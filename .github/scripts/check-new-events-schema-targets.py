#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Fail when a production module gains a call that branches on the events schema and a test that
imports the module runs against the legacy events table only.

Backend CI runs the paths in .github/new-events-schema-targets.txt a second time against the
native JSON events table. A test outside those paths runs on the legacy table only, so a schema
branch that it reaches can break on the JSON table and nothing fails. The check sees tests that
import the module directly. A test that reaches the module through another module goes unchecked.

The workflow skips this check on a pull request with the test-new-events-schema label, because
that label runs every backend test on both tables.

    check-new-events-schema-targets.py --against origin/master [--committed]
"""

from __future__ import annotations

import re
import ast
import sys
import argparse
import subprocess
from collections import Counter
from pathlib import Path

TARGETS_FILE = ".github/new-events-schema-targets.txt"
LABEL = "test-new-events-schema"

# A call to one of these, or one passed as a callable such as database_sync_to_async(use_new_events_schema),
# branches on the events schema. uses_new_events_schema is the HogQLContext method.
BRANCH_FUNCTIONS = frozenset(
    {
        "use_new_events_schema",
        "uses_new_events_schema",
        "flag_calls_only_in_flag_evaluations",
        "reads_flag_calls_from_flag_evaluations",
    }
)
SETTING = "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA"

TEST_MODULE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
TEST_DIRS = frozenset({"test", "tests", "fixtures"})

# Modules whose schema branch defines a switch, picks a route, or exposes config. No test of them reads a different
# result from the JSON table. One exact path each, with the reason.
ROUTING_ONLY: dict[str, str] = {
    "posthog/models/event/new_events_schema.py": "defines the switch that the other callers branch on",
    "posthog/models/event/util.py": "writes test events to the table that the setting picks",
    "products/feature_flags/backend/facade/flags.py": "defines the flag-call helpers that the other callers branch on",
    "posthog/api/project.py": "exposes flag_calls_only_in_flag_evaluations as a field of the project API",
    "posthog/api/team/team_serializer.py": "exposes flag_calls_only_in_flag_evaluations as a field of the team API",
    "posthog/clickhouse/client/connection.py": "picks the ClickHouse workload for a team's queries",
}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def load_targets(text: str) -> list[str]:
    """The listed paths, parsed the same way as loadJsonTargets in turbo-discover.js."""
    paths = (re.sub(r"#.*", "", line).strip().rstrip("/") for line in text.splitlines())
    return [path for path in paths if path]


def is_listed(path: str, targets: list[str]) -> bool:
    return any(path == target or path.startswith(f"{target}/") for target in targets)


def is_production(path: str) -> bool:
    if not path.endswith(".py") or path.startswith("posthog/settings/"):
        return False
    *dirs, name = path.split("/")
    if TEST_MODULE.search(name) or name in ("conftest.py", "fixtures.py"):
        return False
    return not TEST_DIRS.intersection(dirs)


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def schema_branches(source: str) -> Counter[str]:
    """How many times the source branches on the events schema, by function or setting name."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return Counter()
    found: Counter[str] = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found.update(name for name in map(_name, [node.func, *node.args]) if name in BRANCH_FUNCTIONS)
            # get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA") and getattr(settings, ...)
            found.update(SETTING for arg in node.args if isinstance(arg, ast.Constant) and arg.value == SETTING)
        elif isinstance(node, ast.Attribute) and node.attr == SETTING:
            found[SETTING] += 1
    return found


def module_name(path: str) -> str:
    dotted = path.removesuffix(".py").replace("/", ".")
    return dotted.removesuffix(".__init__")


