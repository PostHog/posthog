#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
# ruff: noqa: T201
"""Measure a change against the stamphog size gate and deny list, before you open PRs.

Run it from the repository root:

    uv run stamphog_budget.py                       # whole change vs origin/master
    uv run stamphog_budget.py --base origin/main    # another base
    uv run stamphog_budget.py --plan plan.json      # check a proposed split

plan.json maps a PR name to the files in that PR:

    {"pr-1-backend": ["posthog/api/foo.py", ...], "pr-2-frontend": ["frontend/src/..."]}

The change is `git diff <merge-base>` against the working tree, plus untracked files.
When the repo carries the stamphog engine (`products/stamphog/packages/pr-approval-agent`
or `tools/pr-approval-agent`), the script uses the engine's own gate code, so the numbers
match the hosted review. Otherwise it reads `size_gate` from `.stamphog/policy.yml`
(default 800 lines, 30 files), uses a copy of the engine's exempt rules, and cannot check
deny categories or folder overrides.

The last stdout line is JSON. Exit code 0 means every checked PR fits, 1 means one does not.
"""

import re
import sys
import json
import argparse
import subprocess
from pathlib import Path

ENGINE_DIRS = ("products/stamphog/packages/pr-approval-agent", "tools/pr-approval-agent")
DEFAULT_MAX_LINES = 800
DEFAULT_MAX_FILES = 30

