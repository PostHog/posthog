import os
import sys
import json
import subprocess
from pathlib import Path

import pytest

from rust_test_shards import PACKAGE_WEIGHTS, plan_shards


@pytest.mark.parametrize(
    "affected,expected",
    [
        ({"capture"}, [["capture"]]),
        (
            {"capture", "feature-flags", "cohort-stream-processor"},
            [["feature-flags"], ["capture", "cohort-stream-processor"]],
        ),
        ({"new-crate", "capture"}, [["capture", "new-crate"]]),
    ],
)
def test_selective_shards(affected: set[str], expected: list[list[str]]) -> None:
    assert plan_shards(affected) == expected


def test_empty_selection_runs_every_known_crate_once() -> None:
    shards = plan_shards(set())
    packages = [name for shard in shards for name in shard]
    assert sorted(packages) == sorted(PACKAGE_WEIGHTS)
    assert all(shard for shard in shards)


def test_new_crates_use_default_weights_without_losing_coverage() -> None:
    affected = {f"new-crate-{index}" for index in range(9)}
    shards = plan_shards(affected)
    assert len(shards) == 2
    assert sorted(name for shard in shards for name in shard) == sorted(affected)


def test_cli_emits_the_build_matrix(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("rust_test_shards.py"))],
        env={**os.environ, "AFFECTED_CRATES": '["capture", "new-crate"]', "GITHUB_OUTPUT": str(output)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert "using 60s default): new-crate" in result.stdout
    assert "Selective build: testing 2 of affected crates" in result.stdout
    assert "Total: 162s across 1 shards (target ≤480s/shard)" in result.stdout
    assert json.loads(output.read_text().removeprefix("matrix=")) == {"include": [{"packages": "capture new-crate"}]}
