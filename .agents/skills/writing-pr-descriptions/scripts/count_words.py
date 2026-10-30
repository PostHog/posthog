#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "markdown-it-py~=3.0.0",
# ]
# ///
# ruff: noqa: T201 allow print statements
"""
Print the number of words a reviewer reads in a PR body, table cells and inline code included.

Headings, code blocks, HTML tags, images, task list checkboxes, and everything inside <details> do not count.
List markers and other words without a letter or digit do not count.

Usage:
    uv run count_words.py pr-body.md
    gh pr view 123 --json body --jq .body | uv run count_words.py -
"""

from __future__ import annotations

import re
import sys
import argparse
from html.parser import HTMLParser
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore

UNCOUNTED_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "pre", "details"}
TASK_MARKER = re.compile(r"^\[[ xX]\](?=\s|$)")


class WordCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.open_uncounted_tags: list[str] = []
        self.words = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in UNCOUNTED_TAGS:
            self.open_uncounted_tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.open_uncounted_tags:
            while self.open_uncounted_tags.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        if not self.open_uncounted_tags:
            self.words += sum(1 for word in data.split() if any(char.isalnum() for char in word))

    def close(self) -> None:
        super().close()
        if self.open_uncounted_tags:
            raise ValueError(
                f"<{self.open_uncounted_tags[0]}> is never closed, so GitHub hides everything after it. Close it and run again."
            )


def render_task_markers_as_checkboxes(state: StateCore) -> None:
    """Render GitHub task list markers as checkbox tags, as GitHub does, so they parse as markup."""
    for list_item, inline in zip(state.tokens, state.tokens[2:]):
        if list_item.type == "list_item_open" and inline.type == "inline":
            inline.content = TASK_MARKER.sub('<input type="checkbox">', inline.content, count=1)


def count_words(markdown: str) -> int:
    parser = MarkdownIt("commonmark").enable("table")
    parser.core.ruler.before("inline", "task_markers", render_task_markers_as_checkboxes)
    counter = WordCounter()
    counter.feed(parser.render(markdown))
    counter.close()
    return counter.words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("body", help="PR body markdown file, or - to read stdin")
    args = parser.parse_args()
    try:
        body = sys.stdin.buffer.read() if args.body == "-" else Path(args.body).read_bytes()
        print(count_words(body.decode("utf-8-sig")))
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
