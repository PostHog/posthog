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

# A branch that moves a file repoints every import that names it. Where such
# an import sits inside an already-duplicated block, the block's text changes
# and the gate would read a pre-existing clone as new. Hashing the text with
# the module paths blanked out keeps a repoint from spending the gate's
# budget. The imported names stay in the hash, so a real edit still counts.
# The pattern for each language matches only that language's import syntax,
# and the lookbehind keeps method calls such as `db.from('events')` out.
TS_MODULE_SPECIFIER = re.compile(
    r"""(?P<lead>(?<![.\w])(?:from|import)\s+|(?<![.\w])(?:require|import)\s*\(\s*)(?P<q>['"])[^'"\n]*(?P=q)"""
)
PY_IMPORT_MODULE = re.compile(r"^(?P<lead>\s*(?:from|import)\s+)[.\w]+", re.MULTILINE)

FRAGMENT_NORMALIZERS = {
    "python": (PY_IMPORT_MODULE, r"\g<lead><module>"),
    "typescript": (TS_MODULE_SPECIFIER, r"\g<lead>\g<q><module>\g<q>"),
}

# Two files that import the same modules are not copy-paste that a shared
# helper can absorb, so the gate's advice does not apply to a clone that
# spans nothing else. IMPORT_STATEMENT_START finds the statements, and
# IMPORT_LINE also accepts the lines an import wraps onto: its bindings,
# its braces, and the tail that carries the module path.
IMPORT_STATEMENT_START = {
    "python": re.compile(r"^\s*(?:from|import)\s"),
    "typescript": re.compile(r"^\s*(?:import\b(?!\s*\.)|export\s+(?:\*|type\s|\{))"),
}
IMPORT_LINE = {
    "python": re.compile(r"^\s*(?:(?:from|import)\s.*|[\w.,\s*()]+)\s*$"),
    "typescript": re.compile(
        r"^\s*(?:"
        r"import\b(?!\s*\.).*"
        r"|export\s+(?:\*|type\s|\{).*"
        r"""|\}?\s*from\s*['"][^'"]*['"];?"""
        r"|[\w$,*\s]+(?:\bas\b[\w$,\s]+)?"
        r"|[{}]"
        r")\s*$"
    ),
}

LIMITS_PATH = Path(__file__).with_name("lint-duplication.limits.json")
SCAN_TIMEOUT_SECONDS = 240


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


def is_import_only(clone: dict) -> bool:
    """True when the clone spans import statements and nothing else."""
    language = clone_language(clone)
    lines = [line for line in clone["fragment"].splitlines() if line.strip()]
    if not any(IMPORT_STATEMENT_START[language].match(line) for line in lines):
        return False
    return all(IMPORT_LINE[language].match(line) for line in lines)


def find_gate_failures(clones: list[dict]) -> list[tuple[dict, bool]]:
    """Keep the new clones that fail the gate, worst first.

    A clone between two test files gets the looser bar; anything touching
    app code is held to the app bar.
    """
    failures = []
    for clone in clones:
        if not clone.get("isNew") or is_import_only(clone):
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
    try:
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
            # Two scans must finish inside the CI job's timeout-minutes, or the
            # job dies before the failure section can post.
            timeout=SCAN_TIMEOUT_SECONDS,
            cwd=scan_root,
        )
    except subprocess.TimeoutExpired:
        print(f"duplication lint could not run: jscpd exceeded {SCAN_TIMEOUT_SECONDS}s scanning {scan_root}")
        raise SystemExit(2) from None
    report_path = out_dir / "jscpd-report.json"
    if proc.returncode != 0 or not report_path.exists():
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        print(f"duplication lint could not run: jscpd exited {proc.returncode} scanning {scan_root}")
        raise SystemExit(2)
    return json.loads(report_path.read_text())["duplicates"]


def normalize_fragment(text: str, language: str) -> str:
    """Return the text with the module path of every import blanked out."""
    pattern, replacement = FRAGMENT_NORMALIZERS[language]
    return pattern.sub(replacement, text)


def attach_fragment_hashes(clones: list[dict], tree: Path) -> None:
    """Record a hash of both copies of every clone, while the tree is on disk.

    jscpd reports the text of one side only, and which side that is follows
    the order it walked the files, so a branch that adds, removes or moves a
    file can flip it. The two copies are not always identical, because jscpd
    matches on token shape rather than on characters, so a flip rewrites the
    clone's text and the gate reads a pre-existing clone as new. Hashing both
    copies and sorting the pair gives the clone an identity that survives the
    walk order.
    """
    lines_by_path: dict[str, list[str] | None] = {}

    def lines_of(name: str) -> list[str] | None:
        if name not in lines_by_path:
            try:
                lines_by_path[name] = (tree / name).read_text().splitlines()
            except OSError:
                lines_by_path[name] = None
        return lines_by_path[name]

    for clone in clones:
        language = clone_language(clone)
        hashes = []
        for side in ("firstFile", "secondFile"):
            info = clone[side]
            lines = lines_of(info["name"])
            # jscpd's own text is the first side's, and it is the only copy
            # available for a file the scan has since lost.
            text = "\n".join(lines[info["start"] - 1 : info["end"]]) if lines else clone["fragment"]
            hashes.append(hashlib.sha256(normalize_fragment(text, language).encode()).hexdigest())
        clone["fragmentHashes"] = sorted(hashes)


