from concurrent.futures import Future
from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from dagster import Failure, build_op_context

from products.data_modeling.dags.saved_query_demand import record_saved_query_demand_day

DAY = "2026-09-17"


class FakeOpsCluster:
    def __init__(self, rows):
        self.rows = rows
        self.queries: list[str] = []

    def any_host_by_role(self, fn, node_role, workload=None):
        cluster = self

        class FakeClient:
            def execute(self, query, params=None, settings=None):
                cluster.queries.append(query)
                assert params == {"day": DAY}
                return cluster.rows

        future: Future = Future()
        future.set_result(fn(FakeClient()))
        return future


def _run(rows, record):
    with (
        build_op_context(partition_key=DAY, resources={"cluster": FakeOpsCluster(rows)}) as context,
        patch("products.data_modeling.dags.saved_query_demand.record_saved_query_demand", side_effect=record) as mock,
    ):
        record_saved_query_demand_day(context)
        return mock, context.get_output_metadata("result")


def test_one_facade_call_per_team_with_utc_timestamps():
    rows = [
        (1, "sq-a", datetime(2026, 9, 17, 10, 0)),
        (1, "sq-b", datetime(2026, 9, 17, 11, 0)),
        (2, "sq-c", datetime(2026, 9, 17, 12, 0)),
    ]
    mock, metadata = _run(rows, record=lambda team_id, demand: len(demand))

    assert mock.call_count == 2
    mock.assert_any_call(
        1, {"sq-a": datetime(2026, 9, 17, 10, tzinfo=UTC), "sq-b": datetime(2026, 9, 17, 11, tzinfo=UTC)}
    )
    mock.assert_any_call(2, {"sq-c": datetime(2026, 9, 17, 12, tzinfo=UTC)})
    assert metadata["teams"] == 2
    assert metadata["nodes_stamped"] == 3
    assert metadata["failed_teams"] == 0


def test_a_failing_team_does_not_withhold_the_others_and_fails_the_run():
    rows = [(1, "sq-a", datetime(2026, 9, 17, 10, 0)), (2, "sq-c", datetime(2026, 9, 17, 12, 0))]

    def record(team_id, demand):
        if team_id == 1:
            raise RuntimeError("boom")
        return 1

    with (
        build_op_context(partition_key=DAY, resources={"cluster": FakeOpsCluster(rows)}) as context,
        patch("products.data_modeling.dags.saved_query_demand.record_saved_query_demand", side_effect=record) as mock,
    ):
        with pytest.raises(Failure, match="1 team"):
            record_saved_query_demand_day(context)

        assert mock.call_count == 2
        assert context.get_output_metadata("result")["failed_teams"] == 1