def imported_modules(source: str, path: str) -> set[str]:
    """Every module that the file names in an import statement, with relative imports resolved."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    package = path.split("/")[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent = package[: len(package) - node.level + 1]
                base = ".".join([*parent, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def importing_tests(path: str, committed: bool) -> list[str]:
    """Test modules in the repository that import the module at `path`."""
    module = module_name(path)
    parent = module.rpartition(".")[0]
    # Every import of the module names it in full, names its parent package, or is relative.
    patterns = ["-e", module, "-e", "from .", *(["-e", f"from {parent} import"] if parent else [])]
    untracked = [] if committed else ["--untracked"]
    grep = subprocess.run(["git", "grep", "-lzF", *untracked, *patterns, "--", "*.py"], capture_output=True, text=True)
    # git grep exits 1 when nothing matches.
    if grep.returncode > 1:
        raise subprocess.CalledProcessError(grep.returncode, grep.args, grep.stdout, grep.stderr)
    return sorted(
        candidate
        for candidate in grep.stdout.split("\0")
        if TEST_MODULE.search(candidate)
        and module in imported_modules(Path(candidate).read_text(errors="replace"), candidate)
    )


def _changed(merge_base: str, committed: bool) -> list[tuple[str | None, str | None]]:
    """(base path, path) for each Python file the branch changes. An added file has no base path, and a deleted file
    has no path."""
    head = ["HEAD"] if committed else []
    fields = _git("diff", "-z", "--name-status", "-M", merge_base, *head, "--", "*.py").split("\0")
    changed: list[tuple[str | None, str | None]] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status.startswith("R"):
            changed.append((fields[index + 1], fields[index + 2]))
            index += 3
            continue
        path = fields[index + 1]
        changed.append((None if status == "A" else path, None if status == "D" else path))
        index += 2
    if not committed:
        untracked = _git("ls-files", "-z", "--others", "--exclude-standard", "--", "*.py").split("\0")
        changed.extend((None, path) for path in untracked if path)
    return changed


def _show(ref: str, path: str) -> str:
    try:
        return _git("show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return ""


def _base_branches(merge_base: str, base_path: str) -> Counter[str]:
    """The branches of a production file at the merge base. A branch that moves out of a test or settings file is
    new to production code."""
    return schema_branches(_show(merge_base, base_path)) if is_production(base_path) else Counter()


def gained_branches(merge_base: str, committed: bool) -> list[str]:
    """Production modules that branch on the events schema more often, by name, than at the merge base."""
    changed = _changed(merge_base, committed)
    # Git reports a move with large edits as a deletion and an addition. An added file is compared against the
    # branches of every deleted file, so a moved branch does not count as new.
    deleted: Counter[str] = Counter()
    for base_path, path in changed:
        if path is None and base_path is not None:
            deleted += _base_branches(merge_base, base_path)
    gained = []
    for base_path, path in changed:
        if path is None or not is_production(path):
            continue
        after = schema_branches(_show("HEAD", path) if committed else Path(path).read_text(errors="replace"))
        before = _base_branches(merge_base, base_path) if base_path else deleted
        if after - before:
            gained.append(path)
    return sorted(gained)


def unlisted_tests(modules: list[str], targets: list[str], committed: bool) -> dict[str, list[str]]:
    unlisted = {}
    for path in modules:
        if path in ROUTING_ONLY:
            continue
        tests = [test for test in importing_tests(path, committed) if not is_listed(test, targets)]
        if tests:
            unlisted[path] = tests
    return unlisted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--against", default="origin/master", help="diff base ref")
    parser.add_argument("--committed", action="store_true", help="check commits only, not the working tree")
    args = parser.parse_args()

    try:
        merge_base = _git("merge-base", args.against, "HEAD").strip()
    except subprocess.CalledProcessError:
        print(f"No merge base with {args.against}, so the events schema check did not run.", file=sys.stderr)
        return 2

    targets = load_targets(Path(TARGETS_FILE).read_text())
    unlisted = unlisted_tests(gained_branches(merge_base, args.committed), targets, args.committed)
    if not unlisted:
        return 0

    print("These modules gain a call that branches on the events schema, and tests that import them")
    print("run against the legacy events table only:")
    for path, tests in unlisted.items():
        print(f"  {path}")
        for test in tests:
            print(f"    {test}")
    print(
        f"\nAdd each test file above that reaches the new branch to {TARGETS_FILE}, so Backend CI also\n"
        f"runs it against the native JSON events table. When the list is long, add the {LABEL} label\n"
        "instead and push a commit: the label runs every backend test on both tables. A module whose\n"
        "branch only picks a route or exposes config goes in ROUTING_ONLY in\n.github/scripts/check-new-events-schema-targets.py."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
