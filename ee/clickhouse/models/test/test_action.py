import dataclasses
from typing import List

from ee.clickhouse.util import ClickhouseTestMixin
from posthog.client import sync_execute
from posthog.models.action import Action
from posthog.models.action.util import filter_event, format_action_filter
from posthog.models.action_step import ActionStep
from posthog.test.base import BaseTest, _create_event, _create_person
from posthog.test.test_event_model import filter_by_actions_factory


@dataclasses.dataclass
class MockEvent:
    uuid: str
    distinct_id: str


def _get_events_for_action(action: Action) -> List[MockEvent]:
    formatted_query, params = format_action_filter(team_id=action.team_id, action=action, prepend="")
    query = f"""
        SELECT
            events.uuid,
            events.distinct_id
        FROM events
        WHERE {formatted_query}
        AND events.team_id = %(team_id)s
        ORDER BY events.timestamp DESC
    """
    events = sync_execute(query, {"team_id": action.team_id, **params})
    return [MockEvent(str(uuid), distinct_id) for uuid, distinct_id in events]


EVENT_UUID_QUERY = "SELECT uuid FROM events WHERE {} AND team_id = %(team_id)s"


class TestActions(
    ClickhouseTestMixin, filter_by_actions_factory(_create_event, _create_person, _get_events_for_action)  # type: ignore
):
    pass


class TestActionFormat(ClickhouseTestMixin, BaseTest):
    def test_filter_event_exact_url(self):
        event_target_uuid = _create_event(
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

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk})
        self.assertEqual(str(result[0][0]), event_target_uuid)

    def test_filter_event_contains_url(self):

        _create_event(
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

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_filter_event_regex_url(self):

        _create_event(
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

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk})
        self.assertEqual(len(result), 2)

    def test_double(self):
        # Tests a regression where the second step properties would override those of the first step, causing issues
        _create_event(
            event="insight viewed", team=self.team, distinct_id="whatever", properties={"filters_count": 2},
        )

        action1 = Action.objects.create(team=self.team, name="action1")
        step1 = ActionStep.objects.create(
            event="insight viewed",
            action=action1,
            properties=[{"key": "insight", "type": "event", "value": ["RETENTION"], "operator": "exact"}],
        )
        step2 = ActionStep.objects.create(
            event="insight viewed",
            action=action1,
            properties=[{"key": "filters_count", "type": "event", "value": "1", "operator": "gt"}],
        )

        events = _get_events_for_action(action1)
        self.assertEqual(len(events), 1)
