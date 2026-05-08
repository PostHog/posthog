import pytest

from dagster import build_op_context

from posthog.dags.common.ops import get_all_team_ids_op


def _collect_batches(op_config: dict) -> list[list[int]]:
    return [output.value for output in get_all_team_ids_op(build_op_context(op_config=op_config))]


class TestGetAllTeamIdsOp:
    def test_default_yields_all_batches(self):
        batches = _collect_batches({"team_ids": [1, 2, 3, 4, 5], "batch_size": 2})

        assert batches == [[1, 2], [3, 4], [5]]

    def test_max_batches_truncates_to_first_n(self):
        batches = _collect_batches({"team_ids": [1, 2, 3, 4, 5, 6, 7], "batch_size": 2, "max_batches": 2})

        assert batches == [[1, 2], [3, 4]]

    def test_max_batches_exceeding_total_yields_all(self):
        batches = _collect_batches({"team_ids": [1, 2, 3], "batch_size": 1, "max_batches": 100})

        assert batches == [[1], [2], [3]]

    def test_max_batches_zero_means_unlimited(self):
        batches = _collect_batches({"team_ids": [1, 2, 3, 4, 5], "batch_size": 1, "max_batches": 0})

        assert batches == [[1], [2], [3], [4], [5]]

    def test_negative_max_batches_rejected(self):
        with pytest.raises(ValueError, match="max_batches must be >= 0"):
            _collect_batches({"team_ids": [1, 2, 3], "batch_size": 1, "max_batches": -1})
