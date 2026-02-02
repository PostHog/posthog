from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.test_utils import (
    assert_query_matches_session_ids,
    create_event,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


@freeze_time("2021-01-01T13:46:23")
@override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True)
class TestPersonPropertyHybridQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    def _assert_query_matches_session_ids(
        self, query: dict | None, expected: list[str], sort_results_when_asserting: bool = True
    ) -> None:
        assert_query_matches_session_ids(
            team=self.team, query=query, expected=expected, sort_results_when_asserting=sort_results_when_asserting
        )

    @property
    def an_hour_ago(self):
        return (now() - relativedelta(hours=1)).replace(microsecond=0, second=0)

    def test_hybrid_query_disabled_by_default(self) -> None:
        with freeze_time("2021-08-21T20:00:00.000Z"):
            anonymous_id = "anonymous_user_123"
            identified_id = "identified_user_123"
            session_id_after = "session_after_identification"

            Person.objects.create(
                team=self.team,
                distinct_ids=[anonymous_id, identified_id],
                properties={"email": "user@example.com"},
            )

            produce_replay_summary(
                distinct_id=identified_id,
                session_id=session_id_after,
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            create_event(
                identified_id,
                self.an_hour_ago,
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_after},
            )

            self._assert_query_matches_session_ids(
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "user@example.com",
                            "type": "person",
                            "operator": "exact",
                        }
                    ]
                },
                [session_id_after],
            )

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_hybrid_query_enabled_finds_sessions(self, mock_feature_enabled) -> None:
        with freeze_time("2021-08-21T20:00:00.000Z"):
            anonymous_id = "anonymous_user_456"
            identified_id = "identified_user_456"
            session_id_before = "session_before_identification_456"
            session_id_after = "session_after_identification_456"

            produce_replay_summary(
                distinct_id=anonymous_id,
                session_id=session_id_before,
                first_timestamp=self.an_hour_ago - relativedelta(minutes=10),
                team_id=self.team.id,
            )
            create_event(
                anonymous_id,
                self.an_hour_ago - relativedelta(minutes=10),
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_before},
            )

            Person.objects.create(
                team=self.team,
                distinct_ids=[anonymous_id, identified_id],
                properties={"email": "user@example.com"},
            )

            produce_replay_summary(
                distinct_id=identified_id,
                session_id=session_id_after,
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            create_event(
                identified_id,
                self.an_hour_ago,
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_after},
            )

            self._assert_query_matches_session_ids(
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "user@example.com",
                            "type": "person",
                            "operator": "exact",
                        }
                    ]
                },
                [session_id_before, session_id_after],
            )

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_hybrid_query_finds_all_person_sessions(self, mock_feature_enabled) -> None:
        with freeze_time("2021-08-21T20:00:00.000Z"):
            distinct_id_1 = "distinct_1"
            distinct_id_2 = "distinct_2"
            distinct_id_3 = "distinct_3"
            session_id_1 = "session_1"
            session_id_2 = "session_2"
            session_id_3 = "session_3"

            Person.objects.create(
                team=self.team,
                distinct_ids=[distinct_id_1, distinct_id_2, distinct_id_3],
                properties={"email": "multi@example.com"},
            )

            produce_replay_summary(
                distinct_id=distinct_id_1,
                session_id=session_id_1,
                first_timestamp=self.an_hour_ago,
                team_id=self.team.id,
            )
            create_event(
                distinct_id_1,
                self.an_hour_ago,
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_1},
            )

            produce_replay_summary(
                distinct_id=distinct_id_2,
                session_id=session_id_2,
                first_timestamp=self.an_hour_ago + relativedelta(minutes=10),
                team_id=self.team.id,
            )
            create_event(
                distinct_id_2,
                self.an_hour_ago + relativedelta(minutes=10),
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_2},
            )

            produce_replay_summary(
                distinct_id=distinct_id_3,
                session_id=session_id_3,
                first_timestamp=self.an_hour_ago + relativedelta(minutes=20),
                team_id=self.team.id,
            )
            create_event(
                distinct_id_3,
                self.an_hour_ago + relativedelta(minutes=20),
                team=self.team,
                event_name="$pageview",
                properties={"$session_id": session_id_3},
            )

            self._assert_query_matches_session_ids(
                {
                    "properties": [
                        {
                            "key": "email",
                            "value": "multi@example.com",
                            "type": "person",
                            "operator": "exact",
                        }
                    ]
                },
                [session_id_1, session_id_2, session_id_3],
            )
