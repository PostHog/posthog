from datetime import datetime, timedelta
from unittest.mock import patch

import pytz
from freezegun.api import freeze_time

from posthog.client import sync_execute
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.queries.breakdown_props import _parse_breakdown_cohorts
from posthog.queries.util import get_earliest_timestamp
from posthog.test.base import _create_event


def test_get_earliest_timestamp(db, team):
    with freeze_time("2021-01-21") as frozen_time:
        _create_event(team=team, event="sign up", distinct_id="1", timestamp="2020-01-04T14:10:00Z")
        _create_event(team=team, event="sign up", distinct_id="1", timestamp="2020-01-06T14:10:00Z")

        assert get_earliest_timestamp(team.id) == datetime(2020, 1, 4, 14, 10, tzinfo=pytz.UTC)

        frozen_time.tick(timedelta(seconds=1))
        _create_event(team=team, event="sign up", distinct_id="1", timestamp="1984-01-06T14:10:00Z")
        _create_event(team=team, event="sign up", distinct_id="1", timestamp="2014-01-01T01:00:00Z")
        _create_event(team=team, event="sign up", distinct_id="1", timestamp="2015-01-01T01:00:00Z")

        assert get_earliest_timestamp(team.id) == datetime(2015, 1, 1, 1, tzinfo=pytz.UTC)


@freeze_time("2021-01-21")
def test_get_earliest_timestamp_with_no_events(db, team):
    assert get_earliest_timestamp(team.id) == datetime(2021, 1, 14, tzinfo=pytz.UTC)


def test_get_earliest_timestamp_has_a_short_lived_cache(db, team):
    with freeze_time("2021-01-21") as frozen_time:
        with patch("posthog.queries.util.insight_sync_execute") as patched_sync_execute:
            patched_sync_execute.return_value = [[datetime(2020, 1, 4, 14, 10, tzinfo=pytz.UTC)]]

            # returns the no events value because insight_sync_execute is patched
            assert get_earliest_timestamp(team.id) == datetime(2020, 1, 4, 14, 10, tzinfo=pytz.UTC)
            frozen_time.tick(timedelta(milliseconds=900))

            assert get_earliest_timestamp(team.id) == datetime(2020, 1, 4, 14, 10, tzinfo=pytz.UTC)
            patched_sync_execute.assert_called_once()

            frozen_time.tick(timedelta(milliseconds=100))
            assert get_earliest_timestamp(team.id) == datetime(2020, 1, 4, 14, 10, tzinfo=pytz.UTC)
            assert patched_sync_execute.call_count == 2


def test_does_not_cache_the_default_case(db, team):
    with freeze_time("2021-01-21") as frozen_time:
        with patch("posthog.queries.util.insight_sync_execute") as patched_sync_execute:
            # returns the no events value because insight_sync_execute is patched
            assert get_earliest_timestamp(team.id) == datetime(2021, 1, 14, 0, 0, tzinfo=pytz.UTC)
            assert patched_sync_execute.call_count == 1

            frozen_time.tick(timedelta(milliseconds=900))

            assert get_earliest_timestamp(team.id) == datetime(2021, 1, 14, 0, 0, 0, 900000, tzinfo=pytz.UTC)
            assert patched_sync_execute.call_count == 2


def test_parse_breakdown_cohort_query(db, team):
    action = Action.objects.create(team=team, name="$pageview")
    ActionStep.objects.create(action=action, event="$pageview")
    cohort1 = Cohort.objects.create(team=team, groups=[{"action_id": action.pk, "days": 3}], name="cohort1")
    queries, params = _parse_breakdown_cohorts([cohort1])
    assert len(queries) == 1
    sync_execute(queries[0], params)
