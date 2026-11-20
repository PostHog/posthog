#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Refuse to mask a quarantined failure that the pull request introduced.

The Trunk quarantine gate turns a failing shard green when every failing test is quarantined.
That also hides a regression in a test that was quarantined earlier for an unrelated flake.
This script re-runs the failing tests on the commit the PR is merged onto.
A failure is masked only when the same test fails there too.

The shard runs the PR's merge commit. Its first parent is the base: the same tree without the PR.
The script checks the base out over the workspace, so the re-run keeps the shard's database,
services, installed packages, and untracked build output.
It must be the last step that reads the workspace.

Every safety condition below fails closed. The exit code is 0 only when each failure is shown to be
pre-existing, and the caller treats any other result as a failed job.

1. The event is a pull request whose checkout is a merge commit. Any other shape has no base.
2. The shard's settings file lists every setting the re-run needs.
3. The shard's JUnit report names at least one failing test, and every failure resolves to a test id.
   A setup or teardown error does not count as a failure that a base run can reproduce.
4. The PR changes no migration, lockfile, pyproject, ClickHouse table definition, or source that the shard
   compiles and installs.
   The reused database and installed packages are then not the base's, so a base failure would prove nothing.
5. The base commit fetches and checks out.
6. Pytest exits 0 or 1. Exit 2, 3, 4, and 5 mean an interrupted run, an internal error, a usage error
   (such as a test id that does not exist on the base), and no tests collected.
7. The base JUnit report holds a plain failure for every id. A test that passes, is skipped, or errors
   on the base, or is missing from it, is not a pre-existing failure.
