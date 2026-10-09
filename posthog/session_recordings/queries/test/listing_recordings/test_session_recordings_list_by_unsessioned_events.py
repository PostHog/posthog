from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import PersonsOnEventsMode

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.sub_queries.events_subquery import UNSESSIONED_EVENTS_FLAG
from posthog.session_recordings.queries.test.listing_recordings.test_utils import assert_query_matches_session_ids
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person

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
        self, distinct_id: str, person_id: UUID, timestamp: datetime, session_id: str | None = None
    ) -> None:
        _create_event(
            team=self.team,
            event="order paid",
            distinct_id=distinct_id,
            person_id=person_id,
            timestamp=timestamp,
            properties={"$session_id": session_id} if session_id else {},
        )

    def _assert_matches(self, events: list[dict], expected: list[str], flag_enabled: bool = True) -> None:
        with patch(
            "posthog.session_recordings.queries.sub_queries.events_subquery.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: flag_enabled and flag == UNSESSIONED_EVENTS_FLAG,
        ):
            assert_query_matches_session_ids(
                team=self.team, query={"date_from": "-3d", "events": events}, expected=expected
            )

    @parameterized.expand(
        [
            ("same_distinct_id_inside_window", True, "user-1", INSIDE_WINDOW, None, [ORDER_PAID], True),
            ("merged_distinct_id_inside_window", True, "anon-1", INSIDE_WINDOW, None, [ORDER_PAID], True),
            ("outside_window", True, "user-1", RECORDING_END + timedelta(hours=2), None, [ORDER_PAID], False),
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

    def test_events_of_people_without_recordings_do_not_fill_the_row_cap(self) -> None:
        person = create_person(team=self.team, distinct_ids=["user-1"])
        busy = create_person(team=self.team, distinct_ids=["no-recording"])
        self._produce_recording("recording-of-user-1", "user-1")
        self._create_order_paid("user-1", person.uuid, INSIDE_WINDOW)
        for minute in range(50):
            self._create_order_paid("no-recording", busy.uuid, RECORDING_START + timedelta(minutes=minute))
        flush_persons_and_events()

        with patch("posthog.session_recordings.queries.sub_queries.events_subquery.EVENTS_SUBQUERY_ROW_LIMIT", 1):
            self._assert_matches([ORDER_PAID], ["recording-of-user-1"])
