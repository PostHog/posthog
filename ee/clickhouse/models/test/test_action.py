import dataclasses

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.property import action_to_expr

from posthog.clickhouse.client import sync_execute
from posthog.models.action import Action
from posthog.models.action.util import filter_event, format_action_filter
from posthog.models.test.test_event_model import filter_by_actions_factory

from common.hogvm.python.operation import (
    HOGQL_BYTECODE_IDENTIFIER as _H,
    HOGQL_BYTECODE_VERSION,
    Operation as op,
)


@dataclasses.dataclass
class MockEvent:
    uuid: str
    distinct_id: str


def _get_events_for_action(action: Action) -> list[MockEvent]:
    hogql_context = HogQLContext(team_id=action.team_id)
    formatted_query, params = format_action_filter(
        team_id=action.team_id, action=action, prepend="", hogql_context=hogql_context
    )
    query = f"""
        SELECT
            events.uuid,
            events.distinct_id
        FROM events
        WHERE {formatted_query}
        AND events.team_id = %(team_id)s
        ORDER BY events.timestamp DESC
    """
    events = sync_execute(
        query,
        {"team_id": action.team_id, **params, **hogql_context.values},
        team_id=action.team_id,
    )
    return [MockEvent(str(uuid), distinct_id) for uuid, distinct_id in events]


EVENT_UUID_QUERY = "SELECT uuid FROM events WHERE {} AND team_id = %(team_id)s"


class TestActions(
    ClickhouseTestMixin,
    filter_by_actions_factory(_create_event, _create_person, _get_events_for_action),  # type: ignore
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

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "$autocapture",
                    "url": "https://posthog.com/feedback/123",
                    "url_matching": "exact",
                }
            ],
        )
        query, params = filter_event(action1.steps[0])

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk}, team_id=self.team.pk)

        self.assertEqual(len(result), 1)
        self.assertCountEqual(
            [str(r[0]) for r in result],
            [event_target_uuid],
        )

    def test_filter_event_exact_url_with_query_params(self):
        first_match_uuid = _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123?vip=1"},
        )

        second_match_uuid = _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123?vip=1"},
        )

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"$current_url": "https://posthog.com/feedback/123?vip=0"},
        )

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "$autocapture",
                    "url": "https://posthog.com/feedback/123?vip=1",
                    "url_matching": "exact",
                }
            ],
        )
        query, params = filter_event(action1.steps[0])

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk}, team_id=self.team.pk)

        self.assertEqual(len(result), 2)
        self.assertCountEqual(
            [str(r[0]) for r in result],
            [first_match_uuid, second_match_uuid],
        )

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

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[{"event": "$autocapture", "url": "https://posthog.com/feedback/123"}],
        )
        query, params = filter_event(action1.steps[0])

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk}, team_id=self.team.pk)
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

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "$autocapture",
                    "url": "/123",
                    "url_matching": "regex",
                }
            ],
        )
        query, params = filter_event(action1.steps[0])

        full_query = EVENT_UUID_QUERY.format(" AND ".join(query))
        result = sync_execute(full_query, {**params, "team_id": self.team.pk}, team_id=self.team.pk)
        self.assertEqual(len(result), 2)

    def test_double(self):
        # Tests a regression where the second step properties would override those of the first step, causing issues
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="whatever",
            properties={"filters_count": 2},
        )

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "insight",
                            "type": "event",
                            "value": ["RETENTION"],
                            "operator": "exact",
                        }
                    ],
                },
                {
                    "event": "insight viewed",
                    "properties": [
                        {
                            "key": "filters_count",
                            "type": "event",
                            "value": "1",
                            "operator": "gt",
                        }
                    ],
                },
            ],
        )

        events = _get_events_for_action(action1)
        self.assertEqual(len(events), 1)

    def test_filter_with_hogql(self):
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="first",
            properties={"filters_count": 20},
        )
        _create_event(
            event="insight viewed",
            team=self.team,
            distinct_id="second",
            properties={"filters_count": 1},
        )

        action1 = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[
                {
                    "event": "insight viewed",
                    "properties": [{"key": "toInt(properties.filters_count) > 10", "type": "hogql"}],
                }
            ],
        )

        events = _get_events_for_action(action1)
        self.assertEqual(len(events), 1)

        self.assertEqual(action1.bytecode, create_bytecode(action_to_expr(action1)).bytecode)
        self.assertEqual(
            action1.bytecode,
            [
                _H,
                HOGQL_BYTECODE_VERSION,
                # event = 'insight viewed'
                op.STRING,
                "insight viewed",
                op.STRING,
                "event",
                op.GET_GLOBAL,
                1,
                op.EQ,
                # toInt(properties.filters_count) > 10
                op.INTEGER,
                10,
                op.STRING,
                "filters_count",
                op.STRING,
                "properties",
                op.GET_GLOBAL,
                2,
                op.CALL_GLOBAL,
                "toInt",
                1,
                op.GT,
                # and
                op.AND,
                2,
            ],
        )
