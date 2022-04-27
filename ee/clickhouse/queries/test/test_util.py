from datetime import datetime
from uuid import uuid4

import pytz
from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.queries.breakdown_props import _parse_breakdown_cohorts
from posthog.client import sync_execute
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.cohort import Cohort
from posthog.queries.util import get_earliest_timestamp


def _create_event(**kwargs):
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)


@freeze_time("2021-01-21")
def test_get_earliest_timestamp(db, team):
    _create_event(team=team, event="sign up", distinct_id="1", timestamp="2020-01-04T14:10:00Z")
    _create_event(team=team, event="sign up", distinct_id="1", timestamp="2020-01-06T14:10:00Z")

    assert get_earliest_timestamp(team.id) == datetime(2020, 1, 4, 14, 10, tzinfo=pytz.UTC)

    _create_event(team=team, event="sign up", distinct_id="1", timestamp="1984-01-06T14:10:00Z")
    _create_event(team=team, event="sign up", distinct_id="1", timestamp="2014-01-01T01:00:00Z")
    _create_event(team=team, event="sign up", distinct_id="1", timestamp="2015-01-01T01:00:00Z")

    assert get_earliest_timestamp(team.id) == datetime(2015, 1, 1, 1, tzinfo=pytz.UTC)


@freeze_time("2021-01-21")
def test_get_earliest_timestamp_with_no_events(db, team):
    assert get_earliest_timestamp(team.id) == datetime(2021, 1, 14, tzinfo=pytz.UTC)


def test_parse_breakdown_cohort_query(db, team):
    action = Action.objects.create(team=team, name="$pageview")
    ActionStep.objects.create(action=action, event="$pageview")
    cohort1 = Cohort.objects.create(team=team, groups=[{"action_id": action.pk, "days": 3}], name="cohort1",)
    queries, params = _parse_breakdown_cohorts([cohort1])
    assert len(queries) == 1
    sync_execute(queries[0], params)
