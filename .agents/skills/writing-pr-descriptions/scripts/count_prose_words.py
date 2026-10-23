#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Print the number of prose words in a PR body.

Headings, tables, code blocks, HTML tags, images, and everything inside <details> are not prose.
List markers, checkboxes and other words without a letter or digit do not count.

Usage:
    uv run python count_prose_words.py pr-body.md
    gh pr view 123 --json body --jq .body | uv run python count_prose_words.py -
"""

from __future__ import annotations

import sys
import argparse
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt

NON_PROSE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "table", "pre", "details"}


class ProseWordCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.non_prose_depth = 0
        self.words = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in NON_PROSE_TAGS:
            self.non_prose_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in NON_PROSE_TAGS and self.non_prose_depth:
            self.non_prose_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.non_prose_depth:
            self.words += sum(1 for word in data.split() if any(char.isalnum() for char in word))


def count_prose_words(markdown: str) -> int:
    counter = ProseWordCounter()
    counter.feed(MarkdownIt("commonmark").enable("table").render(markdown))
    counter.close()
    return counter.words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("body", help="PR body markdown file, or - to read stdin")
    args = parser.parse_args()
    try:
        markdown = sys.stdin.read() if args.body == "-" else Path(args.body).read_text()
    except OSError as error:
        parser.error(str(error))
    print(count_prose_words(markdown))


if __name__ == "__main__":
    main()
