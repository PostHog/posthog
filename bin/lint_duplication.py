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
import hashlib
import argparse
import tempfile
import subprocess
import collections
from dataclasses import dataclass
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


@dataclass(frozen=True, kw_only=True, slots=True)
class Limits:
    production: int
    test: int


def load_limits() -> Limits:
    data = json.loads(LIMITS_PATH.read_text())
    return Limits(production=int(data["production"]), test=int(data["test"]))


LIMITS = load_limits()
APP_MAX_NEW_CLONE_TOKENS = LIMITS.production
TEST_MAX_NEW_CLONE_TOKENS = LIMITS.test

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


def clone_key(clone: dict) -> tuple[frozenset, str]:
    """Pair key, insensitive to which side jscpd calls first and to where in
    the files the fragment sits.

    Keying on the fragment text (not the span) means edits elsewhere in the
    files do not re-flag an old clone as new; editing the duplicated block
    itself does, which is what the gate is for.
    """
    pair = frozenset((clone["firstFile"]["name"], clone["secondFile"]["name"]))
    return pair, hashlib.sha256(clone["fragment"].encode()).hexdigest()


def mark_new_clones(current: list[dict], baseline: list[dict]) -> None:
    """Flag clones the baseline cannot account for, counting occurrences.

    A fragment already copied once between two files is grandfathered only
    for as many copies as the baseline holds: a third copy of the same
    fragment in the same file pair is new duplication and must be flagged.
    """
    available = collections.Counter(clone_key(clone) for clone in baseline)
    for clone in current:
        key = clone_key(clone)
        if available[key] > 0:
            available[key] -= 1
            clone["isNew"] = False
        else:
            clone["isNew"] = True


def resolve_baseline(base: str, repo: Path) -> str:
    """Return the ref to compare clones against.

    The branch point, not the base tip: jscpd matches clones with their
    locations, so a file that moved on the base since the branch forked
    re-flags every old clone inside it as new. Comparing against the
    merge-base keeps pre-existing duplication out of the gate no matter
    how far behind the branch falls.
    """
    merge_base = subprocess.run(
        ["git", "merge-base", base, "HEAD"], capture_output=True, text=True, cwd=repo
    ).stdout.strip()
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

    if args.report_dir:
        # Written before the scans so a crash can never leave a stale "ok":
        # the CI report can then tell "the scan failed" from "the branch
        # predates the check" (no files at all).
        (Path(args.report_dir) / "duplication-scan-status.json").write_text(json.dumps({"status": "failed"}) + "\n")

    repo = Path(args.path).resolve()
    if not repo.is_dir():
        print(f"Scan path {repo} does not exist.")
        return 2

    baseline = resolve_baseline(args.base, repo)
    print(f"Comparing clones against {baseline}")

    # jscpd's own --baseline-from-ref mismatches clones whose files moved on
    # the base since the branch forked, and some stable pairs it re-flags
    # with no visible cause. Scan both trees with identical flags and diff
    # the clone sets ourselves instead: a clone is new only when no clone in
    # the baseline pairs the same files over the same fragment. jscpd merges
    # repeated occurrences of one fragment into a single clone, so a repeat
    # copy inside an already-duplicated file pair is not detectable here;
    # new file pairs and edited blocks are.
    scan_failed = False
    with tempfile.TemporaryDirectory(prefix="jscpd-") as tmp:
        tmp_path = Path(tmp)
        baseline_worktree = tmp_path / "baseline-worktree"
        # Registrations from runs killed mid-scan point at paths that no
        # longer exist; drop them before adding a fresh one.
        subprocess.run(["git", "worktree", "prune"], capture_output=True, cwd=repo)
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(baseline_worktree), baseline],
            capture_output=True,
            text=True,
            cwd=repo,
        )
        if add.returncode != 0:
            print(add.stderr[-2000:])
            print(f"duplication lint could not check out the baseline {baseline}")
            return 2
        try:
            current_clones = run_jscpd(repo, tmp_path / "current-report")
            baseline_clones = run_jscpd(baseline_worktree, tmp_path / "baseline-report")
        except SystemExit:
            scan_failed = True
            current_clones = []
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(baseline_worktree)], capture_output=True, cwd=repo
            )

    if scan_failed:
        return 2

    mark_new_clones(current_clones, baseline_clones)
    print(
        f"{len(current_clones)} clones in this tree, {sum(1 for c in current_clones if c['isNew'])} not in the baseline"
    )
    if args.report_dir:
        (Path(args.report_dir) / "duplication-scan-status.json").write_text(json.dumps({"status": "ok"}) + "\n")

    failures = find_gate_failures(current_clones)
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
