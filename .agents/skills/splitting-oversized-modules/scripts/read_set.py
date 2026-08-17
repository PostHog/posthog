#!/usr/bin/env python3
"""Token cost of the files an agent must read to make a change.

    # baseline, before touching anything
    uv run --no-project --with tiktoken python read_set.py \
        products/foo/backend/logic.py products/foo/backend/tests/test_logic.py

    # after the split, the files one representative change actually needs
    uv run --no-project --with tiktoken python read_set.py \
        products/foo/backend/logic/comments.py products/foo/backend/tests/logic/test_comments.py

Measure before you split, so the payoff is a number rather than a preference. Pick
three or four representative changes across different concerns, not one — a split
helps unevenly, and the average is what you are buying.

Counting uses tiktoken's cl100k_base. It is not any specific model's tokenizer, so
treat the ratio as the result and the absolute number as an estimate.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import tiktoken


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--rev", help="measure these paths at a git revision instead of on disk (e.g. HEAD)")
    args = parser.parse_args()

    encoding = tiktoken.get_encoding("cl100k_base")
    rows: list[tuple[int, int, str]] = []
    for path in args.files:
        if args.rev:
            text = subprocess.run(
                ["git", "show", f"{args.rev}:{path}"], capture_output=True, text=True, check=True
            ).stdout
        else:
            text = path.read_text()
        rows.append((len(encoding.encode(text)), len(text.splitlines()), str(path)))

    for tokens, loc, path in sorted(rows, reverse=True):
        print(f"{tokens:>8,} tok  {loc:>5} loc  {path}")
    print(f"{sum(r[0] for r in rows):>8,} tok  {sum(r[1] for r in rows):>5} loc  TOTAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