def parse_renames(name_status_z: str) -> dict[str, str]:
    """Read `git diff --name-status -z` output into a new path -> old path map.

    Each record is a status field and then one path, except a rename or a
    copy, which carries the source and the destination. Walking the fields
    keeps the two shapes apart; reading a fixed number of fields per record
    would misalign every record after the first rename.
    """
    fields = [field for field in name_status_z.split("\0") if field]
    renames: dict[str, str] = {}
    index = 0
    while index < len(fields):
        status = fields[index]
        if status.startswith(("R", "C")) and index + 2 < len(fields):
            renames[fields[index + 2]] = fields[index + 1]
            index += 3
        else:
            index += 2
    return renames


def find_renames(baseline: str, repo: Path) -> dict[str, str]:
    """Map each path the branch moved to where it sat at the baseline.

    jscpd identifies a clone by the two files it spans, so a file the branch
    moved takes every clone it was already part of with it, and all of them
    read as new. Git's own rename detection gives the translation back. It
    compares the baseline against the working tree, which is the tree jscpd
    scans. A move git does not detect, because the file also changed too
    much to pair up, leaves those clones flagged, which is the safe
    direction for a gate.
    """
    proc = subprocess.run(
        ["git", "diff", "--name-status", "--find-renames", "-z", baseline],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    if proc.returncode != 0:
        print(f"Could not list renames against {baseline}; moved files will read as new duplication.")
        return {}
    return parse_renames(proc.stdout)


def clone_key(clone: dict, renames: dict[str, str] | None = None) -> tuple[frozenset, tuple[str, ...]]:
    """Pair key, insensitive to which side jscpd calls first and to where in
    the files the fragment sits.

    Keying on the fragment text (not the span) means edits elsewhere in the
    files do not re-flag an old clone as new; editing the duplicated block
    itself does, which is what the gate is for. Both halves of the key read
    at their baseline spelling: `renames` translates a moved file back to
    where it sat, and the hashes ignore import module paths, so moving a
    file does not spend the budget.
    """
    renames = renames or {}
    pair = frozenset(renames.get(side["name"], side["name"]) for side in (clone["firstFile"], clone["secondFile"]))
    return pair, tuple(clone["fragmentHashes"])


def mark_new_clones(current: list[dict], baseline: list[dict], renames: dict[str, str] | None = None) -> None:
    """Flag clones the baseline cannot account for, counting occurrences.

    A fragment already copied once between two files is grandfathered only
    for as many copies as the baseline holds: a third copy of the same
    fragment in the same file pair is new duplication and must be flagged.
    """
    available = collections.Counter(clone_key(clone) for clone in baseline)
    for clone in current:
        key = clone_key(clone, renames)
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

    if args.report_dir:
        # Written before any check or scan so an early exit can never leave a
        # stale "ok": the CI report can then tell "the scan failed" from "the
        # branch predates the check" (no files at all).
        (Path(args.report_dir) / "duplication-scan-status.json").write_text(json.dumps({"status": "failed"}) + "\n")

    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", args.base], capture_output=True).returncode != 0:
        print(f"Base ref {args.base!r} not found. Fetch it first, e.g.:")
        print("  git fetch --no-tags --depth=1 origin master:refs/remotes/origin/master")
        return 2

    repo = Path(args.path).resolve()
    if not repo.is_dir():
        print(f"Scan path {repo} does not exist.")
        return 2

    baseline = resolve_baseline(args.base, repo)
    print(f"Comparing clones against {baseline}")

    renames = find_renames(baseline, repo)
    if renames:
        print(f"{len(renames)} moved file(s) read at their baseline paths")

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
            # Both trees are still on disk here, and only here: the baseline
            # worktree goes away as soon as this block leaves.
            attach_fragment_hashes(current_clones, repo)
            attach_fragment_hashes(baseline_clones, baseline_worktree)
        except SystemExit:
            scan_failed = True
            current_clones = []
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(baseline_worktree)], capture_output=True, cwd=repo
            )

    if scan_failed:
        return 2

    mark_new_clones(current_clones, baseline_clones, renames)
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
