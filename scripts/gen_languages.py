#!/usr/bin/env python3
"""Render a Most Used Languages card as a static SVG.

Off-the-shelf cards rank languages by raw byte count, which lets a couple of
notebook repositories bury everything else: a single .ipynb embeds its own
output images as base64. This counts every repository once instead, splitting
each one by its internal language mix, so the card answers "what do you build
with" rather than "which files are biggest".

Reads private repositories too, so the picture is complete. Run it with a
GitHub token available to `gh`:

    python gen_languages.py --out languages.svg

Requires the `gh` CLI, authenticated.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict

# Personal repos plus every org whose work should count.
ORGS = ["ai-phoenix-dev", "dixon-ai", "Naylor-Drainage", "Outdo-media"]

# Languages that describe tooling or output rather than authored work.
EXCLUDE = {"Batchfile", "Makefile", "Dockerfile"}

# GitHub's own linguist colours, so the card reads like the rest of GitHub.
COLOURS = {
    "Python": "#3572A5", "Jupyter Notebook": "#DA5B0B", "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a", "HTML": "#e34c26", "CSS": "#663399",
    "SCSS": "#c6538c", "Shell": "#89e051", "PowerShell": "#012456",
    "Mermaid": "#ff3670", "C": "#555555", "C++": "#f34b7d", "Cython": "#fedf5b",
    "Dockerfile": "#384d54", "Procfile": "#a0a0a0", "Ruby": "#701516",
}
FALLBACK = "#8b949e"

PERSONAL_Q = """
query($cursor: String) {
  viewer { repositories(first: 100, after: $cursor,
                        ownerAffiliations: [OWNER], isFork: false) {
    pageInfo { hasNextPage endCursor }
    nodes { nameWithOwner isArchived
            languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } } } } } } }
"""

ORG_Q = """
query($cursor: String, $org: String!) {
  organization(login: $org) { repositories(first: 100, after: $cursor, isFork: false) {
    pageInfo { hasNextPage endCursor }
    nodes { nameWithOwner isArchived
            languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } } } } } } }
"""


def graphql(query, **variables):
    cmd = ["gh", "api", "graphql", "--paginate", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd += ["-F", f"{key}={value}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"gh failed: {out.stderr.strip()[:300]}")
    # --paginate concatenates one JSON document per page.
    decoder, pos, pages = json.JSONDecoder(), 0, []
    text = out.stdout.strip()
    while pos < len(text):
        doc, pos = decoder.raw_decode(text, pos)
        pages.append(doc)
        while pos < len(text) and text[pos] in " \n\r\t":
            pos += 1
    return pages


def collect(include_archived=False):
    """Map each repository to its language byte counts."""
    repos = defaultdict(Counter)

    def absorb(nodes):
        for node in nodes or []:
            if node.get("isArchived") and not include_archived:
                continue
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                if name not in EXCLUDE:
                    repos[node["nameWithOwner"]][name] += edge["size"]

    for page in graphql(PERSONAL_Q):
        absorb(page["data"]["viewer"]["repositories"]["nodes"])
    for org in ORGS:
        for page in graphql(ORG_Q, org=org):
            org_data = page.get("data", {}).get("organization")
            if org_data:
                absorb(org_data["repositories"]["nodes"])
    return repos


def normalise(repos):
    """Weight every repository equally, split by its internal language mix."""
    shares = Counter()
    for langs in repos.values():
        total = sum(langs.values())
        if not total:
            continue
        for name, size in langs.items():
            shares[name] += size / total
    grand = sum(shares.values()) or 1
    return [(name, value / grand * 100) for name, value in shares.most_common()]


def render(ranked, repo_count, top=6, width=340):
    """Build the SVG: a stacked bar over a two-column legend."""
    shown = ranked[:top]
    rest = sum(pct for _, pct in ranked[top:])
    if rest > 0.5:
        shown.append(("Other", rest))
    scale = sum(pct for _, pct in shown) or 1

    bar_x, bar_w, bar_y, radius = 25, width - 50, 55, 4
    segments, offset = [], bar_x
    for name, pct in shown:
        seg = bar_w * pct / scale
        segments.append(
            f'<rect x="{offset:.2f}" y="{bar_y}" width="{max(seg, 0.6):.2f}" '
            f'height="8" fill="{COLOURS.get(name, FALLBACK)}"/>'
        )
        offset += seg

    rows, row_h = [], 20
    for i, (name, pct) in enumerate(shown):
        col, row = i % 2, i // 2
        x = bar_x + col * (bar_w / 2)
        y = bar_y + 32 + row * row_h
        rows.append(
            f'<circle cx="{x + 5:.0f}" cy="{y:.0f}" r="5" '
            f'fill="{COLOURS.get(name, FALLBACK)}"/>'
            f'<text x="{x + 18:.0f}" y="{y + 4:.0f}" class="lang">'
            f'{name} <tspan class="pct">{pct:.1f}%</tspan></text>'
        )

    height = bar_y + 32 + ((len(shown) + 1) // 2) * row_h + 18
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Most used languages, weighted per repository">
  <title>Most Used Languages</title>
  <style>
    .title {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #3FB950 }}
    .sub   {{ font: 400 10px 'Segoe UI', Ubuntu, Sans-Serif; fill: #8b949e }}
    .lang  {{ font: 400 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: #C9D1D9 }}
    .pct   {{ fill: #8b949e }}
  </style>
  <rect x="0.5" y="0.5" rx="{radius + 2}" width="{width - 1}" height="{height - 1}"
        fill="#0D1117" stroke="#30363D"/>
  <text x="25" y="32" class="title">Most Used Languages</text>
  <text x="25" y="46" class="sub">weighted per repository across {repo_count} repos, private included</text>
  <clipPath id="round"><rect x="{bar_x}" y="{bar_y}" rx="{radius}"
        width="{bar_w}" height="8"/></clipPath>
  <g clip-path="url(#round)">{''.join(segments)}</g>
  {''.join(rows)}
</svg>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="languages.svg")
    parser.add_argument("--top", type=int, default=6)
    parser.add_argument("--include-archived", action="store_true")
    args = parser.parse_args()

    repos = collect(args.include_archived)
    ranked = normalise(repos)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(ranked, len(repos), args.top))

    print(f"{args.out}: {len(repos)} repos")
    for name, pct in ranked[: args.top]:
        print(f"   {name:<20}{pct:>6.2f}%")


if __name__ == "__main__":
    main()
