from collections.abc import Callable, Mapping
from concurrent.futures import Future
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from dagster import Failure, build_op_context

from products.data_modeling.dags.saved_query_demand import record_saved_query_demand_day

DAY = "2026-09-17"

Row = tuple[int, str, datetime]


class FakeOpsCluster:
    def __init__(self, rows: list[Row]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    def any_host_by_role(
        self, fn: Callable[[Any], list[Row]], node_role: Any, workload: Any = None
    ) -> Future[list[Row]]:
        cluster = self

        class FakeClient:
            def execute(
                self, query: str, params: Mapping[str, Any] | None = None, settings: Mapping[str, Any] | None = None
            ) -> list[Row]:
                cluster.queries.append(query)
                assert params == {"day": DAY}
                return cluster.rows

        future: Future[list[Row]] = Future()
        future.set_result(fn(FakeClient()))
        return future


def _run(rows: list[Row], record: Callable[[int, dict[str, datetime]], int]) -> tuple[MagicMock, Mapping[str, Any]]:
    with (
        build_op_context(partition_key=DAY, resources={"cluster": FakeOpsCluster(rows)}) as context,
        patch("products.data_modeling.dags.saved_query_demand.record_saved_query_demand", side_effect=record) as mock,
    ):
        record_saved_query_demand_day(context)
        metadata = context.get_output_metadata("result")
        assert metadata is not None
        return mock, metadata


def test_one_facade_call_per_team_with_utc_timestamps() -> None:
    rows: list[Row] = [
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


def test_a_failing_team_does_not_withhold_the_others_and_fails_the_run() -> None:
    rows: list[Row] = [(1, "sq-a", datetime(2026, 9, 17, 10, 0)), (2, "sq-c", datetime(2026, 9, 17, 12, 0))]

    def record(team_id: int, demand: dict[str, datetime]) -> int:
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
        metadata = context.get_output_metadata("result")
        assert metadata is not None
        assert metadata["failed_teams"] == 1
