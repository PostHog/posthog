#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Print the number of prose words in a PR body.

Headings, tables, code blocks, HTML tags, images, task list checkboxes, and everything inside <details> are not prose.
List markers and other words without a letter or digit do not count.

Usage:
    uv run python count_prose_words.py pr-body.md
    gh pr view 123 --json body --jq .body | uv run python count_prose_words.py -
"""

from __future__ import annotations

import re
import sys
import argparse
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore

NON_PROSE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "table", "pre", "details"}
TASK_MARKER = re.compile(r"^\[[ xX]\](?=\s|$)")


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


def render_task_markers_as_checkboxes(state: StateCore) -> None:
    """Render GitHub task list markers as checkbox tags, as GitHub does, so they parse as markup."""
    for list_item, inline in zip(state.tokens, state.tokens[2:]):
        if list_item.type == "list_item_open" and inline.type == "inline":
            inline.content = TASK_MARKER.sub('<input type="checkbox">', inline.content, count=1)


def count_prose_words(markdown: str) -> int:
    parser = MarkdownIt("commonmark").enable("table")
    parser.core.ruler.before("inline", "task_markers", render_task_markers_as_checkboxes)
    counter = ProseWordCounter()
    counter.feed(parser.render(markdown))
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
