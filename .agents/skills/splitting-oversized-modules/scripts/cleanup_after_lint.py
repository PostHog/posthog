#!/usr/bin/env python3
"""Tidy the leftovers `ruff --fix` cannot, then re-verify.

    uv run --no-project python cleanup_after_lint.py products/foo/backend/logic

Run after `ruff check --fix`, which is what creates the first leftover:

  - `if TYPE_CHECKING: pass` — ruff removes the unused imports inside the block but
    leaves the emptied block behind. Deleted here, since it is never meaningful.
  - `# --- Section ---` dividers — these were navigation inside the monolith and the
    module name says it now. Only *reported*, not deleted: a divider inside a module
    that still holds two clusters may be worth keeping, and that is a judgment call.

Removing the emptied block leaves its `from typing import TYPE_CHECKING` unused, so
`ruff check --fix` has to run a *second* time after this. And since deleting dead blocks
changes files you may already have verified, re-run verify_pure_move.py too:

    ruff check <package>/ --fix && ruff format <package>/
    uv run --no-project python verify_pure_move.py <original> <package>
"""

from __future__ import annotations

import re
import ast
import argparse
from pathlib import Path

DIVIDER = re.compile(r"^#\s*-{2,}.*-{2,}\s*$")


def drop_empty_type_checking(source: str) -> str:
    """Remove `if TYPE_CHECKING: pass` blocks, plus the blank lines they leave."""
    spans: list[tuple[int, int]] = []
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
            and not node.orelse
        ):
            spans.append((node.lineno, node.end_lineno or node.lineno))
    if not spans:
        return source
    lines = source.splitlines(keepends=True)
    for start, end in reversed(spans):
        stop = end
        while stop < len(lines) and lines[stop].strip() == "":
            stop += 1
        del lines[start - 1 : stop]
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()

    dividers: list[str] = []
    for path in sorted(args.package.glob("*.py")):
        source = path.read_text()
        cleaned = drop_empty_type_checking(source)
        if cleaned != source:
            path.write_text(cleaned)
            print(f"dropped dead TYPE_CHECKING block in {path.name}")
        for number, line in enumerate(cleaned.splitlines(), start=1):
            if DIVIDER.match(line):
                dividers.append(f"{path.name}:{number} {line.strip()}")

    if dividers:
        print("\nsection dividers left over from the monolith — remove unless the module still needs them:")
        for entry in dividers:
            print(f"  {entry}")
    print("\nnext: ruff check --fix again (TYPE_CHECKING is now unused), ruff format, verify_pure_move.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
