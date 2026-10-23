#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Print the number of prose words in a PR body.

Headings, tables, code, HTML, images, and everything inside <details> are not prose.
List markers, checkboxes and other words without a letter or digit do not count.

Usage:
    uv run python count_prose_words.py pr-body.md
    gh pr view 123 --json body --jq .body | uv run python count_prose_words.py -
"""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

from markdown_it import MarkdownIt

PARSER = MarkdownIt("commonmark").enable("table")
NON_PROSE_OPENERS = {"heading_open", "table_open"}
NON_PROSE_CLOSERS = {"heading_close", "table_close"}
# An HTML block runs to the next blank line, so it can hold visible text after a closing tag.
HTML_PIECE = re.compile(r"<!--.*?-->|<[^>]*>|[^<]+", re.DOTALL)
DETAILS_OPEN = re.compile(r"<details\b", re.IGNORECASE)
DETAILS_CLOSE = re.compile(r"</details\s*>", re.IGNORECASE)


def count_words(text: str) -> int:
    return sum(1 for word in text.split() if any(char.isalnum() for char in word))


def count_prose_words(markdown: str) -> int:
    non_prose_depth = 0
    details_depth = 0
    words = 0
    for block in PARSER.parse(markdown):
        if block.type in NON_PROSE_OPENERS:
            non_prose_depth += 1
        elif block.type in NON_PROSE_CLOSERS:
            non_prose_depth -= 1
        for token in [block, *(block.children or [])]:
            if token.type in ("html_block", "html_inline"):
                pieces = HTML_PIECE.findall(token.content)
            elif token.type in ("text", "code_inline"):
                pieces = [token.content]
            else:
                continue
            is_html = token.type.startswith("html")
            for piece in pieces:
                if is_html and DETAILS_OPEN.match(piece):
                    details_depth += 1
                elif is_html and DETAILS_CLOSE.match(piece):
                    details_depth = max(0, details_depth - 1)
                elif not (is_html and piece.startswith("<")) and not non_prose_depth and not details_depth:
                    words += count_words(piece)
    return words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("body", help="PR body markdown file, or - to read stdin")
    args = parser.parse_args()
    if args.body == "-":
        markdown = sys.stdin.read()
    elif Path(args.body).is_file():
        markdown = Path(args.body).read_text()
    else:
        parser.error(f"{args.body} is not a file")
    print(count_prose_words(markdown))


if __name__ == "__main__":
    main()