# Fallback copy of the engine's size-exempt rules (gates.py). The engine wins when present.
_EXEMPT_EXT = {
    ".md", ".mdx", ".txt", ".rst", ".snap", ".ambr", ".storyshot", ".svg",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".lock",
}  # fmt: skip
_EXEMPT_PATH_RE = re.compile(
    r"(?:^|/)docs/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|(?:^|/)generated/.*\.(ts|tsx|js|jsx|json|md|snap|pyi|txt)$"
    r"|\.gen\.(ts|tsx|js|jsx)$|\.generated\.(ts|tsx|js|jsx)$",
    re.IGNORECASE,
)
_TEST_RE = re.compile(
    r"(?:^|/)(?:__tests__|tests?|_tests?)/|(?:^|/)test_[^/]+\.py$|[_.](?:test|spec)\.[^/]+$|_test\.py$",
    re.IGNORECASE,
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def changed_files(base: str) -> list[dict]:
    merge_base = git("merge-base", base, "HEAD").strip()
    files: dict[str, dict] = {}
    for line in git("diff", "--numstat", "-M", merge_base).splitlines():
        added, deleted, path = line.split("\t", 2)
        if " => " in path:  # rename: count it under the new path
            path = re.sub(r"\{([^{}]*) => ([^{}]*)\}", r"\2", path)
            path = path.split(" => ")[-1].replace("//", "/")
        binary = added == "-"
        files[path] = {
            "filename": path,
            "additions": 0 if binary else int(added),
            "deletions": 0 if binary else int(deleted),
            "binary": binary,
        }
    for path in git("ls-files", "--others", "--exclude-standard").splitlines():
        try:
            count = len(Path(path).read_text(errors="replace").splitlines())
        except (OSError, UnicodeDecodeError):
            count = 0
        files[path] = {"filename": path, "additions": count, "deletions": 0, "binary": False}
    return sorted(files.values(), key=lambda f: f["filename"])


class Engine:
    """Thin wrapper over the real stamphog gate code, or a fallback when it is absent."""

    def __init__(self) -> None:
        self.mode = "fallback"
        engine_dir = next((Path(d) for d in ENGINE_DIRS if (Path(d) / "gates.py").exists()), None)
        if engine_dir is not None:
            sys.path.insert(0, str(engine_dir.resolve()))
            import gates  # noqa: PLC0415 - only importable once the engine dir is on the path
            import policy  # noqa: PLC0415

            self.gates, self.policy, self.mode = gates, policy, f"engine ({engine_dir})"
            return
        self.max_lines, self.max_files = DEFAULT_MAX_LINES, DEFAULT_MAX_FILES
        policy_file = Path(".stamphog/policy.yml")
        if policy_file.exists():
            import yaml  # noqa: PLC0415

            gate = (yaml.safe_load(policy_file.read_text()) or {}).get("size_gate") or {}
            self.max_lines = int(gate.get("max_lines", self.max_lines))
            self.max_files = int(gate.get("max_files", self.max_files))

    def exempt(self, path: str) -> bool:
        if self.mode != "fallback":
            return self.gates.is_size_exempt(path)
        return Path(path).suffix.lower() in _EXEMPT_EXT or bool(_EXEMPT_PATH_RE.search(path) or _TEST_RE.search(path))

    def check(self, files: list[dict]) -> dict:
        names = [f["filename"] for f in files]
        counted = [f for f in files if not self.exempt(f["filename"])]
        lines = sum(f["additions"] + f["deletions"] for f in counted)
        result: dict = {"substantive_lines": lines, "substantive_files": len(counted), "all_files": len(files)}
        problems: list[str] = []
        if self.mode == "fallback":
            result.update(line_roof=self.max_lines, file_roof=self.max_files, deny_categories=None)
            if lines > self.max_lines:
                problems.append(f"{lines} substantive lines > {self.max_lines}")
            if len(counted) > self.max_files:
                problems.append(f"{len(counted)} substantive files > {self.max_files}")
        else:
            budgets = self.policy.resolve(self.gates.POLICY, names)
            by_name = {f["filename"]: f for f in files}
            for kind, scopes in (("lines", budgets.line_scopes), ("files", budgets.file_scopes)):
                for scope in scopes:
                    scoped = [by_name[n] for n in scope.files if not self.exempt(n)]
                    used = sum(f["additions"] + f["deletions"] for f in scoped) if kind == "lines" else len(scoped)
                    if used > scope.ceiling:
                        problems.append(f"{used} substantive {kind} in {scope.path or 'global pool'} > {scope.ceiling}")
            if lines > budgets.line_roof:
                problems.append(f"{lines} substantive lines > roof {budgets.line_roof}")
            if len(counted) > budgets.file_roof:
                problems.append(f"{len(counted)} substantive files > roof {budgets.file_roof}")
            deny = self.gates.detect_deny_categories(names)
            result.update(line_roof=budgets.line_roof, file_roof=budgets.file_roof, deny_categories=deny)
            if deny:
                problems.append(f"deny categories {deny}: stamphog will refuse, a human must review")
        result["fits"] = not problems
        result["problems"] = problems
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/master", help="Base ref (default origin/master)")
    parser.add_argument("--plan", help="JSON file: {pr_name: [file, ...]} to check a proposed split")
    parser.add_argument("--verbose", action="store_true", help="Print per-file line counts")
    args = parser.parse_args()

    files = changed_files(args.base)
    engine = Engine()
    report: dict = {"mode": engine.mode, "base": args.base, "whole_change": engine.check(files)}

    if args.verbose:
        for f in files:
            tag = "exempt" if engine.exempt(f["filename"]) else "counts"
            print(f"{f['additions'] + f['deletions']:>6}  {tag:<6}  {f['filename']}")

    ok = report["whole_change"]["fits"]
    if args.plan:
        plan: dict[str, list[str]] = json.loads(Path(args.plan).read_text())
        by_name = {f["filename"]: f for f in files}
        planned = [n for names in plan.values() for n in names]
        report["unplanned_files"] = sorted(set(by_name) - set(planned))
        report["duplicated_files"] = sorted({n for n in planned if planned.count(n) > 1})
        report["unknown_files"] = sorted(set(planned) - set(by_name))
        report["prs"] = {
            name: engine.check([by_name[n] for n in names if n in by_name]) for name, names in plan.items()
        }
        ok = (
            all(r["fits"] for r in report["prs"].values())
            and not report["unplanned_files"]
            and not report["duplicated_files"]
        )
    report["ok"] = ok
    print(json.dumps(report))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
