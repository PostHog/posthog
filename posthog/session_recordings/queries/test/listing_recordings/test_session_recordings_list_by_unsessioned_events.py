from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import PersonsOnEventsMode, RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.models.group.util import create_group
from posthog.session_recordings.queries.sub_queries.events_subquery import (
    UNSESSIONED_EVENTS_FLAG,
    ReplayFiltersEventsSubQuery,
)
from posthog.session_recordings.queries.test.listing_recordings.test_utils import assert_query_matches_session_ids
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person
from posthog.test.test_utils import create_group_type_mapping_without_created_at

FROZEN_NOW = "2021-08-21T20:00:00Z"
RECORDING_START = datetime(2021, 8, 21, 10, 0, tzinfo=UTC)
RECORDING_END = RECORDING_START + timedelta(minutes=30)
INSIDE_WINDOW = RECORDING_START + timedelta(minutes=10)
ORDER_PAID = {"id": "order paid", "type": "events", "order": 0, "name": "order paid"}
PAGEVIEW = {"id": "$pageview", "type": "events", "order": 1, "name": "$pageview"}
ORDER_PAID_EXCLUDING_TEST_PLANS = {
    **ORDER_PAID,
    "properties": [{"key": "plan", "value": ["test"], "operator": "is_not", "type": "event"}],
}
ORDER_PAID_BY_HOGQL_DISTINCT_ID = {
    **ORDER_PAID,
    "properties": [{"key": "distinct_id = 'user-1' AND person_id IS NOT NULL", "type": "hogql"}],
}
FINANCE_ORGANIZATIONS = {
    "key": "industry",
    "value": ["finance"],
    "operator": "exact",
    "type": "group",
    "group_type_index": 0,
}
REFUND_EXCLUDED = {"id": "order refunded", "type": "events", "order": 1, "name": "order refunded", "negation": True}


