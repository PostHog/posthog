#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Gate a branch on new code duplication in Python and TypeScript.

Runs jscpd over the repo and compares clone fingerprints against the base
ref, so only duplication the branch introduces can fail the gate. Existing
duplication is grandfathered in. App code and test code are held to
different bars: a clone between two test files may run longer before it
fails, because repeated setup is idiomatic in tests.

With --report-dir, also writes one findings file per language for the CI
report comment (.github/scripts/post-duplication-section.mjs).
"""

import re
import sys
import json
import argparse
import tempfile
import subprocess
from pathlib import Path

JSCPD_VERSION = "5.1.1"

FORMATS = "python,typescript,tsx"

# Migrations and generated code duplicate by design; .depot/ is a vendored
# mirror of .github/actions/.
IGNORE = "**/migrations/**,**/generated/**,.depot/**"

# jscpd scan floor. Anything smaller is never reported at all.
SCAN_MIN_LINES = 10
SCAN_MIN_TOKENS = 70

TEST_PATH = re.compile(
    r"(^|/)(test|tests|__tests__|__mocks__)/"
    r"|(^|/)test_[^/]*\.py$"
    r"|_test\.py$"
    r"|conftest\.py$"
    r"|\.test\.tsx?$"
    r"|\.spec\.tsx?$"
    r"|\.stories\.tsx?$"
)

LIMITS_PATH = Path(__file__).with_name("lint-duplication.limits.json")


def load_limits() -> tuple[int, int]:
    data = json.loads(LIMITS_PATH.read_text())
    return int(data["production"]), int(data["test"])


# A new clone fails the gate at this many tokens. ~70 tokens is 10-15 lines
# of Python or TypeScript; ~150 tokens is 25-35 lines.
APP_MAX_NEW_CLONE_TOKENS, TEST_MAX_NEW_CLONE_TOKENS = load_limits()

LANGUAGES = ("python", "typescript")


def is_test_file(path: str) -> bool:
    return bool(TEST_PATH.search(path))


def clone_language(clone: dict) -> str:
    return "python" if clone.get("format") == "python" else "typescript"


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


def build_findings(failures: list[tuple[dict, bool]]) -> dict[str, list[dict]]:
    """Shape the failures as per-language findings for the CI report files."""
    findings: dict[str, list[dict]] = {language: [] for language in LANGUAGES}
    for clone, both_tests in failures:
        findings[clone_language(clone)].append(
            {
                "first_file": clone["firstFile"]["name"],
                "first_start": clone["firstFile"]["start"],
                "first_end": clone["firstFile"]["end"],
                "second_file": clone["secondFile"]["name"],
                "second_start": clone["secondFile"]["start"],
                "second_end": clone["secondFile"]["end"],
                "lines": clone["lines"],
                "tokens": clone["tokens"],
                "test": both_tests,
            }
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/master", help="git ref to compare clones against")
    parser.add_argument("--path", default=".", help="repository root to scan")
    parser.add_argument(
        "--report-dir",
        default=None,
        help="write duplication-findings-<language>.json files for the CI report into this directory",
    )
    args = parser.parse_args()

    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", args.base], capture_output=True).returncode != 0:
        print(f"Base ref {args.base!r} not found. Fetch it first, e.g.:")
        print("  git fetch --no-tags --depth=1 origin master:refs/remotes/origin/master")
        return 2

    with tempfile.TemporaryDirectory(prefix="jscpd-") as out_dir:
        proc = subprocess.run(
            [
                "npx",
                "--yes",
                f"jscpd@{JSCPD_VERSION}",
                "--format",
                FORMATS,
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
                IGNORE,
                "--baseline-from-ref",
                args.base,
                args.path,
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        report_path = Path(out_dir) / "jscpd-report.json"
        if proc.returncode != 0 or not report_path.exists():
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
            print(f"duplication lint could not run: jscpd exited {proc.returncode}")
            return 2
        clones = json.loads(report_path.read_text())["duplicates"]

    failures = find_gate_failures(clones)
    findings = build_findings(failures)

    if args.report_dir:
        report_names = {"python": "duplication-findings-python.json", "typescript": "duplication-findings-ts.json"}
        for language, language_findings in findings.items():
            (Path(args.report_dir) / report_names[language]).write_text(json.dumps(language_findings, indent=2) + "\n")

    if not failures:
        print("No new code duplication above the bars.")
        return 0

    print("This branch adds new code duplication:")
    for clone, both_tests in failures:
        first, second = clone["firstFile"], clone["secondFile"]
        side = "test" if both_tests else "app"
        print(
            f"  [{clone_language(clone)}] {first['name']}:{first['start']}-{first['end']} <-> "
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
