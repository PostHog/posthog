import pytest
from unittest.mock import patch

from posthog.clickhouse.client.connection import Workload
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

SQL = "SELECT team_id FROM events WHERE team_id IN %(team_ids)s"


class TestExecuteClickhouseHealthTeamQuery:
    def test_empty_team_ids_skips_query(self) -> None:
        with patch("posthog.temporal.health_checks.query.sync_execute") as mock_execute:
            assert execute_clickhouse_health_team_query(SQL, team_ids=[]) == []
        mock_execute.assert_not_called()

    def test_chunks_teams_and_runs_offline(self) -> None:
        with patch(
            "posthog.temporal.health_checks.query.sync_execute",
            side_effect=lambda *a, **k: [(t,) for t in a[1]["team_ids"]],
        ) as mock_execute:
            rows = execute_clickhouse_health_team_query(SQL, team_ids=[1, 2, 3, 4, 5], chunk_size=2)

        # One statement per chunk, each on the offline pool with only its slice of teams.
        assert [call.kwargs["workload"] for call in mock_execute.call_args_list] == [Workload.OFFLINE] * 3
        assert [call.args[1]["team_ids"] for call in mock_execute.call_args_list] == [[1, 2], [3, 4], [5]]
        # Rows from every chunk are concatenated in order.
        assert rows == [(1,), (2,), (3,), (4,), (5,)]

    def test_rejects_non_positive_chunk_size(self) -> None:
        with pytest.raises(ValueError):
            execute_clickhouse_health_team_query(SQL, team_ids=[1], chunk_size=0)
