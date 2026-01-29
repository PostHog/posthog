"""
Tests for the hybrid query approach for person properties in session recordings.

The hybrid query solves the "late identification" problem where:
- User browses anonymously (Day 1) - no email in person properties at event time
- User signs up (Day 3) - identified with email
- Filtering by email should show ALL sessions (Days 1-3), not just Day 3+
"""

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, also_test_with_materialized_columns
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.log_entries import TRUNCATE_LOG_ENTRIES_TABLE_SQL
from posthog.models import Person
from posthog.session_recordings.queries.test.listing_recordings.test_utils import assert_query_matches_session_ids
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


@freeze_time("2021-01-01T13:46:23")
class TestPersonPropertyHybridQuery(ClickhouseTestMixin, APIBaseTest):
    """
    Tests for the hybrid query feature flag that changes how person properties are queried
    in session recordings when using Person on Events (PoE) mode.
    """

    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())
        sync_execute(TRUNCATE_LOG_ENTRIES_TABLE_SQL)

    def _two_sessions_two_persons(
        self, label: str, session_one_person_properties: dict, session_two_person_properties: dict
    ) -> tuple[str, str]:
        """
        Helper to create two persons with sessions - exactly matching the pattern
        from test_session_recording_list_from_query.py
        """
        sessions = []

        for i in range(2):
            user = f"{label}-user-{i}"
            session = f"{label}-session-{i}"
            sessions.append(session)

            Person.objects.create(
                team=self.team,
                distinct_ids=[user],
                properties=session_one_person_properties if i == 0 else session_two_person_properties,
            )

            produce_replay_summary(
                distinct_id=user,
                session_id=session,
                first_timestamp="2021-01-01 00:00:00",
                team_id=self.team.id,
            )
            produce_replay_summary(
                distinct_id=user,
                session_id=session,
                first_timestamp="2021-01-01 00:00:30",
                team_id=self.team.id,
            )

        return sessions[0], sessions[1]

    @also_test_with_materialized_columns(person_properties=["email"])
    def test_hybrid_query_disabled_by_default(self):
        """
        When hybrid query flag is OFF (default), should use standard PoE approach.
        This test verifies the flag correctly controls the query mode.
        """
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_hybrid_disabled",
            session_one_person_properties={"email": "user1@example.com"},
            session_two_person_properties={"email": "user2@example.com"},
        )

        # Query by email with flag OFF (standard PoE)
        with patch("posthoganalytics.feature_enabled", return_value=False):
            assert_query_matches_session_ids(
                team=self.team,
                query={
                    "properties": [
                        {
                            "key": "email",
                            "value": ["user1@example.com"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ]
                },
                expected=[session_id_one],
            )

    @also_test_with_materialized_columns(person_properties=["email"])
    def test_hybrid_query_enabled_finds_sessions(self):
        """
        When hybrid query flag is ON, should use two-stage person-id based query.
        This verifies the hybrid query path is activated by the flag.
        """
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_hybrid_enabled",
            session_one_person_properties={"email": "hybrid1@example.com"},
            session_two_person_properties={"email": "hybrid2@example.com"},
        )

        # Query by email with flag ON (hybrid query)
        with patch("posthoganalytics.feature_enabled", return_value=True):
            assert_query_matches_session_ids(
                team=self.team,
                query={
                    "properties": [
                        {
                            "key": "email",
                            "value": ["hybrid1@example.com"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ]
                },
                expected=[session_id_one],
            )

    @also_test_with_materialized_columns(person_properties=["email"])
    def test_hybrid_query_isolates_users(self):
        """
        Hybrid query should correctly filter to only the matching person's sessions,
        not leak sessions from other users.
        """
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_hybrid_isolate",
            session_one_person_properties={"email": "user1@gmail.com"},
            session_two_person_properties={"email": "user2@hotmail.com"},
        )

        # Query for gmail user with hybrid query ON
        with patch("posthoganalytics.feature_enabled", return_value=True):
            assert_query_matches_session_ids(
                team=self.team,
                query={
                    "properties": [
                        {
                            "key": "email",
                            "value": ["user1@gmail.com"],
                            "operator": "exact",
                            "type": "person",
                        }
                    ]
                },
                expected=[session_id_one],
            )

    @also_test_with_materialized_columns(person_properties=["email"])
    def test_hybrid_query_with_icontains(self):
        """
        Hybrid query should work with icontains operator.
        """
        session_id_one, session_id_two = self._two_sessions_two_persons(
            "test_hybrid_icontains",
            session_one_person_properties={"email": "test@gmail.com"},
            session_two_person_properties={"email": "test@hotmail.com"},
        )

        # Query for gmail with hybrid query ON
        with patch("posthoganalytics.feature_enabled", return_value=True):
            assert_query_matches_session_ids(
                team=self.team,
                query={
                    "properties": [
                        {
                            "key": "email",
                            "value": "gmail",
                            "operator": "icontains",
                            "type": "person",
                        }
                    ]
                },
                expected=[session_id_one],
            )
