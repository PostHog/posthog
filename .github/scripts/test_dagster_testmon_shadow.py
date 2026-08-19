import os
import sys
import json
import subprocess
import importlib.util
from pathlib import Path

import pytest
from pytest import ExitCode

SCRIPT_PATH = Path(__file__).with_name("dagster_testmon_shadow.py")
SPEC = importlib.util.spec_from_file_location("dagster_testmon_shadow", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
dagster_testmon_shadow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dagster_testmon_shadow)


@pytest.mark.parametrize(
    "exit_code,selected_tests,expected",
    [
        pytest.param(ExitCode.OK, ["posthog/dags/tests/test_job.py::test_job"], "selected", id="selected"),
        pytest.param(ExitCode.OK, [], "empty", id="empty-success"),
        pytest.param(ExitCode.NO_TESTS_COLLECTED, [], "empty", id="empty-pytest"),
        pytest.param(ExitCode.USAGE_ERROR, [], "error", id="usage-error"),
        pytest.param(ExitCode.INTERRUPTED, [], "error", id="interrupted"),
    ],
)
def test_selection_status(exit_code: ExitCode, selected_tests: list[str], expected: str) -> None:
    assert dagster_testmon_shadow.selection_status(exit_code, selected_tests) == expected


def test_build_pytest_arguments_keeps_testmon_selection_enabled() -> None:
    arguments = dagster_testmon_shadow.build_pytest_arguments(
        roots=["posthog/dags", "products/signals/dags"],
        group=2,
        concurrency=3,
        use_optimal_chunks=True,
    )

    assert arguments == [
        "posthog/dags",
        "products/signals/dags",
        "--splits",
        "3",
        "--group",
        "2",
        "--splitting-algorithm=optimal_chunks",
        "--split-granularity=file",
        "--collect-only",
        "--testmon",
        "--testmon-forceselect",
        "-q",
    ]


def test_missing_testmon_data_is_unavailable(tmp_path: Path) -> None:
    result = dagster_testmon_shadow.collect_selection(
        datafile=tmp_path / ".testmondata",
        roots=["posthog/dags"],
        group=1,
        concurrency=3,
    )

    assert result == {
        "concurrency": 3,
        "group": 1,
        "pytest_exit_code": None,
        "selected_test_count": None,
        "selected_tests": [],
        "status": "unavailable",
    }


@pytest.mark.parametrize(
    "old_value,new_value,expected_status,expected_count",
    [
        pytest.param("return 1", "return 3", "selected", 1, id="covered-block"),
        pytest.param("return 2", "return 3", "empty", 0, id="uncovered-block"),
    ],
)
def test_shadow_selection_uses_executed_code_blocks(
    tmp_path: Path,
    old_value: str,
    new_value: str,
    expected_status: str,
    expected_count: int,
) -> None:
    source_path = tmp_path / "app.py"
    source_path.write_text("def covered():\n    return 1\n\ndef not_covered():\n    return 2\n")
    test_path = tmp_path / "test_app.py"
    test_path.write_text("from app import covered\n\ndef test_covered():\n    assert covered() == 1\n")
    datafile = tmp_path / ".testmondata"
    output = tmp_path / "selection.json"
    env = {**os.environ, "TESTMON_DATAFILE": str(datafile)}
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.pop("DEBUG", None)
    env.pop("TEST", None)

    subprocess.run(
        [sys.executable, "-m", "pytest", "--testmon-noselect", "-q", str(test_path)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    source_path.write_text(source_path.read_text().replace(old_value, new_value))

    subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--group",
            "1",
            "--concurrency",
            "1",
            "--datafile",
            str(datafile),
            "--output",
            str(output),
            "--root",
            str(test_path),
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(output.read_text())
    assert result["status"] == expected_status
    assert result["selected_test_count"] == expected_count
