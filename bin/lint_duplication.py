#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Gate a branch on new Python code duplication.

Runs jscpd over the repo and compares clone fingerprints against the base
ref, so only duplication the branch introduces can fail the gate. Existing
duplication is grandfathered in. App code and test code are held to
different bars: a clone between two test files may run longer before it
fails, because repeated setup is idiomatic in tests.
"""

import re
import sys
import json
import argparse
import tempfile
import subprocess
from pathlib import Path

JSCPD_VERSION = "5.1.1"

# jscpd scan floor. Anything smaller is never reported at all.
SCAN_MIN_LINES = 10
SCAN_MIN_TOKENS = 70

# A new clone fails the gate at this many tokens. ~70 tokens is 10-15 lines
# of Python; ~150 tokens is 25-35 lines.
APP_MAX_NEW_CLONE_TOKENS = 70
TEST_MAX_NEW_CLONE_TOKENS = 150

TEST_PATH = re.compile(r"(^|/)(test|tests)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$")


def is_test_file(path: str) -> bool:
    return bool(TEST_PATH.search(path))


def find_gate_failures(clones: list[dict]) -> list[tuple[dict, bool]]:
    """Keep the new clones that fail the gate, worst first.

    A clone between two test files gets the looser bar; anything touching
    app code is held to the app bar.
    """
    failures = []
    for clone in clones:
        if not clone.get("isNew"):
            continue
        both_tests = is_test_file(clone["firstFile"]["name"]) and is_test_file(clone["secondFile"]["name"])
        bar = TEST_MAX_NEW_CLONE_TOKENS if both_tests else APP_MAX_NEW_CLONE_TOKENS
        if clone["tokens"] >= bar:
            failures.append((clone, both_tests))
    failures.sort(key=lambda item: -item[0]["tokens"])
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master", help="git ref to compare clones against")
    parser.add_argument("--path", default=".", help="repository root to scan")
    args = parser.parse_args()

    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", args.base], capture_output=True).returncode != 0:
        print(f"Base ref {args.base!r} not found. Fetch it first, e.g.:")
        print(f"  git fetch --no-tags --depth=1 origin master:refs/remotes/origin/master")
        return 2

    with tempfile.TemporaryDirectory(prefix="jscpd-") as out_dir:
        proc = subprocess.run(
            [
                "npx",
                "--yes",
                f"jscpd@{JSCPD_VERSION}",
                "--format",
                "python",
                "--min-lines",
                str(SCAN_MIN_LINES),
                "--min-tokens",
                str(SCAN_MIN_TOKENS),
                "--skip-comments",
                "--reporters",
                "json",
                "--output",
                out_dir,
                "--ignore",
                "**/migrations/**",
                "--baseline-from-ref",
                args.base,
                args.path,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        report_path = Path(out_dir) / "jscpd-report.json"
        if proc.returncode != 0 or not report_path.exists():
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
            print(f"duplication lint could not run: jscpd exited {proc.returncode}")
            return 2
        clones = json.loads(report_path.read_text())["duplicates"]

    failures = find_gate_failures(clones)

    if not failures:
        print("No new Python code duplication above the bars.")
        return 0

    print("This branch adds new code duplication:")
    for clone, both_tests in failures:
        first, second = clone["firstFile"], clone["secondFile"]
        side = "test" if both_tests else "app"
        print(
            f"  {first['name']}:{first['start']}-{first['end']} <-> "
            f"{second['name']}:{second['start']}-{second['end']} "
            f"({clone['lines']} lines, {clone['tokens']} tokens, {side} code)"
        )
    print()
    print(
        f"New duplication fails at {APP_MAX_NEW_CLONE_TOKENS}+ tokens in app code, "
        f"or {TEST_MAX_NEW_CLONE_TOKENS}+ tokens when both copies live in test files."
    )
    print("Extract the repeated block into a shared helper instead of copying it.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