"""

from __future__ import annotations

import os
import shlex
import argparse
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ENV_SETTINGS = ("PERSON_ON_EVENTS_V2_ENABLED", "CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA")
SETTINGS_KEYS = (*ENV_SETTINGS, "PYTEST_ARGS")
ENVIRONMENT_FILES = ("uv.lock", "pyproject.toml", ".python-version")
# The shard installs these from the PR's tree. Checking out the base does not reinstall them.
# These lists name the inputs of the shard's migrate, ClickHouse table, and package install steps in ci-backend.yml.
# Update them with those steps.
# The shard's ClickHouse test tables come from these definitions and survive `--reuse-db`.
CLICKHOUSE_SCHEMA = ("posthog/clickhouse/", "ee/clickhouse/", "posthog/user_scripts/")
INSTALLED_FROM_TREE = ("common/hogql_parser/", "rust/hogql/parser/", "products/canvas/packages/canvas_builder/")
RETRY_MARKER = '"posthog.runner_name"'
RETRY_FLAGS = ("--force-reruns", "1", "--reruns-delay", "1")
# The flags `Run Core tests` passes to every pytest invocation, minus sharding, coverage and timing.
BASE_PYTEST_FLAGS = (
    "-v",
    "--tb=short",
    "--reuse-db",
    "-o",
    "junit_duration_report=call",
    "-m",
    "not async_migrations",
    "-r",
    "fEsxXR",
)

Runner = Callable[[Sequence[str], "dict[str, str] | None"], "subprocess.CompletedProcess[str]"]


class CannotVerify(Exception):
    """A safety condition does not hold, so the failure must not be masked."""


@dataclass(frozen=True)
class Case:
    classname: str
    name: str
    outcome: str  # "failure", "error", "skipped" or "passed"


def default_runner(cmd: Sequence[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), env=env, capture_output=True, text=True, check=False)


def parse_junit(path: Path) -> list[Case]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CannotVerify(f"cannot read JUnit report {path}: {exc}") from exc
    cases = []
    for case in root.iter("testcase"):
        if case.find("error") is not None:
            outcome = "error"
        elif case.find("failure") is not None:
            outcome = "failure"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        cases.append(Case(case.get("classname", ""), case.get("name", ""), outcome))
    return cases


def resolve_test_id(case: Case, root: Path) -> str:
    """Rebuild `path.py::Class::name` from a JUnit classname, which joins the module path and classes with dots."""
    parts = case.classname.split(".")
    for end in range(len(parts), 0, -1):
        module = Path(*parts[:end]).with_suffix(".py")
        if (root / module).is_file():
            return "::".join([module.as_posix(), *parts[end:], case.name])
    raise CannotVerify(f"cannot map JUnit classname {case.classname!r} to a test file")


def failing_test_ids(cases: Sequence[Case], root: Path) -> list[str]:
    ids = set()
    for case in cases:
        if case.outcome == "error":
            raise CannotVerify(
                f"{case.classname}::{case.name} errored in setup or teardown, which a base run cannot reproduce"
            )
        if case.outcome == "failure":
            ids.add(resolve_test_id(case, root))
    if not ids:
        raise CannotVerify("the shard failed but its JUnit report lists no failing test")
    return sorted(ids)


def outcomes_by_id(cases: Sequence[Case], root: Path) -> dict[str, str]:
    """Collapse duplicate entries for one test to its worst outcome."""
    rank = {"passed": 0, "skipped": 1, "failure": 2, "error": 3}
    result: dict[str, str] = {}
    for case in cases:
        try:
            test_id = resolve_test_id(case, root)
        except CannotVerify:
            continue
        if test_id not in result or rank[case.outcome] > rank[result[test_id]]:
            result[test_id] = case.outcome
    return result


def read_settings(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise CannotVerify(f"cannot read the shard settings {path}: {exc}") from exc
    settings = dict(line.split("=", 1) for line in lines if "=" in line)
    missing = [key for key in SETTINGS_KEYS if key not in settings]
    if missing:
        raise CannotVerify(f"the shard settings lack {', '.join(missing)}")
    return settings


def git(run: Runner, *args: str) -> str:
    result = run(["git", *args], None)
    if result.returncode != 0:
        raise CannotVerify(f"`git {' '.join(args)}` failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def find_base(run: Runner) -> str:
    # `git cat-file` prints the commit object itself. `git rev-list` hides the parents of a shallow commit.
    header = git(run, "cat-file", "-p", "HEAD").split("\n\n", 1)[0]
    parents = [line.split()[1] for line in header.splitlines() if line.startswith("parent ")]
    if len(parents) != 2:
        raise CannotVerify("HEAD is not a merge commit, so it has no base to compare against")
    return parents[0]


def environment_changes(run: Runner, base: str) -> list[str]:
    paths = git(run, "diff", "--name-only", "--no-renames", base, "HEAD").splitlines()
    return [
        path
        for path in paths
        if "migrations/" in path
        or path.startswith((*INSTALLED_FROM_TREE, *CLICKHOUSE_SCHEMA))
        or path.endswith((*ENVIRONMENT_FILES, "sql.py"))
    ]


def ensure_origin(run: Runner) -> None:
    # Depot CI's fast checkout adds no origin remote.
    if run(["git", "remote", "get-url", "origin"], None).returncode == 0:
        return
    server, repository = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY")
    if not (server and repository):
        raise CannotVerify("the checkout has no origin remote and GITHUB_SERVER_URL or GITHUB_REPOSITORY is unset")
    git(run, "remote", "add", "origin", f"{server}/{repository}")


def fetch_base(run: Runner, base: str) -> None:
    # The shard's checkout is shallow, so the base commit and its tree are not local yet.
    ensure_origin(run)
    git(run, "fetch", "--no-tags", "--depth=1", "origin", base)


def checkout_base(run: Runner, base: str) -> None:
    git(run, "checkout", "--force", "--detach", base)
    head = git(run, "rev-parse", "HEAD").strip()
    if head != base:
        raise CannotVerify(f"checked out {head}, not the base {base}")


def pytest_command(ids: Sequence[str], junit_out: Path, settings: dict[str, str], retries: bool) -> list[str]:
    return [
        "pytest",
        *BASE_PYTEST_FLAGS,
        *(RETRY_FLAGS if retries else ()),
        f"--junitxml={junit_out}",
        *shlex.split(settings["PYTEST_ARGS"]),
        *ids,
    ]


def check(
    junit: Path,
    settings_file: Path,
    out_dir: Path,
    root: Path,
    event_name: str,
    run: Runner = default_runner,
) -> list[str]:
    """Return the ids that are not shown to fail on the base. An empty list means every failure is pre-existing."""
    if event_name != "pull_request":
        print(
            f"The event is {event_name or 'unknown'}, not a pull request. No base to compare, so the gate result stands."
        )
        return []

    settings = read_settings(settings_file)
    ids = failing_test_ids(parse_junit(junit), root)
    print(f"{len(ids)} quarantined test(s) failed on the PR:")
    for test_id in ids:
        print(f"  {test_id}")

    base = find_base(run)
    fetch_base(run, base)
    changed = environment_changes(run, base)
    if changed:
        raise CannotVerify(
            "the PR changes files the reused database and packages depend on, so the base cannot be re-run here: "
            + ", ".join(changed[:5])
        )
    checkout_base(run, base)

    out_dir.mkdir(parents=True, exist_ok=True)
    junit_out = out_dir / "junit-base.xml"
    junit_out.unlink(missing_ok=True)
    env = {**os.environ, **{key: settings[key] for key in ENV_SETTINGS}}
    retries = RETRY_MARKER in (root / "posthog" / "conftest.py").read_text(errors="replace")
    result = run(pytest_command(ids, junit_out, settings, retries), env)
    print(result.stdout[-4000:])
    print(result.stderr[-4000:])
    if result.returncode not in (0, 1):
        raise CannotVerify(f"pytest exited {result.returncode} on the base, so it did not run the tests to a verdict")

    base_outcomes = outcomes_by_id(parse_junit(junit_out), root)
    regressions = []
    for test_id in ids:
        outcome = base_outcomes.get(test_id, "missing")
        if outcome == "failure":
            print(f"Also fails on the base, so the quarantine stands: {test_id}")
        else:
            print(f"::error::{test_id} fails on the PR but its result on the base is {outcome}")
            regressions.append(test_id)
    return regressions


def main(argv: Sequence[str] | None = None, run: Runner = default_runner) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        regressions = check(
            args.junit, args.settings, args.out_dir, Path.cwd(), os.environ.get("GITHUB_EVENT_NAME", ""), run
        )
    except CannotVerify as exc:
        print(f"::error::Quarantined failure not masked: {exc}")
        return 1
    if regressions:
        print(
            "::error::A quarantined test that fails on this PR does not fail on the base, "
            "so the quarantine does not apply."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
