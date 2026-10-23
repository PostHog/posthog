#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Print the number of prose words in a PR body file.

Headings, tables, fenced code blocks, <details> blocks and HTML comments are not prose.

Usage:
    python3 count_prose_words.py pr-body.md
"""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def count_prose_words(markdown: str) -> int:
    in_code = False
    in_details = False
    words = 0
    for line in HTML_COMMENT.sub("", markdown).splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if stripped.startswith("<details>"):
            in_details = True
        if stripped.startswith("</details>"):
            in_details = False
            continue
        if in_code or in_details or stripped.startswith(("|", "#")):
            continue
        words += len(stripped.split())
    return words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("body", type=Path, help="PR body markdown file")
    args = parser.parse_args()
    if not args.body.is_file():
        parser.error(f"{args.body} is not a file")
    print(count_prose_words(args.body.read_text()))


if __name__ == "__main__":
    sys.exit(main())
