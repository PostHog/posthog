import json
from typing import Dict, List, Optional
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import filter_event, format_action_filter
from ee.clickhouse.models.event import create_event
from ee.clickhouse.sql.actions import ACTION_QUERY
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.action import Action
from posthog.models.action_step import ActionStep
from posthog.models.event import Event
from posthog.models.person import Person
from posthog.test.base import BaseTest
from posthog.test.test_event_model import filter_by_actions_factory


def _create_event(**kwargs) -> Event:
    pk = uuid4()
    kwargs.update({"event_uuid": pk})
    create_event(**kwargs)
    return Event(pk=str(pk))


def query_action(action: Action) -> Optional[List]:
    formatted_query, params = format_action_filter(action, "")

    query = ACTION_QUERY.format(action_filter=formatted_query)

    if query:
        return sync_execute(query, {"team_id": action.team_id, **params})

    return None


def _get_events_for_action(action: Action) -> List[Event]:
    events = query_action(action)
    ret = []
    if not events:
        return []
    for event in events:
        ev = Event(pk=str(event[0]))
        ev.distinct_id = event[5]
        ret.append(ev)
    return ret


def _create_person(**kwargs) -> Person:
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


class TestActions(
    ClickhouseTestMixin, filter_by_actions_factory(_create_event, _create_person, _get_events_for_action)  # type: ignore
):
    pass


class TestActionFormat(ClickhouseTestMixin, BaseTest):
    def test_filter_event_exact_url(self):

        event_target = _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123"},
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/1234"},
        )

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(
            event="$autocapture", action=action1, url="https://posthog.com/feedback/123", url_matching=ActionStep.EXACT,
        )
        query, params = filter_event(step1)

        full_query = "SELECT uuid FROM events WHERE {}".format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk})
        self.assertEqual(str(result[0][0]), event_target.pk)

    def test_filter_event_contains_url(self):

        event_target = _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123"},
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/1234"},
        )

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(event="$autocapture", action=action1, url="https://posthog.com/feedback/123",)
        query, params = filter_event(step1)

        full_query = "SELECT uuid FROM events WHERE {}".format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_filter_event_regex_url(self):

        event_target = _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123"},
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://test.com/feedback"},
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/1234"},
        )

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(
            event="$autocapture", action=action1, url="/123", url_matching=ActionStep.REGEX,
        )
        query, params = filter_event(step1)

        full_query = "SELECT uuid FROM events WHERE {}".format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)