@time_machine.travel(FROZEN_NOW, tick=False)
class TestSessionRecordingsListByUnsessionedEvents(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    def _produce_recording(self, session_id: str, distinct_id: str) -> None:
        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=RECORDING_START,
            last_timestamp=RECORDING_END,
        )

    def _create_order_paid(
        self,
        distinct_id: str,
        person_id: UUID,
        timestamp: datetime,
        session_id: str | None = None,
        properties: dict | None = None,
    ) -> str:
        return _create_event(
            team=self.team,
            event="order paid",
            distinct_id=distinct_id,
            person_id=person_id,
            timestamp=timestamp,
            properties={**({"$session_id": session_id} if session_id else {}), **(properties or {})},
        )

    @contextmanager
    def _flag(self, enabled: bool) -> Iterator[None]:
        with patch(
            "posthog.session_recordings.queries.sub_queries.events_subquery.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: enabled and flag == UNSESSIONED_EVENTS_FLAG,
        ):
            yield

    def _assert_matches(
        self,
        events: list[dict],
        expected: list[str],
        flag_enabled: bool = True,
        properties: list | None = None,
        query_overrides: dict | None = None,
    ) -> None:
        with self._flag(flag_enabled):
            assert_query_matches_session_ids(
                team=self.team,
                query={"date_from": "-3d", "events": events, "properties": properties or [], **(query_overrides or {})},
                expected=expected,
            )

    @parameterized.expand(
        [
            ("same_distinct_id_inside_window", True, "user-1", INSIDE_WINDOW, None, [ORDER_PAID], True),
            ("merged_distinct_id_inside_window", True, "anon-1", INSIDE_WINDOW, None, [ORDER_PAID], True),
            ("outside_window", True, "user-1", RECORDING_END + timedelta(hours=2), None, [ORDER_PAID], False),
            (
                "inside_margin_in_the_hour_before_the_recording",
                True,
                "user-1",
                RECORDING_START - timedelta(seconds=30),
                None,
                [ORDER_PAID],
                True,
            ),
            ("other_session_id_on_event", True, "user-1", INSIDE_WINDOW, "other", [ORDER_PAID], False),
            ("flag_off", False, "user-1", INSIDE_WINDOW, None, [ORDER_PAID], False),
            ("exclusion_turns_match_off", True, "user-1", INSIDE_WINDOW, None, [ORDER_PAID, REFUND_EXCLUDED], False),
            (
                "negative_property_turns_match_off",
                True,
                "user-1",
                INSIDE_WINDOW,
                None,
                [ORDER_PAID_EXCLUDING_TEST_PLANS],
                False,
            ),
            (
                "hogql_filter_naming_joined_fields",
                True,
                "user-1",
                INSIDE_WINDOW,
                None,
                [ORDER_PAID_BY_HOGQL_DISTINCT_ID],
                True,
            ),
            ("and_with_a_sessioned_filter", True, "user-1", INSIDE_WINDOW, None, [ORDER_PAID, PAGEVIEW], True),
        ]
    )
    def test_event_without_session_id_matches_recording_of_same_person_by_time(
        self,
        _name: str,
        flag_enabled: bool,
        recording_distinct_id: str,
        event_time: datetime,
        event_session_id: str | None,
        events: list[dict],
        expected_match: bool,
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["user-1", "anon-1"])
        create_person(team=self.team, distinct_ids=["user-2"])
        self._produce_recording("recording-of-user-1", recording_distinct_id)
        self._produce_recording("recording-of-user-2", "user-2")
        self._create_order_paid("user-1", person.uuid, event_time, event_session_id)
        for distinct_id, session_id in [("user-1", "recording-of-user-1"), ("user-2", "recording-of-user-2")]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp=RECORDING_START + timedelta(minutes=1),
                properties={"$session_id": session_id},
            )
        flush_persons_and_events()

        self._assert_matches(events, ["recording-of-user-1"] if expected_match else [], flag_enabled)

    @parameterized.expand([(mode,) for mode in PersonsOnEventsMode])
    def test_event_sent_before_a_merge_matches_in_every_persons_on_events_mode(self, mode: PersonsOnEventsMode) -> None:
        self.team.modifiers = {"personsOnEventsMode": mode}
        self.team.save()
        # Sent before the merge, so the event keeps a person id that no distinct id maps to now.
        self._create_order_paid("anon-1", uuid4(), INSIDE_WINDOW)
        flush_persons_and_events()
        create_person(team=self.team, distinct_ids=["user-1", "anon-1"])
        self._produce_recording("recording-of-user-1", "user-1")
        flush_persons_and_events()

        self._assert_matches([ORDER_PAID], ["recording-of-user-1"])

    @parameterized.expand([("person_without_recordings", False), ("recorded_person_outside_window", True)])
    def test_unmatched_events_do_not_fill_the_row_cap(self, _name: str, busy_person_has_recording: bool) -> None:
        person = create_person(team=self.team, distinct_ids=["user-1"])
        busy = create_person(team=self.team, distinct_ids=["busy"])
        self._produce_recording("recording-of-user-1", "user-1")
        if busy_person_has_recording:
            self._produce_recording("recording-of-busy", "busy")
        self._create_order_paid("user-1", person.uuid, INSIDE_WINDOW)
        for minute in range(50):
            self._create_order_paid("busy", busy.uuid, RECORDING_START - timedelta(hours=5, minutes=minute))
        flush_persons_and_events()

        with patch("posthog.session_recordings.queries.sub_queries.events_subquery.EVENTS_SUBQUERY_ROW_LIMIT", 1):
            self._assert_matches([ORDER_PAID], ["recording-of-user-1"])

    @parameterized.expand(
        [("backend_event_has_the_property", "pro", True), ("no_event_has_the_property", "free", False)]
    )
    def test_top_level_event_property_matches_event_without_session_id(
        self, _name: str, plan: str, expected_match: bool
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["user-1"])
        self._produce_recording("recording-of-user-1", "user-1")
        self._create_order_paid("user-1", person.uuid, INSIDE_WINDOW, properties={"plan": plan})
        flush_persons_and_events()

        self._assert_matches(
            [ORDER_PAID],
            ["recording-of-user-1"] if expected_match else [],
            properties=[{"key": "plan", "value": ["pro"], "operator": "exact", "type": "event"}],
        )

    @parameterized.expand(
        [
            ("inside_margin_before_the_recording", RECORDING_START - timedelta(seconds=30), True),
            ("outside_margin_after_the_recording", RECORDING_END + timedelta(minutes=3), False),
        ]
    )
    def test_explicit_session_ids_without_date_from(
        self, _name: str, event_time: datetime, expected_match: bool
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["user-1"])
        self._produce_recording("recording-of-user-1", "user-1")
        self._create_order_paid("user-1", person.uuid, event_time)
        flush_persons_and_events()

        self._assert_matches(
            [ORDER_PAID],
            ["recording-of-user-1"] if expected_match else [],
            query_overrides={"date_from": None, "session_ids": ["recording-of-user-1"]},
        )

    @parameterized.expand(
        [("same_personless_distinct_id", "personless-1", True), ("other_personless_distinct_id", "personless-2", False)]
    )
    def test_personless_distinct_id_matches_by_time(
        self, _name: str, event_distinct_id: str, expected_match: bool
    ) -> None:
        self._produce_recording("recording-of-personless-1", "personless-1")
        self._create_order_paid(event_distinct_id, uuid4(), INSIDE_WINDOW)
        flush_persons_and_events()

        self._assert_matches([ORDER_PAID], ["recording-of-personless-1"] if expected_match else [])

    @parameterized.expand(
        [
            ("flag_on", True, [], ["sessioned", "backend_finance", "backend_retail"]),
            ("flag_off", False, [], ["sessioned"]),
            ("flag_on_with_group_filter", True, [FINANCE_ORGANIZATIONS], ["sessioned", "backend_finance"]),
        ]
    )
    def test_matching_events_include_events_without_session_id_inside_the_window(
        self, _name: str, flag_enabled: bool, properties: list, expected: list[str]
    ) -> None:
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:1", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:2", properties={"industry": "retail"})
        person = create_person(team=self.team, distinct_ids=["user-1", "anon-1"])
        other = create_person(team=self.team, distinct_ids=["user-2"])
        self._produce_recording("recording-of-user-1", "user-1")
        uuids = {
            "sessioned": self._create_order_paid(
                "user-1",
                person.uuid,
                RECORDING_START + timedelta(minutes=1),
                "recording-of-user-1",
                properties={"$group_0": "org:1"},
            ),
            "backend_finance": self._create_order_paid(
                "anon-1", person.uuid, INSIDE_WINDOW, properties={"$group_0": "org:1"}
            ),
            "backend_retail": self._create_order_paid(
                "anon-1", person.uuid, INSIDE_WINDOW, properties={"$group_0": "org:2"}
            ),
        }
        self._create_order_paid("anon-1", person.uuid, RECORDING_END + timedelta(hours=2))
        self._create_order_paid("user-2", other.uuid, INSIDE_WINDOW)
        flush_persons_and_events()

        query = RecordingsQuery.model_validate(
            {"session_ids": ["recording-of-user-1"], "events": [ORDER_PAID], "properties": properties}
        )
        with self._flag(flag_enabled):
            result = ReplayFiltersEventsSubQuery(team=self.team, query=query).get_event_ids_for_session()

        assert sorted(str(row[0]) for row in result.results) == sorted(str(uuids[name]) for name in expected)
