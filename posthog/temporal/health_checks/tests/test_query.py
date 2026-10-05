import pytest
from unittest.mock import patch

from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded
from posthog.temporal.health_checks.query import CH_RETRY_MAX_ATTEMPTS, execute_clickhouse_health_team_query

SQL = "SELECT team_id FROM events WHERE team_id IN %(team_ids)s"


def test_retries_transient_clickhouse_errors_then_returns_rows():
    rows = [(1,)]
    with (
        patch("posthog.temporal.health_checks.query.time.sleep") as sleep,
        patch(
            "posthog.temporal.health_checks.query.sync_execute",
            side_effect=[ClickHouseClusterMemoryLimitExceeded(), rows],
        ) as sync_execute,
    ):
        assert execute_clickhouse_health_team_query(SQL, team_ids=[1, 2]) == rows

    assert sync_execute.call_count == 2
    assert sleep.call_count == 1


def test_raises_once_the_retries_are_spent():
    with (
        patch("posthog.temporal.health_checks.query.time.sleep"),
        patch(
            "posthog.temporal.health_checks.query.sync_execute",
            side_effect=ClickHouseClusterMemoryLimitExceeded(),
        ) as sync_execute,
        pytest.raises(ClickHouseClusterMemoryLimitExceeded),
    ):
        execute_clickhouse_health_team_query(SQL, team_ids=[1, 2])

    assert sync_execute.call_count == CH_RETRY_MAX_ATTEMPTS


def test_does_not_retry_other_errors():
    with (
        patch("posthog.temporal.health_checks.query.sync_execute", side_effect=ValueError("bad query")) as sync_execute,
        pytest.raises(ValueError),
    ):
        execute_clickhouse_health_team_query(SQL, team_ids=[1, 2])

    assert sync_execute.call_count == 1
