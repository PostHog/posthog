#!/usr/bin/env python3

import os
import sys
import json
import sqlite3
import argparse
import subprocess
from pathlib import Path

import pytest
from pytest import ExitCode


class SelectionCollector:
    def __init__(self) -> None:
        self.selected_tests: list[str] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.selected_tests = [item.nodeid for item in session.items]


def baseline_tests(datafile: Path) -> list[str]:
    with sqlite3.connect(f"file:{datafile}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT DISTINCT test_name FROM test_execution ORDER BY test_name")
        return [test_name for (test_name,) in rows]


def is_dagster_test_file(path: Path) -> bool:
    parts = path.as_posix().split("/")
    in_posthog_dags = any(parts[index : index + 2] == ["posthog", "dags"] for index in range(len(parts) - 1))
    in_product_dags = any(parts[index] == "products" and parts[index + 2] == "dags" for index in range(len(parts) - 2))
    return (
        path.suffix == ".py"
        and (path.name.startswith("test_") or "tests" in parts)
        and (in_posthog_dags or in_product_dags)
    )


def parse_changed_test_files(files_json: str) -> list[Path]:
    try:
        paths = json.loads(files_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        return []
    return sorted(Path(path) for path in paths if is_dagster_test_file(Path(path)))


def build_pytest_arguments(test_names: list[str], changed_test_files: list[Path]) -> list[str]:
    changed_paths = {path.as_posix() for path in changed_test_files}
    baseline_tests = [test_name for test_name in test_names if test_name.split("::", 1)[0] not in changed_paths]
    return [
        *baseline_tests,
        "--collect-only",
        "--testmon",
        "--testmon-forceselect",
        "--testmon-nocollect",
        "-p",
        "no:cov",
        "-q",
    ]


def selection_status(exit_code: ExitCode, selected_tests: list[str]) -> str:
    if exit_code in {ExitCode.OK, ExitCode.NO_TESTS_COLLECTED}:
        return "selected" if selected_tests else "empty"
    return "error"


def unavailable_selection(group: int, concurrency: int) -> dict[str, object]:
    return {
        "baseline_test_count": None,
        "concurrency": concurrency,
        "group": group,
        "pytest_exit_code": None,
        "selected_test_count": None,
        "selected_tests": [],
        "status": "unavailable",
    }


def collect_selection(
    datafile: Path,
    changed_test_files: list[Path],
    include_changed_test_files: bool,
    group: int,
    concurrency: int,
) -> dict[str, object]:
    if not datafile.exists():
        return unavailable_selection(group, concurrency)

    try:
        test_names = baseline_tests(datafile)
    except sqlite3.Error:
        return unavailable_selection(group, concurrency)
    if not test_names:
        return unavailable_selection(group, concurrency)

    collector = SelectionCollector()
    os.environ["TESTMON_DATAFILE"] = str(datafile)
    exit_code = pytest.main(build_pytest_arguments(test_names, changed_test_files), plugins=[collector])

    existing_changed_tests = [str(path) for path in changed_test_files if include_changed_test_files and path.exists()]
    changed_test_exit_code = ExitCode.OK
    changed_tests: list[str] = []
    if existing_changed_tests:
        changed_test_result = subprocess.run(
            [sys.executable, "-m", "pytest", *existing_changed_tests, "--collect-only", "-p", "no:testmon", "-q"],
            capture_output=True,
            text=True,
            check=False,
        )
        changed_test_exit_code = ExitCode(changed_test_result.returncode)
        changed_tests = [line for line in changed_test_result.stdout.splitlines() if "::" in line]

    selected_tests = sorted(set(collector.selected_tests) | set(changed_tests))
    if changed_test_exit_code not in {ExitCode.OK, ExitCode.NO_TESTS_COLLECTED}:
        exit_code = changed_test_exit_code
    return {
        "baseline_test_count": len(test_names),
        "concurrency": concurrency,
        "group": group,
        "pytest_exit_code": int(exit_code),
        "selected_test_count": len(selected_tests),
        "selected_tests": selected_tests,
        "status": selection_status(exit_code, selected_tests),
    }


def write_step_summary(result: dict[str, object]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    selected_test_count = result["selected_test_count"]
    count = "unknown" if selected_test_count is None else str(selected_test_count)
    with Path(summary_path).open("a") as summary:
        summary.write("## Dagster testmon shadow selection\n\n")
        summary.write(f"- Shard: {result['group']}/{result['concurrency']}\n")
        summary.write(f"- Status: {result['status']}\n")
        summary.write(f"- Selected tests: {count}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=int, required=True)
    parser.add_argument("--concurrency", type=int, required=True)
    parser.add_argument("--datafile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--changed-files-json", default="[]")
    parser.add_argument("--include-changed-test-files", action="store_true")
    args = parser.parse_args()

    result = collect_selection(
        datafile=args.datafile,
        changed_test_files=parse_changed_test_files(args.changed_files_json),
        include_changed_test_files=args.include_changed_test_files,
        group=args.group,
        concurrency=args.concurrency,
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    write_step_summary(result)
    summary = {key: value for key, value in result.items() if key != "selected_tests"}
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
