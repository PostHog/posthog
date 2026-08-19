#!/usr/bin/env python3

import os
import sys
import json
import argparse
from pathlib import Path

import pytest
from pytest import ExitCode

from pytest_split import plugin as pytest_split_plugin
from pytest_split.algorithms import Algorithms

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class SelectionCollector:
    def __init__(self) -> None:
        self.selected_tests: list[str] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.selected_tests = [item.nodeid for item in session.items]


def supports_optimal_chunks() -> bool:
    return "optimal_chunks" in Algorithms.names() and hasattr(pytest_split_plugin, "PytestSplitFilePlugin")


def dagster_roots() -> list[str]:
    roots = ["posthog/dags"]
    roots.extend(path.relative_to(REPO_ROOT).as_posix() for path in sorted((REPO_ROOT / "products").glob("*/dags")))
    return roots


def build_pytest_arguments(roots: list[str], group: int, concurrency: int, use_optimal_chunks: bool) -> list[str]:
    splitting_arguments = ["--splitting-algorithm=duration_based_chunks"]
    if use_optimal_chunks:
        splitting_arguments = ["--splitting-algorithm=optimal_chunks", "--split-granularity=file"]

    return [
        *roots,
        "--splits",
        str(concurrency),
        "--group",
        str(group),
        *splitting_arguments,
        "--collect-only",
        "--testmon",
        "--testmon-forceselect",
        "-q",
    ]


def selection_status(exit_code: ExitCode, selected_tests: list[str]) -> str:
    if exit_code in {ExitCode.OK, ExitCode.NO_TESTS_COLLECTED}:
        return "selected" if selected_tests else "empty"
    return "error"


def collect_selection(datafile: Path, roots: list[str], group: int, concurrency: int) -> dict[str, object]:
    if not datafile.exists():
        return {
            "concurrency": concurrency,
            "group": group,
            "pytest_exit_code": None,
            "selected_test_count": None,
            "selected_tests": [],
            "status": "unavailable",
        }

    collector = SelectionCollector()
    os.environ["TESTMON_DATAFILE"] = str(datafile)
    exit_code = pytest.main(
        build_pytest_arguments(
            roots=roots,
            group=group,
            concurrency=concurrency,
            use_optimal_chunks=supports_optimal_chunks(),
        ),
        plugins=[collector],
    )
    selected_tests = sorted(collector.selected_tests)
    return {
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
    parser.add_argument("--root", action="append", dest="roots")
    args = parser.parse_args()

    result = collect_selection(
        datafile=args.datafile,
        roots=args.roots or dagster_roots(),
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
