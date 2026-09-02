#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Gate a branch on new code duplication in Python and TypeScript.

Runs jscpd over this tree and over a worktree of the branch point, and
diffs the two clone sets, so only duplication the branch introduces can
fail the gate. Existing duplication is grandfathered in. App code and
test code are held to different bars: a clone between two test files may
run longer before it fails, because repeated setup is idiomatic in tests.

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
IGNORE = "**/migrations/**,**/generated/**,**/generated.*,.depot/**"

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
    for clone, _ in failures:
        findings[clone_language(clone)].append(
            {
                "first_file": clone["firstFile"]["name"],
                "first_start": clone["firstFile"]["start"],
                "second_file": clone["secondFile"]["name"],
                "second_start": clone["secondFile"]["start"],
                "lines": clone["lines"],
                "tokens": clone["tokens"],
            }
        )
    return findings


def run_jscpd(scan_root: Path, out_dir: Path) -> list[dict]:
    """Scan one tree with jscpd and return its clone list."""
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
            str(out_dir),
            "--ignore",
            IGNORE,
            ".",
        ],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=scan_root,
    )
    report_path = out_dir / "jscpd-report.json"
    if proc.returncode != 0 or not report_path.exists():
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        print(f"duplication lint could not run: jscpd exited {proc.returncode} scanning {scan_root}")
        raise SystemExit(2)
    return json.loads(report_path.read_text())["duplicates"]


def clone_key(clone: dict) -> frozenset:
    """Pair key, insensitive to which side jscpd calls first."""
    first = (clone["firstFile"]["name"], clone["firstFile"]["start"], clone["firstFile"]["end"])
    second = (clone["secondFile"]["name"], clone["secondFile"]["start"], clone["secondFile"]["end"])
    return frozenset((first, second))


def resolve_baseline(base: str) -> str:
    """Return the ref to compare clones against.

    The branch point, not the base tip: jscpd matches clones with their
    locations, so a file that moved on the base since the branch forked
    re-flags every old clone inside it as new. Comparing against the
    merge-base keeps pre-existing duplication out of the gate no matter
    how far behind the branch falls.
    """
    merge_base = subprocess.run(["git", "merge-base", base, "HEAD"], capture_output=True, text=True).stdout.strip()
    if merge_base:
        return merge_base
    print(f"Could not resolve the merge-base with {base!r} (shallow history?). Falling back to {base!r}.")
    return base


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

    baseline = resolve_baseline(args.base)
    print(f"Comparing clones against {baseline}")

    # jscpd's own --baseline-from-ref mismatches clones whose files moved on
    # the base since the branch forked, and some stable pairs it re-flags
    # with no visible cause. Scan both trees with identical flags and diff
    # the clone sets ourselves instead: a clone is new only when its pair
    # (both sides' path and span, either order) is absent from the baseline.
    with tempfile.TemporaryDirectory(prefix="jscpd-") as tmp:
        tmp_path = Path(tmp)
        baseline_worktree = tmp_path / "baseline-worktree"
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(baseline_worktree), baseline],
            capture_output=True,
            text=True,
        )
        if add.returncode != 0:
            print(add.stderr[-2000:])
            print(f"duplication lint could not check out the baseline {baseline}")
            return 2
        try:
            current_clones = run_jscpd(Path(args.path).resolve(), tmp_path / "current-report")
            baseline_clones = run_jscpd(baseline_worktree, tmp_path / "baseline-report")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(baseline_worktree)], capture_output=True)

    baseline_keys = {clone_key(clone) for clone in baseline_clones}
    clones = []
    for clone in current_clones:
        clone["isNew"] = clone_key(clone) not in baseline_keys
        clones.append(clone)
    print(f"{len(clones)} clones in this tree, {sum(1 for c in clones if c['isNew'])} not in the baseline")

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
