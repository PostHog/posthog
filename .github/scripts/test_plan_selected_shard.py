import os
import sys
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("plan_selected_shard.py")

TEST_COUNTS = {"test_a.py": 4, "test_b.py": 3, "test_c.py": 2, "test_new.py": 2}
SELECTED = ["test_a.py", "test_b.py", "test_c.py", "test_new.py"]
TIMED = {
    f"{path}::test_{index}": 1.0
    for path, count in TEST_COUNTS.items()
    if path != "test_new.py"
    for index in range(count)
}


def collect_group(root: Path, splits: int, group: int) -> list[str]:
    plan = root / f"plan-{group}.json"
    files = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--durations",
            ".test_durations",
            "--splits",
            str(splits),
            "--group",
            str(group),
            "--plan-out",
            str(plan),
            *SELECTED,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if not files:
        return []
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "/dev/null",
            f"--rootdir={root}",
            "-p",
            "pytest_split.plugin",
            "--collect-only",
            "-q",
            *files,
            "--splits",
            str(splits),
            "--group",
            str(group),
            "--split-granularity=file",
            "--split-plan-path",
            str(plan),
        ],
        cwd=root,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode in (0, 5), result.stdout + result.stderr
    return [line for line in result.stdout.splitlines() if "::" in line]


@pytest.mark.parametrize(
    "durations,splits",
    [
        (TIMED, 3),
        ({}, 3),
        (TIMED, 6),
    ],
)
def test_every_selected_test_runs_on_exactly_one_shard(
    tmp_path: Path, durations: dict[str, float], splits: int
) -> None:
    for path, count in {**TEST_COUNTS, "test_unselected.py": 1}.items():
        (tmp_path / path).write_text("".join(f"def test_{index}():\n    pass\n" for index in range(count)))
    (tmp_path / ".test_durations").write_text(json.dumps(durations))

    collected = [nodeid for group in range(1, splits + 1) for nodeid in collect_group(tmp_path, splits, group)]

    expected = [f"{path}::test_{index}" for path in SELECTED for index in range(TEST_COUNTS[path])]
    assert sorted(collected) == sorted(expected)
