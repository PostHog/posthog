from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlencode

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    FuzzyInt,
    QueryMatchingTest,
    _create_event,
    flush_persons_and_events,
    snapshot_postgres_queries,
    snapshot_postgres_queries_context,
)
from unittest.mock import ANY, MagicMock, call, patch

from django.utils.timezone import now

from clickhouse_driver.errors import ServerException
from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from rest_framework import status

from posthog.schema import LogEntryPropertyFilter, RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorCannotScheduleTask, CHQueryErrorTooManySimultaneousQueries
from posthog.models import Organization, Person, SessionRecording, User
from posthog.models.team import Team
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        sync_execute("TRUNCATE TABLE sharded_events")
        sync_execute("TRUNCATE TABLE person")
        sync_execute("TRUNCATE TABLE sharded_session_replay_events")
        SessionRecordingViewed.objects.all().delete()
        SessionRecording.objects.all().delete()
        Person.objects.all().delete()

    def produce_replay_summary(
        self,
        distinct_id,
        session_id,
        timestamp,
        team_id=None,
    ):
        if team_id is None:
            team_id = self.team.pk

        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            ensure_analytics_event_in_session=False,
            retention_period_days=90,
        )

    @parameterized.expand(
        [
            # Test basic listing returns recordings in descending order by start time
            (
                "basic_listing",
                [
                    {"distinct_ids": ["user1"], "session_id": "session1", "times": [0]},
                    {"distinct_ids": ["user2"], "session_id": "session2", "times": [20]},
                ],
                # Expected order: session2 (newer), session1 (older)
                ["session2", "session1"],
            ),
            # Test multiple snapshots create proper duration
            (
                "multiple_snapshots",
                [
                    {
                        "distinct_ids": ["user1"],
                        "session_id": "session_with_duration",
                        "times": [0, 10, 30],  # 30 second duration
                    },
                ],
                ["session_with_duration"],
                30,  # expected duration
            ),
            # Test user with many distinct IDs only returns one distinct ID
            (
                "many_distinct_ids",
                [
                    {
                        "distinct_ids": [f"user_one_{i}" for i in range(12)],
                        "session_id": "session_many_ids",
                        "times": [0],
                        "distinct_id_for_recording": "user_one_0",
                    },
                ],
                ["session_many_ids"],
                None,
                1,  # expected distinct_ids count in response
            ),
        ]
    )
    @snapshot_postgres_queries
    def test_get_session_recordings_scenarios(
        self,
        _name: str,
        user_configs: list[dict],
        expected_session_order: list[str],
        expected_duration: int | None = None,
        expected_distinct_ids_count: int | None = None,
    ) -> None:
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        created_users = []

        # Create users and recordings based on config
        for config in user_configs:
            user = Person.objects.create(
                team=self.team,
                distinct_ids=config["distinct_ids"],
                properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            created_users.append(user)

            # Create recordings for each timestamp
            recording_distinct_id = config.get("distinct_id_for_recording", config["distinct_ids"][0])
            for time_offset in config["times"]:
                self.produce_replay_summary(
                    recording_distinct_id,
                    config["session_id"],
                    base_time + relativedelta(seconds=time_offset),
                )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]

        # Check order
        actual_order = [r["id"] for r in results]
        assert actual_order == expected_session_order

        # Check duration if specified
        if expected_duration is not None:
            assert results[0]["recording_duration"] == expected_duration

        # Check distinct_ids count if specified
        if expected_distinct_ids_count is not None:
            assert len(results[0]["person"]["distinct_ids"]) == expected_distinct_ids_count

    @snapshot_postgres_queries
    def test_get_session_recordings_returns_newest_first(self) -> None:
        """Test that recordings are returned in descending order by start time"""
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

        # Create recordings at different times
        self.produce_replay_summary("user1", "old_session", base_time)
        self.produce_replay_summary("user2", "new_session", base_time + relativedelta(seconds=60))
        self.produce_replay_summary("user3", "middle_session", base_time + relativedelta(seconds=30))

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]

        assert [r["id"] for r in results] == ["new_session", "middle_session", "old_session"]

    def test_get_session_recordings_includes_person_data(self) -> None:
        """Test that person data is properly included in recordings response"""
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["test_user"],
            properties={"$some_prop": "something", "email": "test@example.com"},
        )

        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        self.produce_replay_summary("test_user", "test_session", base_time)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]

        assert result["person"]["id"] == person.pk
        assert result["person"]["distinct_ids"] == ["test_user"]
        assert result["distinct_id"] == "test_user"
        assert result["viewed"] is False

    @parameterized.expand(
        [
            # originally for this table all order by was DESCENDING
            ["descending (original)", "start_time", None, ["at_base_time_plus_20", "at_base_time"]],
            ["descending", "start_time", "DESC", ["at_base_time_plus_20", "at_base_time"]],
            ["ascending", "start_time", "ASC", ["at_base_time", "at_base_time_plus_20"]],
        ]
    )
    @snapshot_postgres_queries
    # we can't take snapshots of the CH queries
    # because we use `now()` in the CH queries which don't know about any frozen time
    # @snapshot_clickhouse_queries
    def test_get_session_recordings_sorted(
        self, _name: str, order_field: str, order_direction: str | None, expected_id_order: list[str]
    ) -> None:
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

        # first session runs from base time to base time + 30
        session_id_one = "at_base_time"
        self.produce_replay_summary("user_one_0", session_id_one, base_time)
        self.produce_replay_summary("user_one_0", session_id_one, base_time + relativedelta(seconds=10))
        self.produce_replay_summary("user_one_0", session_id_one, base_time + relativedelta(seconds=30))

        # second session runs from base time + 20 to base time + 30
        session_id_two = "at_base_time_plus_20"
        self.produce_replay_summary("user2", session_id_two, base_time + relativedelta(seconds=20))
        self.produce_replay_summary("user2", session_id_two, base_time + relativedelta(seconds=30))

        query_string = f"?order={order_field}"
        if order_direction:
            query_string += f"&order_direction={order_direction}"
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings{query_string}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()

        results_ = response_data["results"]

        assert [r["id"] for r in results_] == expected_id_order

    def test_can_list_recordings_even_when_the_person_has_multiple_distinct_ids(self):
        # almost duplicate of test_get_session_recordings above
        # but if we have multiple distinct ids on a recording the snapshot
        # varies which makes the snapshot useless
        twelve_distinct_ids: list[str] = [f"user_one_{i}" for i in range(12)]

        Person.objects.create(
            team=self.team,
            distinct_ids=twelve_distinct_ids,  # that's too many! we should limit them
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["user2"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )

        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        session_id_one = f"test_get_session_recordings-1"
        self.produce_replay_summary("user_one_0", session_id_one, base_time)
        self.produce_replay_summary("user_one_1", session_id_one, base_time + relativedelta(seconds=10))
        self.produce_replay_summary("user_one_2", session_id_one, base_time + relativedelta(seconds=30))
        session_id_two = f"test_get_session_recordings-2"
        self.produce_replay_summary("user2", session_id_two, base_time + relativedelta(seconds=20))

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        results_ = response_data["results"]
        assert results_ is not None
        # detailed assertion is in the other test
        assert len(results_) == 2

        # user distinct id varies because we're adding more than one
        assert results_[0]["distinct_id"] == "user2"
        assert results_[1]["distinct_id"] in twelve_distinct_ids

    @patch("posthoganalytics.capture")
    @patch("posthog.session_recordings.session_recording_api.list_recordings_from_query")
    def test_console_log_filters_are_correctly_passed_to_listing(self, mock_query_lister, mock_capture):
        mock_query_lister.return_value = ([], False)

        params_string = urlencode(
            {
                "console_log_filters": '[{"key": "console_log_level", "value": ["warn", "error"], "operator": "exact", "type": "log_entry"}]',
                "user_modified_filters": '{"my_filter": "something"}',
            }
        )
        self.client.get(f"/api/projects/{self.team.id}/session_recordings?{params_string}")

        assert len(mock_query_lister.call_args_list) == 1
        query_passed_to_mock: RecordingsQuery = mock_query_lister.call_args_list[0][0][0]
        maybe_the_filter = (
            query_passed_to_mock.console_log_filters[0] if query_passed_to_mock.console_log_filters else None
        )
        assert maybe_the_filter is not None
        console_filter = cast(LogEntryPropertyFilter, maybe_the_filter)
        assert console_filter.value == ["warn", "error"]
        assert mock_capture.call_args_list[0] == call(
            event="recording list filters changed",
            distinct_id=self.user.distinct_id,
            properties={
                "$current_url": ANY,
                "$session_id": ANY,
                "partial_filter_chosen_my_filter": "something",
            },
            groups=ANY,
        )

    def test_listing_recordings_is_not_nplus1_for_persons(self):
        # we want to get the various queries that django runs once and then caches out of the way
        # otherwise chance and changes outside of here can cause snapshots to flap
        # so we call the API once and then use query snapshot as a context manager _after_ that
        self.client.get(f"/api/projects/{self.team.id}/session_recordings")

        with freeze_time("2022-06-03T12:00:00.000Z"), snapshot_postgres_queries_context(self):
            # request once without counting queries to cache an ee.license lookup that makes results vary otherwise
            self.client.get(f"/api/projects/{self.team.id}/session_recordings")

            base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
            num_queries = FuzzyInt(7, 26)  # PoE on or off adds queries here :shrug:

            # loop from 1 to 10
            for i in range(1, 11):
                self._person_with_snapshots(
                    base_time=base_time,
                    distinct_id=f"user{i}",
                    session_id=f"{i}",
                )
                with self.assertNumQueries(num_queries):
                    self.client.get(f"/api/projects/{self.team.id}/session_recordings")

    def _person_with_snapshots(self, base_time: datetime, distinct_id: str = "user", session_id: str = "1") -> None:
        Person.objects.create(
            team=self.team,
            distinct_ids=[distinct_id],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        self.produce_replay_summary(distinct_id, session_id, base_time)
        self.produce_replay_summary(distinct_id, session_id, base_time + relativedelta(seconds=10))
        flush_persons_and_events()

    def test_session_recordings_dont_leak_teams(self) -> None:
        another_team = Team.objects.create(organization=self.organization)
        Person.objects.create(
            team=another_team,
            distinct_ids=["user"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        home_team_person = Person.objects.create(
            team=self.team,
            distinct_ids=["user"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )

        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        self.produce_replay_summary("user", "other_team", base_time, team_id=another_team.pk)
        self.produce_replay_summary("user", "current_team", base_time)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        assert response_data["results"] == [
            {
                "active_seconds": 0,
                "click_count": 0,
                "console_error_count": 0,
                "console_log_count": 0,
                "console_warn_count": 0,
                "distinct_id": "user",
                "end_time": ANY,
                "expiry_time": ANY,
                "id": "current_team",
                "inactive_seconds": ANY,
                "keypress_count": 0,
                "mouse_activity_count": 0,
                "person": {
                    "created_at": ANY,
                    "distinct_ids": ["user"],
                    "id": home_team_person.id,
                    "name": "bob@bob.com",
                    "properties": {
                        "$some_prop": "something",
                        "email": "bob@bob.com",
                    },
                    "uuid": ANY,
                },
                "recording_duration": ANY,
                "snapshot_source": "web",
                "start_time": ANY,
                "start_url": "https://not-provided-by-test.com",
                "storage": "object_storage",
                "retention_period_days": 90,
                "recording_ttl": 89,
                "viewed": False,
                "viewers": [],
                "ongoing": True,
                "activity_score": ANY,
            },
        ]

    def test_session_recording_for_user_with_multiple_distinct_ids(self) -> None:
        base_time = (now() - timedelta(days=1)).replace(microsecond=0)
        p = Person.objects.create(
            team=self.team,
            distinct_ids=["d1", "d2"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        self.produce_replay_summary("d1", "1", base_time)
        self.produce_replay_summary("d2", "2", base_time + relativedelta(seconds=30))

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        response_data = response.json()

        assert [r["person"]["id"] for r in response_data["results"]] == [p.pk, p.pk]

    def test_viewed_state_of_session_recording_version(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["u1"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        base_time = (now() - timedelta(days=1)).replace(microsecond=0)
        SessionRecordingViewed.objects.create(
            team=self.team, user=self.user, session_id="test_viewed_state_of_session_recording_version-1"
        )
        self.produce_replay_summary("u1", "test_viewed_state_of_session_recording_version-1", base_time)
        self.produce_replay_summary(
            "u1", "test_viewed_state_of_session_recording_version-2", base_time + relativedelta(seconds=30)
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        response_data = response.json()

        assert [(r["id"], r["viewed"]) for r in response_data["results"]] == [
            ("test_viewed_state_of_session_recording_version-2", False),
            ("test_viewed_state_of_session_recording_version-1", True),
        ]

    def test_setting_viewed_state_of_session_recording(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["u1"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

        produce_replay_summary(
            session_id="1",
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=base_time.isoformat(),
            distinct_id="u1",
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        response_data = response.json()
        # Make sure it starts not viewed
        assert response_data["results"][0]["viewed"] is False
        assert response_data["results"][0]["id"] == "1"

        # can get it directly
        get_session_response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1")
        assert get_session_response.status_code == 200
        assert get_session_response.json()["viewed"] is False
        assert get_session_response.json()["id"] == "1"

        # being loaded doesn't mark it as viewed
        all_sessions_response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        response_data = all_sessions_response.json()
        # Make sure it remains not viewed
        assert response_data["results"][0]["viewed"] is False
        assert response_data["results"][0]["id"] == "1"

    @patch("posthoganalytics.capture")
    def test_update_session_recording_viewed(self, mock_capture: MagicMock):
        session_id = "test_update_viewed_state"
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        Person.objects.create(
            team=self.team,
            distinct_ids=["u1"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=base_time.isoformat(),
            distinct_id="u1",
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,
        )

        # Verify initial state
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}")
        assert response.status_code == 200
        assert response.json()["viewed"] is False

        # Update viewed state
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}",
            {"viewed": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["success"] is True

        # Verify updated state
        # We don't get the viewed state back in the retrieve endpoint, so we need to list them
        final_view_response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        response_data = final_view_response.json()
        assert response_data["results"][0]["viewed"] is True
        assert response_data["results"][0]["id"] == "test_update_viewed_state"

        assert len(mock_capture.call_args_list) == 1
        assert mock_capture.call_args_list[0][1]["event"] == "recording viewed"

    @patch("posthoganalytics.capture")
    def test_update_session_recording_analyzed(self, mock_capture: MagicMock):
        session_id = "test_update_analyzed_state"
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=base_time.isoformat(),
            distinct_id="u1",
        )

        # Update analyzed state
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}",
            {"analyzed": True},
        )
        assert update_response.status_code == 200
        assert update_response.json()["success"] is True

        # Verify that the appropriate event was reported
        assert len(mock_capture.call_args_list) == 1
        assert mock_capture.call_args_list[0][1]["event"] == "recording analyzed"

    def test_update_session_recording_invalid_data(self):
        session_id = "test_update_invalid_data"
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=base_time.isoformat(),
            distinct_id="u1",
        )

        # Attempt to update with invalid data
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}",
            {"invalid_field": True},
        )
        assert update_response.status_code == 400

    def test_update_nonexistent_session_recording(self):
        nonexistent_session_id = "nonexistent_session"

        # Attempt to update a non-existent session recording
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recordings/{nonexistent_session_id}",
            {"viewed": True},
        )
        assert update_response.status_code == 404

    @freeze_time("2023-01-01T12:00:00.000Z")
    def test_get_single_session_recording_metadata(self):
        p = Person.objects.create(
            team=self.team,
            distinct_ids=["d1"],
            properties={"$some_prop": "something", "email": "bob@bob.com"},
        )
        session_recording_id = str(uuid7())
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        produce_replay_summary(
            session_id=session_recording_id,
            team_id=self.team.pk,
            first_timestamp=base_time.isoformat(),
            last_timestamp=(base_time + relativedelta(seconds=30)).isoformat(),
            distinct_id="d1",
            retention_period_days=30,
        )

        other_user = User.objects.create(email="paul@not-first-user.com")
        SessionRecordingViewed.objects.create(
            team=self.team,
            user=other_user,
            session_id=session_recording_id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_recording_id}")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "id": session_recording_id,
            "distinct_id": "d1",
            "viewed": False,
            "viewers": [other_user.email],
            "recording_duration": 30,
            "start_time": base_time.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": (base_time + relativedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiry_time": (base_time + relativedelta(days=30))
            .replace(microsecond=0, second=0, minute=0, hour=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "click_count": 0,
            "keypress_count": 0,
            "start_url": "https://not-provided-by-test.com",
            "mouse_activity_count": 0,
            "inactive_seconds": 30,
            "active_seconds": 0,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "person": {
                "id": p.id,
                "name": "bob@bob.com",
                "distinct_ids": ["d1"],
                "properties": {"email": "bob@bob.com", "$some_prop": "something"},
                "created_at": "2023-01-01T12:00:00Z",
                "uuid": ANY,
            },
            "storage": "object_storage",
            "retention_period_days": 30,
            "recording_ttl": 29,
            "snapshot_source": "web",
            "ongoing": None,
            "activity_score": None,
        }

    def test_get_single_session_recording_viewed_stats_someone_else_viewed(self):
        with freeze_time("2023-01-01T12:00:00.000Z"):
            session_recording_id = "session_1"
            base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
            produce_replay_summary(
                session_id=session_recording_id,
                team_id=self.team.pk,
                first_timestamp=base_time.isoformat(),
                last_timestamp=(base_time + relativedelta(seconds=30)).isoformat(),
                distinct_id="d1",
            )

            other_user = User.objects.create(email="paul@not-first-user.com")
            SessionRecordingViewed.objects.create(
                team=self.team,
                user=other_user,
                session_id=session_recording_id,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_recording_id}/viewed")
        response_data = response.json()

        assert response_data == {
            "viewed": False,
            "other_viewers": 1,
        }

    def test_get_single_session_recording_viewed_stats_current_user_viewed(self):
        with freeze_time("2023-01-01T12:00:00.000Z"):
            session_recording_id = "session_1"
            base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
            produce_replay_summary(
                session_id=session_recording_id,
                team_id=self.team.pk,
                first_timestamp=base_time.isoformat(),
                last_timestamp=(base_time + relativedelta(seconds=30)).isoformat(),
                distinct_id="d1",
            )

            SessionRecordingViewed.objects.create(
                team=self.team,
                user=self.user,
                session_id=session_recording_id,
            )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_recording_id}/viewed")
        response_data = response.json()

        assert response_data == {
            "viewed": True,
            "other_viewers": 0,
        }

    def test_get_single_session_recording_viewed_stats_can_404(self):
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/12345/viewed")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "viewed": False,
            "other_viewers": 0,
        }

    def test_single_session_recording_doesnt_leak_teams(self):
        another_team = Team.objects.create(organization=self.organization)
        self.produce_replay_summary(
            "user",
            "id_no_team_leaking",
            now() - relativedelta(days=1),
            team_id=another_team.pk,
        )
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/id_no_team_leaking")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/id_no_team_leaking/snapshots")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json())

    def test_session_recording_with_no_person(self):
        produce_replay_summary(
            session_id="id_no_person",
            team_id=self.team.pk,
            first_timestamp=(now() - relativedelta(days=1)).isoformat(),
            last_timestamp=(now() - relativedelta(days=1)).isoformat(),
            distinct_id="d1",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/id_no_person")
        response_data = response.json()

        self.assertEqual(
            response_data["person"],
            {
                "id": None,
                "name": None,
                "distinct_ids": ["d1"],
                "properties": {},
                "created_at": None,
                "uuid": response_data["person"]["uuid"],
            },
        )

    def test_session_recording_doesnt_exist(self):
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/non_existent_id")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/non_existent_id/snapshots")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_request_to_another_teams_endpoint_returns_401(self):
        org = Organization.objects.create(name="Separate Org")
        another_team = Team.objects.create(organization=org)
        self.produce_replay_summary(
            "user",
            "id_no_team_leaking",
            now() - relativedelta(days=1),
            team_id=another_team.pk,
        )
        response = self.client.get(f"/api/projects/{another_team.pk}/session_recordings/id_no_team_leaking")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            (False, 3),
            (True, 1),
        ]
    )
    def test_session_ids_filter(self, use_recording_events: bool, api_version: int):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            Person.objects.create(
                team=self.team,
                distinct_ids=["user"],
                properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            self.produce_replay_summary(
                "user",
                "1",
                now() - relativedelta(days=1),
            )
            self.produce_replay_summary(
                "user",
                "2",
                now() - relativedelta(days=2),
            )
            self.produce_replay_summary(
                "user",
                "3",
                now() - relativedelta(days=3),
            )

            # Fetch playlist
            params_string = urlencode({"session_ids": '["1", "2", "3"]', "version": api_version})
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings?{params_string}")
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()

            assert len(response_data["results"]) == 3
            assert response_data["results"][0]["id"] == "1"
            assert response_data["results"][1]["id"] == "2"
            assert response_data["results"][2]["id"] == "3"

    def test_empty_list_session_ids_filter_returns_no_recordings(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            Person.objects.create(
                team=self.team,
                distinct_ids=["user"],
                properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            self.produce_replay_summary("user", "1", now() - relativedelta(days=1))
            self.produce_replay_summary("user", "2", now() - relativedelta(days=2))
            self.produce_replay_summary("user", "3", now() - relativedelta(days=3))

            # Fetch playlist
            params_string = urlencode({"session_ids": "[]"})
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings?{params_string}")
            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()

            assert len(response_data["results"]) == 0

    def test_delete_session_recording(self):
        self.produce_replay_summary("user", "1", now() - relativedelta(days=1), team_id=self.team.pk)
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/1")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # Trying to delete same recording again returns 404
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/1")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch(
        "posthog.session_recordings.session_recording_v2_service.copy_to_lts",
        return_value="some-lts-path",
    )
    def test_persist_session_recording(self, _mock_copy_objects: MagicMock) -> None:
        self.produce_replay_summary("user", "1", now() - relativedelta(days=1), team_id=self.team.pk)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["storage"] == "object_storage"

        response = self.client.post(f"/api/projects/{self.team.id}/session_recordings/1/persist")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"success": True}

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["storage"] == "object_storage_lts"

    def test_get_matching_events_for_must_not_send_multiple_session_ids(self) -> None:
        query_params = [
            f'session_ids=["{str(uuid7())}", "{str(uuid7())}"]',
        ]
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/matching_events?{'&'.join(query_params)}"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "Must specify exactly one session_id",
            "type": "validation_error",
        }

    def test_get_matching_events_for_must_send_a_single_session_id_filter(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/matching_events?")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "Must specify exactly one session_id",
            "type": "validation_error",
        }

    def test_get_matching_events_for_must_send_at_least_an_event_filter(self) -> None:
        query_params = [
            f'session_ids=["{str(uuid7())}"]',
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/matching_events?{'&'.join(query_params)}"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "Must specify at least one event or action filter, or event properties filter",
            "type": "validation_error",
        }

    def test_get_matching_events_can_send_event_properties_filter(self) -> None:
        query_params = [
            f'session_ids=["{str(uuid7())}"]',
            # we can send event action or event properties filters and it is valid
            'properties=[{"key":"$active_feature_flags","value":"query_running_time","operator":"icontains","type":"event"}]',
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/matching_events?{'&'.join(query_params)}"
        )
        assert response.status_code == status.HTTP_200_OK

    def test_get_matching_events_for_unknown_session(self) -> None:
        session_id = str(uuid7())
        query_params = [
            f'session_ids=["{session_id}"]',
            'events=[{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]',
        ]
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/matching_events?{'&'.join(query_params)}"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": []}

    def test_get_matching_events_with_query(self) -> None:
        """both sessions have a pageview, but only the specified session returns a single UUID for the pageview events"""
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

        # the matching session
        matching_events_session = str(uuid7())
        self.produce_replay_summary("user", matching_events_session, base_time)
        event_id = _create_event(
            event="$pageview",
            properties={"$session_id": matching_events_session},
            team=self.team,
            distinct_id=str(uuid7()),
        )
        _create_event(
            event="a different event that we shouldn't see",
            properties={"$session_id": matching_events_session},
            team=self.team,
            distinct_id=str(uuid7()),
        )

        # a non-matching session
        non_matching_session_id = str(uuid7())
        self.produce_replay_summary("user", non_matching_session_id, base_time)
        _create_event(
            event="$pageview",
            properties={"$session_id": non_matching_session_id},
            team=self.team,
            distinct_id=str(uuid7()),
        )

        query_params = [
            f'session_ids=["{matching_events_session}"]',
            'events=[{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]',
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/matching_events?{'&'.join(query_params)}"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["uuid"] == event_id
        assert "timestamp" in results[0]

    def test_get_matching_events(self) -> None:
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)

        # the matching session
        session_id = f"test_get_matching_events-1-{uuid7()}"
        self.produce_replay_summary("user", session_id, base_time)
        event_id_one = _create_event(
            event="$pageview",
            properties={"$session_id": session_id},
            team=self.team,
            distinct_id=uuid7(),
            timestamp=base_time + timedelta(seconds=1),
        )
        event_id_two = _create_event(
            event="$pageview",
            properties={"$session_id": session_id},
            team=self.team,
            distinct_id=uuid7(),
            timestamp=base_time + timedelta(seconds=10),
        )
        event_id_three = _create_event(
            event="$pageview",
            properties={"$session_id": session_id},
            team=self.team,
            distinct_id=uuid7(),
            timestamp=base_time + timedelta(seconds=6),
        )

        # a non-matching session
        non_matching_session_id = f"test_get_matching_events-2-{uuid7()}"
        self.produce_replay_summary("user", non_matching_session_id, base_time)
        _create_event(
            event="$pageview",
            properties={"$session_id": non_matching_session_id},
            team=self.team,
            distinct_id=uuid7(),
        )

        query_params = [
            f'session_ids=["{session_id}"]',
            'events=[{"id": "$pageview", "type": "events", "order": 0, "name": "$pageview"}]',
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/matching_events?{'&'.join(query_params)}"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        results = response.json()["results"]
        assert len(results) == 3
        result_uuids = sorted([r["uuid"] for r in results])
        expected_uuids = sorted([event_id_one, event_id_three, event_id_two])
        assert result_uuids == expected_uuids
        # Verify all results have timestamps
        for result in results:
            assert "timestamp" in result

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_400_when_invalid_list_query(self) -> None:
        query_params = "&".join(
            [
                f'session_ids="invalid"',
                "hogql_filtering=1",
                "tomato=potato",
                "version=2",
            ]
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings?{query_params}",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            '{"type": "extra_forbidden", "loc": ["tomato"], "msg": "Extra inputs are not permitted", "input": "potato", "url": "https://errors.pydantic.dev/2.10/v/extra_forbidden"}'
            in response.json()["detail"]
        )
        assert response.json() == self.snapshot

    @parameterized.expand(
        [
            (
                "too_many_queries",
                CHQueryErrorTooManySimultaneousQueries("Too many simultaneous queries"),
                "Too many simultaneous queries. Try again later.",
            ),
            (
                "timeout_exceeded",
                ServerException("CHQueryErrorTimeoutExceeded"),
                "Query timeout exceeded. Try again later.",
            ),
        ]
    )
    @patch("posthog.session_recordings.queries.session_recording_list_from_query.SessionRecordingListFromQuery.run")
    def test_session_recordings_query_errors(self, _name, exception, expected_message, mock_run):
        mock_run.side_effect = exception
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json() == {
            "attr": None,
            "code": "throttled",
            "detail": expected_message,
            "type": "throttled_error",
        }

    def test_sync_execute_ch_cannot_schedule_task_retry_then_503(self):
        """Test that list_blocks throws CHQueryErrorCannotScheduleTask multiple times and eventually returns 503"""
        call_count = 0

        def mock_list_blocks(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise CHQueryErrorCannotScheduleTask("Cannot schedule task", code=439)

        # Patch list_blocks where it's imported and used in session_recording_v2_service
        with patch("posthog.session_recordings.session_recording_api.list_blocks", side_effect=mock_list_blocks):
            session_id = str(uuid7())
            self.produce_replay_summary("user", session_id, now() - relativedelta(days=1))

            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?blob_v2=true"
            )

            # Verify the error was called multiple times and we get 503
            assert call_count > 2, f"Expected multiple calls, got {call_count}"
            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_bulk_delete_session_recordings(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1", "user2"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)

        # Create test recordings
        session_ids = ["bulk_delete_test_1", "bulk_delete_test_2", "bulk_delete_test_3"]
        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        # Bulk delete
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        assert response_data["success"]
        assert response_data["deleted_count"] == 3
        assert response_data["total_requested"] == 3

        # Verify recordings are marked as deleted
        for session_id in session_ids:
            recording = SessionRecording.objects.get(team=self.team, session_id=session_id)
            assert recording.deleted

    @parameterized.expand(
        [
            (
                "empty_array",
                {"session_recording_ids": []},
                "session_recording_ids must be provided as a non-empty array",
            ),
            (
                "missing_field",
                {},
                "session_recording_ids must be provided as a non-empty array",
            ),
            (
                "invalid_type",
                {"session_recording_ids": "not_a_list"},
                "session_recording_ids must be provided as a non-empty array",
            ),
            (
                "too_many_recordings",
                {"session_recording_ids": [f"bulk_delete_test_{i}" for i in range(21)]},
                "Cannot process more than 20 recordings at once",
            ),
        ]
    )
    def test_bulk_delete_validation_errors(self, test_name, request_data, expected_error_message):
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            request_data,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == expected_error_message

    def test_bulk_delete_skips_already_deleted_recordings(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)

        # Create recordings
        session_ids = ["bulk_delete_existing_1", "bulk_delete_existing_2"]
        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        # Mark one as already deleted
        SessionRecording.objects.create(
            team=self.team,
            session_id="bulk_delete_existing_1",
            distinct_id="user1",
            deleted=True,
        )

        # Bulk delete
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Should only delete the one that wasn't already deleted
        assert response_data["deleted_count"] == 1
        assert response_data["total_requested"] == 2

    def test_bulk_delete_nonexistent_recordings(self):
        session_ids = ["nonexistent_1", "nonexistent_2"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Should return 0 deleted since recordings don't exist
        assert response_data["deleted_count"] == 0
        assert response_data["total_requested"] == 2

    def test_bulk_delete_mixed_existing_and_nonexistent(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)

        # Create one existing recording
        self.produce_replay_summary("user1", "bulk_delete_mixed_existing", base_time)

        session_ids = ["bulk_delete_mixed_existing", "bulk_delete_mixed_nonexistent"]

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Should delete only the existing one
        assert response_data["deleted_count"] == 1
        assert response_data["total_requested"] == 2

    def test_bulk_delete_creates_postgres_records_for_clickhouse_only_recordings(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)
        session_id = "bulk_delete_ch_only"

        # Create recording only in ClickHouse (via produce_replay_summary)
        self.produce_replay_summary("user1", session_id, base_time)

        # Verify no PostgreSQL record exists yet
        assert not SessionRecording.objects.filter(team=self.team, session_id=session_id).exists()

        # Bulk delete
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": [session_id]},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        assert response_data["deleted_count"] == 1

        # Verify PostgreSQL record was created and marked as deleted
        recording = SessionRecording.objects.get(team=self.team, session_id=session_id)
        assert recording.deleted
        assert recording.distinct_id == "user1"

    @patch("posthog.session_recordings.session_recording_api.logger")
    def test_bulk_delete_logging(self, mock_logger):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)
        session_ids = ["bulk_delete_log_test_1", "bulk_delete_log_test_2"]

        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify logging was called
        mock_logger.info.assert_called_once_with(
            "bulk_recordings_deleted",
            team_id=self.team.id,
            deleted_count=2,
            total_requested=2,
        )

    def test_bulk_delete_doesnt_leak_teams(self):
        other_team = Team.objects.create(organization=self.organization)
        Person.objects.create(
            team=other_team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)
        session_id = "bulk_delete_other_team"

        # Create recording in another team
        self.produce_replay_summary("user1", session_id, base_time, team_id=other_team.pk)

        # Try to bulk delete from current team
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_delete",
            {"session_recording_ids": [session_id]},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Should not delete anything since recording belongs to other team
        assert response_data["deleted_count"] == 0
        assert response_data["total_requested"] == 1

    def test_bulk_viewed_session_recordings(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1", "user2"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)

        # Create test recordings
        session_ids = ["bulk_viewed_test_1", "bulk_viewed_test_2", "bulk_viewed_test_3"]
        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        # Bulk mark as viewed
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_viewed",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        assert response_data["success"]
        assert response_data["viewed_count"] == 3
        assert response_data["total_requested"] == 3

        # Verify recordings are marked as viewed in database
        for session_id in session_ids:
            viewed_record = SessionRecordingViewed.objects.get(team=self.team, user=self.user, session_id=session_id)
            assert viewed_record is not None

    def test_bulk_viewed_handles_duplicates(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)
        session_ids = ["bulk_viewed_dup_1", "bulk_viewed_dup_2", "bulk_viewed_dup_3"]

        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        # Mark first two as already viewed
        for session_id in session_ids[:2]:
            SessionRecordingViewed.objects.create(
                team=self.team,
                user=self.user,
                session_id=session_id,
            )

        # Bulk mark all as viewed (including already viewed ones)
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_viewed",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Should process all 3 recordings (viewed_count represents total processed)
        assert response_data["viewed_count"] == 3
        assert response_data["total_requested"] == 3

        # Verify all recordings are marked as viewed in database
        for session_id in session_ids:
            viewed_record = SessionRecordingViewed.objects.get(team=self.team, user=self.user, session_id=session_id)
            assert viewed_record is not None

    def test_bulk_not_viewed_session_recordings(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)
        session_ids = ["bulk_not_viewed_test_1", "bulk_not_viewed_test_2", "bulk_not_viewed_test_3"]

        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        # First mark all as viewed
        for session_id in session_ids:
            SessionRecordingViewed.objects.create(
                team=self.team,
                user=self.user,
                session_id=session_id,
            )

        # Bulk mark as not viewed
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_not_viewed",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        assert response_data["success"]
        assert response_data["not_viewed_count"] == 3
        assert response_data["total_requested"] == 3

        # Verify viewed records are deleted
        for session_id in session_ids:
            assert not SessionRecordingViewed.objects.filter(
                team=self.team, user=self.user, session_id=session_id
            ).exists()

    def test_bulk_not_viewed_handles_already_not_viewed(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["user1"],
            properties={"email": "test@example.com"},
        )

        base_time = now() - relativedelta(days=1)
        session_ids = ["bulk_not_viewed_mixed_1", "bulk_not_viewed_mixed_2", "bulk_not_viewed_mixed_3"]

        for session_id in session_ids:
            self.produce_replay_summary("user1", session_id, base_time)

        # Mark only first two as viewed
        for session_id in session_ids[:2]:
            SessionRecordingViewed.objects.create(
                team=self.team,
                user=self.user,
                session_id=session_id,
            )

        # Bulk mark all as not viewed (including one that wasn't viewed)
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recordings/bulk_not_viewed",
            {"session_recording_ids": session_ids},
        )

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()

        # Should only delete 2 viewed records
        assert response_data["not_viewed_count"] == 2
        assert response_data["total_requested"] == 3
