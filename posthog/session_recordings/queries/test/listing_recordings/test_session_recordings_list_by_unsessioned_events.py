from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.sub_queries.events_subquery import UNSESSIONED_EVENTS_FLAG
from posthog.session_recordings.queries.test.listing_recordings.test_utils import assert_query_matches_session_ids
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL
from posthog.test.persons import create_person

FROZEN_NOW = "2021-08-21T20:00:00Z"
RECORDING_START = datetime(2021, 8, 21, 10, 0, tzinfo=UTC)
RECORDING_END = RECORDING_START + timedelta(minutes=30)


@time_machine.travel(FROZEN_NOW, tick=False)
class TestSessionRecordingsListByUnsessionedEvents(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @parameterized.expand(
        [
            ("same_distinct_id_inside_window", True, "user-1", RECORDING_START + timedelta(minutes=10), None, True),
            ("merged_distinct_id_inside_window", True, "anon-1", RECORDING_START + timedelta(minutes=10), None, True),
            ("outside_window", True, "user-1", RECORDING_END + timedelta(hours=2), None, False),
            ("other_session_id_on_event", True, "user-1", RECORDING_START + timedelta(minutes=10), "other", False),
            ("flag_off", False, "user-1", RECORDING_START + timedelta(minutes=10), None, False),
        ]
    )
    def test_event_without_session_id_matches_recording_of_same_person_by_time(
        self,
        _name: str,
        flag_enabled: bool,
        recording_distinct_id: str,
        event_time: datetime,
        event_session_id: str | None,
        expected_match: bool,
    ) -> None:
        person = create_person(team=self.team, distinct_ids=["user-1", "anon-1"])
        create_person(team=self.team, distinct_ids=["user-2"])
        produce_replay_summary(
            team_id=self.team.id,
            session_id="recording-of-user-1",
            distinct_id=recording_distinct_id,
            first_timestamp=RECORDING_START,
            last_timestamp=RECORDING_END,
        )
        produce_replay_summary(
            team_id=self.team.id,
            session_id="recording-of-user-2",
            distinct_id="user-2",
            first_timestamp=RECORDING_START,
            last_timestamp=RECORDING_END,
        )
        _create_event(
            team=self.team,
            event="order paid",
            distinct_id="user-1",
            person_id=person.uuid,
            timestamp=event_time,
            properties={"$session_id": event_session_id} if event_session_id else {},
        )
        flush_persons_and_events()

        with patch(
            "posthog.session_recordings.queries.sub_queries.events_subquery.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: flag_enabled and flag == UNSESSIONED_EVENTS_FLAG,
        ):
            assert_query_matches_session_ids(
                team=self.team,
                query={
                    "date_from": "-3d",
                    "events": [{"id": "order paid", "type": "events", "order": 0, "name": "order paid"}],
                },
                expected=["recording-of-user-1"] if expected_match else [],
            )
