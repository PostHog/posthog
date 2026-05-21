import pytest

from dagster import build_op_context
from parameterized import parameterized

from posthog.dags.common.ops import get_all_team_ids_op


def _collect_batches(op_config: dict) -> list[list[int]]:
    return [output.value for output in get_all_team_ids_op(build_op_context(op_config=op_config))]


class TestGetAllTeamIdsOp:
    @parameterized.expand(
        [
            (
                "default_yields_all_batches",
                {"team_ids": [1, 2, 3, 4, 5], "batch_size": 2},
                [[1, 2], [3, 4], [5]],
            ),
            (
                "max_batches_truncates_to_first_n",
                {"team_ids": [1, 2, 3, 4, 5, 6, 7], "batch_size": 2, "max_batches": 2},
                [[1, 2], [3, 4]],
            ),
            (
                "max_batches_exceeding_total_yields_all",
                {"team_ids": [1, 2, 3], "batch_size": 1, "max_batches": 100},
                [[1], [2], [3]],
            ),
            (
                "max_batches_zero_means_unlimited",
                {"team_ids": [1, 2, 3, 4, 5], "batch_size": 1, "max_batches": 0},
                [[1], [2], [3], [4], [5]],
            ),
        ]
    )
    def test_batches(self, _name: str, op_config: dict, expected: list[list[int]]):
        assert _collect_batches(op_config) == expected

    def test_negative_max_batches_rejected(self):
        with pytest.raises(ValueError, match="max_batches must be >= 0"):
            _collect_batches({"team_ids": [1, 2, 3], "batch_size": 1, "max_batches": -1})
