#!/usr/bin/env python3
# ruff: noqa: T201
"""Measure a change, or a proposed split of it, against the stamphog size gate and deny list.

Run from the repository root:

    uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --source <ref> [--plan plan.json]

The change is the diff from the merge base of `--base` and `--source` to `--source`.
plan.json maps a PR name to its files: {"pr-1-backend": ["posthog/api/foo.py", ...], ...}.
The numbers come from the stamphog engine in this repo, so they match the hosted review.
The last stdout line is JSON. Exit code 0 means everything fits.
"""

import sys
import json
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path("products/stamphog/packages/pr-approval-agent").resolve()))

import gates  # noqa: E402
import policy  # noqa: E402


def changed_files(base: str, source: str) -> tuple[dict[str, int], dict[str, str]]:
    """Changed lines per path, and each rename's new path to old path.

    A rename counts under its new path only, like the GitHub files API the gate reads.
    """
    merge_base = subprocess.run(
        ["git", "merge-base", base, source], check=True, capture_output=True, text=True
    ).stdout.strip()
    fields = subprocess.run(
        ["git", "diff", "--numstat", "-z", "-M", merge_base, source], check=True, capture_output=True, text=True
    ).stdout.split("\0")
    lines: dict[str, int] = {}
    renames: dict[str, str] = {}
    while fields and fields[0]:
        added, deleted, path = fields.pop(0).split("\t")
        if not path:  # -z puts a rename's old and new path in the next two fields
            old, path = fields.pop(0), fields.pop(0)
            renames[path] = old
        lines[path] = 0 if added == "-" else int(added) + int(deleted)
    return lines, renames


def check(lines: dict[str, int]) -> dict:
    """The engine's size gate (per-scope budgets plus the whole-PR roof) and deny categories."""
    counted = {path: n for path, n in lines.items() if not gates.is_size_exempt(path)}
    budgets = policy.resolve(gates.POLICY, list(lines))
    problems = []
    for scope in budgets.line_scopes:
        used = sum(counted.get(path, 0) for path in scope.files)
        if used > scope.ceiling:
            problems.append(f"{used} lines in {scope.path or 'global pool'} > {scope.ceiling}")
    for scope in budgets.file_scopes:
        used = sum(path in counted for path in scope.files)
        if used > scope.ceiling:
            problems.append(f"{used} files in {scope.path or 'global pool'} > {scope.ceiling}")
    if sum(counted.values()) > budgets.line_roof:
        problems.append(f"{sum(counted.values())} lines > roof {budgets.line_roof}")
    if len(counted) > budgets.file_roof:
        problems.append(f"{len(counted)} files > roof {budgets.file_roof}")
    deny = gates.detect_deny_categories(list(lines))
    if deny:
        problems.append(f"deny categories {deny}: stamphog refuses, a human must review")
    return {
        "substantive_lines": sum(counted.values()),
        "substantive_files": len(counted),
        "line_roof": budgets.line_roof,
        "file_roof": budgets.file_roof,
        "deny_categories": deny,
        "problems": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--source", default="HEAD", help="Commit that holds the whole change")
    parser.add_argument("--plan", help="JSON file that maps each PR name to its files")
    parser.add_argument("--verbose", action="store_true", help="Print changed lines per file")
    args = parser.parse_args()

    lines, renames = changed_files(args.base, args.source)
    if args.verbose:
        for path, n in sorted(lines.items()):
            print(f"{n:>6}  {'exempt' if gates.is_size_exempt(path) else 'counts':<6}  {path}")

    report: dict = {"whole_change": check(lines)}
    if args.plan:
        plan: dict[str, list[str]] = json.loads(Path(args.plan).read_text())
        planned = [path for paths in plan.values() for path in paths]
        known = set(lines) | set(renames.values())
        report["unplanned_files"] = sorted(known - set(planned))
        report["unknown_or_duplicated_files"] = sorted(
            {path for path in planned if path not in known or planned.count(path) > 1}
        )
        # git restore needs both paths of a rename in one group, or the old file stays behind.
        report["split_renames"] = sorted(
            {
                f"{old} -> {new}"
                for paths in plan.values()
                for new, old in renames.items()
                if (new in paths) != (old in paths)
            }
        )
        report["prs"] = {
            name: check({path: lines[path] for path in paths if path in lines}) for name, paths in plan.items()
        }
        groups_ok = all(not pr["problems"] for pr in report["prs"].values())
        report["ok"] = groups_ok and not (
            report["unplanned_files"] or report["unknown_or_duplicated_files"] or report["split_renames"]
        )
    else:
        report["ok"] = not report["whole_change"]["problems"]
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
