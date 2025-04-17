from datetime import datetime, timedelta

from zoneinfo import ZoneInfo
from freezegun.api import freeze_time
from unittest.mock import patch, MagicMock

from posthog.clickhouse.client import sync_execute
from posthog.hogql.hogql import HogQLContext
from posthog.models.action import Action
from posthog.models.cohort import Cohort
from posthog.queries.breakdown_props import _parse_breakdown_cohorts
from posthog.queries.util import get_earliest_timestamp
from posthog.test.base import _create_event
from posthog.clickhouse.client import ServerException
from posthog.clickhouse.client import Workload


def test_get_earliest_timestamp(db, team):
    with freeze_time("2021-01-21") as frozen_time:
        _create_event(
            team=team,
            event="sign up",
            distinct_id="1",
            timestamp="2020-01-04T14:10:00Z",
        )
        _create_event(
            team=team,
            event="sign up",
            distinct_id="1",
            timestamp="2020-01-06T14:10:00Z",
        )

        assert get_earliest_timestamp(team.id) == datetime(2020, 1, 4, 14, 10, tzinfo=ZoneInfo("UTC"))

        frozen_time.tick(timedelta(seconds=1))
        _create_event(
            team=team,
            event="sign up",
            distinct_id="1",
            timestamp="1984-01-06T14:10:00Z",
        )
        _create_event(
            team=team,
            event="sign up",
            distinct_id="1",
            timestamp="2014-01-01T01:00:00Z",
        )
        _create_event(
            team=team,
            event="sign up",
            distinct_id="1",
            timestamp="2015-01-01T01:00:00Z",
        )

        assert get_earliest_timestamp(team.id) == datetime(2015, 1, 1, 1, tzinfo=ZoneInfo("UTC"))


@freeze_time("2021-01-21")
def test_get_earliest_timestamp_with_no_events(db, team):
    assert get_earliest_timestamp(team.id) == datetime(2021, 1, 14, tzinfo=ZoneInfo("UTC"))


def test_parse_breakdown_cohort_query(db, team):
    action = Action.objects.create(team=team, name="$pageview", steps_json=[{"event": "$pageview"}])
    cohort1 = Cohort.objects.create(team=team, groups=[{"action_id": action.pk, "days": 3}], name="cohort1")
    queries, params = _parse_breakdown_cohorts([cohort1], HogQLContext(team_id=team.pk))
    assert len(queries) == 1
    sync_execute(queries[0], params)


@patch("posthog.clickhouse.client.execute.get_client_from_pool")
def test_sync_execute_retries_with_online_workload_on_202(mock_get_client):
    # Create mock clients
    mock_client1 = MagicMock()
    mock_client2 = MagicMock()

    # First client raises 202 ServerException
    mock_client1.__enter__.return_value.execute.side_effect = ServerException("Too many simultaneous queries", code=202)

    # Second client succeeds
    mock_client2.__enter__.return_value.execute.return_value = "success"

    # Return different clients on consecutive calls
    mock_get_client.side_effect = [mock_client1, mock_client2]

    # Execute query with personal_api_key access method and offline workload
    query = "SELECT 1"
    tag_queries = {"access_method": "personal_api_key"}

    with patch("posthog.clickhouse.client.execute.get_query_tags", return_value=tag_queries):
        result = sync_execute(query, workload=Workload.OFFLINE)

    # Verify first call was with OFFLINE workload
    mock_get_client.assert_any_call(Workload.OFFLINE, None, False)

    # Verify second call was with ONLINE workload
    mock_get_client.assert_any_call(Workload.ONLINE, None, False)

    # Verify final result
    assert result == "success"
