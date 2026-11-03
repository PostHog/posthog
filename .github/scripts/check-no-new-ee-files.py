#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Fail when a branch adds a file under `ee/` without human approval.

`ee/` is deprecated: new code belongs in `posthog/` or `products/<product>/`. A person
approves a new file by adding its exact path to `EXEMPT` below, which shows up in review.
See `ee/AGENTS.md`.

    check-no-new-ee-files.py --against origin/master [--committed]
"""

from __future__ import annotations

import sys
import argparse
import subprocess

# Approved new files, one exact path each, added by hand after a human agreed in the pull
# request. Never add a glob, because it approves files nobody reviewed.
EXEMPT: frozenset[str] = frozenset(
    {
        "ee/migrations/0068_drop_dashboardprivilege_table.py",
    }
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _paths(*args: str) -> list[str]:
    return [path for path in _git(*args).split("\0") if path]


def _added(args: argparse.Namespace, merge_base: str) -> list[str]:
    """Paths this branch adds under `ee/`. Renames count: they create a new path here."""
    head = ["HEAD"] if args.committed else []
    added = _paths("diff", "-z", "--name-only", "--diff-filter=AR", merge_base, *head, "--", "ee/")
    if args.committed:
        return added
    # `git diff` ignores untracked files, and a new file is often still untracked.
    return added + _paths("ls-files", "-z", "--others", "--exclude-standard", "--", "ee/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--against", default="origin/master", help="diff base ref")
    parser.add_argument("--committed", action="store_true", help="check commits only, not the working tree")
    args = parser.parse_args()

    try:
        merge_base = _git("merge-base", args.against, "HEAD").strip()
    except subprocess.CalledProcessError:
        print(f"No merge base with {args.against}, so the `ee/` check did not run.", file=sys.stderr)
        return 2

    offenders = sorted({path for path in _added(args, merge_base) if path not in EXEMPT})
    if not offenders:
        return 0

    print("This branch adds file(s) under `ee/`, which is deprecated:")
    for path in offenders:
        print(f"  {path}")
    print(
        "\nNew code belongs in `posthog/` or `products/<product>/`. A file that must live in `ee/`\n"
        "needs human approval: ask in the pull request, then add its exact path to `EXEMPT` in\n"
        ".github/scripts/check-no-new-ee-files.py. See `ee/AGENTS.md`."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
