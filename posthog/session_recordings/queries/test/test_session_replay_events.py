from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import (
    SESSION_ID_CLOCK_SKEW_SLACK,
    SessionReplayEvents,
    get_latest_session_event_properties,
    uuidv7_session_lower_bound,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class SessionReplayEventsQueries(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        self.base_expiry_time = (now() + relativedelta(days=29)).replace(microsecond=0, second=0, minute=0, hour=0)
        produce_replay_summary(
            session_id="1",
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time,
            distinct_id="u1",
            first_url="https://example.io/home",
            click_count=2,
            keypress_count=2,
            mouse_activity_count=2,
            active_milliseconds=50 * 1000 * 0.5,
            retention_period_days=30,
        )
        produce_replay_summary(
            session_id="2",
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=2),
            distinct_id="u2",
            first_url="https://example.io/home",
            click_count=100,
            keypress_count=200,
            mouse_activity_count=300,
            active_milliseconds=1234,
            block_urls=["s3://block-1"],
            block_first_timestamps=[self.base_time],
            block_last_timestamps=[self.base_time + relativedelta(seconds=2)],
            retention_period_days=90,
        )
        produce_replay_summary(
            session_id="3",
            team_id=self.team.pk,
            first_timestamp=self.base_time + relativedelta(seconds=1),
            last_timestamp=self.base_time + relativedelta(seconds=3),
            distinct_id="u3",
            first_url="https://example.io/1",
            click_count=10,
            keypress_count=20,
            mouse_activity_count=30,
            active_milliseconds=2345,
            block_urls=["s3://block-x", "s3://block-y"],
            block_first_timestamps=[
                self.base_time + relativedelta(seconds=1),
                self.base_time + relativedelta(seconds=2),
            ],
            block_last_timestamps=[
                self.base_time + relativedelta(seconds=2),
                self.base_time + relativedelta(seconds=3),
            ],
            retention_period_days=365,
        )

    def test_get_metadata(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="1", team=self.team)
        assert metadata == {
            "active_seconds": 25.0,
            "block_first_timestamps": [],
            "block_last_timestamps": [],
            "block_urls": [],
            "click_count": 2,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "distinct_id": "u1",
            "duration": 0,
            "end_time": self.base_time,
            "expiry_time": self.base_expiry_time,
            "first_url": "https://example.io/home",
            "keypress_count": 2,
            "mouse_activity_count": 2,
            "retention_period_days": 30,
            "recording_ttl": 29,
            "start_time": self.base_time,
            "snapshot_source": "web",
            "snapshot_library": None,
        }

    def test_get_metadata_with_block(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="2", team=self.team)
        assert metadata == {
            "active_seconds": 1.234,
            "start_time": self.base_time,
            "end_time": self.base_time + relativedelta(seconds=2),
            "expiry_time": self.base_expiry_time + relativedelta(days=60),
            "block_first_timestamps": [self.base_time],
            "block_last_timestamps": [self.base_time + relativedelta(seconds=2)],
            "block_urls": ["s3://block-1"],
            "click_count": 100,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "distinct_id": "u2",
            "duration": 2,
            "first_url": "https://example.io/home",
            "keypress_count": 200,
            "retention_period_days": 90,
            "recording_ttl": 89,
            "mouse_activity_count": 300,
            "snapshot_source": "web",
            "snapshot_library": None,
        }

    def test_get_metadata_with_multiple_blocks(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="3", team=self.team)
        assert metadata == {
            "active_seconds": 2.345,
            "start_time": self.base_time + relativedelta(seconds=1),
            "end_time": self.base_time + relativedelta(seconds=3),
            "expiry_time": self.base_expiry_time + relativedelta(days=335),
            "block_first_timestamps": [
                self.base_time + relativedelta(seconds=1),
                self.base_time + relativedelta(seconds=2),
            ],
            "block_last_timestamps": [
                self.base_time + relativedelta(seconds=2),
                self.base_time + relativedelta(seconds=3),
            ],
            "block_urls": ["s3://block-x", "s3://block-y"],
            "click_count": 10,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "distinct_id": "u3",
            "duration": 2,
            "first_url": "https://example.io/1",
            "keypress_count": 20,
            "mouse_activity_count": 30,
            "retention_period_days": 365,
            "recording_ttl": 364,
            "snapshot_source": "web",
            "snapshot_library": None,
        }

    def test_get_nonexistent_metadata(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="not a session", team=self.team)
        assert metadata is None

    def test_get_metadata_does_not_leak_between_teams(self) -> None:
        another_team = Team.objects.create(organization=self.organization, name="Another Team")
        metadata = SessionReplayEvents().get_metadata(session_id="1", team=another_team)
        assert metadata is None

    def test_get_metadata_filters_by_date(self) -> None:
        metadata = SessionReplayEvents().get_metadata(
            session_id="1",
            team=self.team,
            recording_start_time=self.base_time + relativedelta(days=2),
        )
        assert metadata is None

    def test_get_group_metadata(self) -> None:
        metadata_dict = SessionReplayEvents().get_group_metadata(
            session_ids=["1", "2"],
            team=self.team,
        )
        assert len(metadata_dict) == 2
        assert metadata_dict["1"] == {
            "active_seconds": 25.0,
            "block_first_timestamps": [],
            "block_last_timestamps": [],
            "block_urls": [],
            "click_count": 2,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "distinct_id": "u1",
            "duration": 0,
            "end_time": self.base_time,
            "expiry_time": self.base_expiry_time,
            "first_url": "https://example.io/home",
            "keypress_count": 2,
            "mouse_activity_count": 2,
            "retention_period_days": 30,
            "recording_ttl": 29,
            "start_time": self.base_time,
            "snapshot_source": "web",
            "snapshot_library": None,
        }
        assert metadata_dict["2"] == {
            "active_seconds": 1.234,
            "start_time": self.base_time,
            "end_time": self.base_time + relativedelta(seconds=2),
            "expiry_time": self.base_expiry_time + relativedelta(days=60),
            "block_first_timestamps": [self.base_time],
            "block_last_timestamps": [self.base_time + relativedelta(seconds=2)],
            "block_urls": ["s3://block-1"],
            "click_count": 100,
            "console_error_count": 0,
            "console_log_count": 0,
            "console_warn_count": 0,
            "distinct_id": "u2",
            "duration": 2,
            "first_url": "https://example.io/home",
            "keypress_count": 200,
            "mouse_activity_count": 300,
            "retention_period_days": 90,
            "recording_ttl": 89,
            "snapshot_source": "web",
            "snapshot_library": None,
        }

    def test_get_group_metadata_handles_nonexistent_sessions(self) -> None:
        metadata_dict = SessionReplayEvents().get_group_metadata(
            session_ids=["1", "nonexistent", "3"],
            team=self.team,
        )
        assert len(metadata_dict) == 3
        assert metadata_dict["1"] is not None
        assert metadata_dict["nonexistent"] is None
        assert metadata_dict["3"] is not None

    def test_sessions_found_with_timestamps(self) -> None:
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=["1", "2", "3"],
            team=self.team,
        )
        assert sessions == {"1", "2", "3"}
        assert min_ts == self.base_time
        assert max_ts == self.base_time + relativedelta(seconds=3)

    def test_sessions_found_with_timestamps_partial_match(self) -> None:
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=["1", "nonexistent", "3"],
            team=self.team,
        )
        assert sessions == {"1", "3"}
        assert min_ts == self.base_time
        assert max_ts == self.base_time + relativedelta(seconds=3)

    def test_sessions_found_with_timestamps_empty_list(self) -> None:
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=[],
            team=self.team,
        )
        assert sessions == set()
        assert min_ts is None
        assert max_ts is None

    def test_sessions_found_with_timestamps_no_matches(self) -> None:
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=["nonexistent1", "nonexistent2"],
            team=self.team,
        )
        assert sessions == set()
        assert min_ts is None
        assert max_ts is None

    def test_sessions_found_with_timestamps_single_session(self) -> None:
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=["2"],
            team=self.team,
        )
        assert sessions == {"2"}
        assert min_ts == self.base_time
        assert max_ts == self.base_time + relativedelta(seconds=2)

    def test_sessions_found_with_timestamps_excludes_sessions_without_events(self) -> None:
        # Create a session replay without any events
        produce_replay_summary(
            session_id="no_events_session",
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time + relativedelta(seconds=5),
            distinct_id="u_no_events",
            first_url="https://example.io/no-events",
            retention_period_days=30,
            ensure_analytics_event_in_session=False,
        )
        # Should not include the session without events
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=["1", "no_events_session"],
            team=self.team,
        )
        assert sessions == {"1"}
        assert min_ts == self.base_time
        assert max_ts == self.base_time

    def test_sessions_found_with_timestamps_all_sessions_without_events(self) -> None:
        # Create sessions without events
        produce_replay_summary(
            session_id="no_events_1",
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time,
            distinct_id="u_no_events_1",
            first_url="https://example.io/no-events-1",
            retention_period_days=30,
            ensure_analytics_event_in_session=False,
        )
        produce_replay_summary(
            session_id="no_events_2",
            team_id=self.team.pk,
            first_timestamp=self.base_time,
            last_timestamp=self.base_time,
            distinct_id="u_no_events_2",
            first_url="https://example.io/no-events-2",
            retention_period_days=30,
            ensure_analytics_event_in_session=False,
        )
        # Should return empty when all sessions lack events
        sessions, min_ts, max_ts = SessionReplayEvents().sessions_found_with_timestamps(
            session_ids=["no_events_1", "no_events_2"],
            team=self.team,
        )
        assert sessions == set()
        assert min_ts is None
        assert max_ts is None


def _uuidv7_session_id_for(ts) -> str:
    ms = int(ts.timestamp() * 1000)
    hex12 = f"{ms:012x}"
    return f"{hex12[:8]}-{hex12[8:12]}-7000-8000-000000000000"


class TestUuidv7SessionLowerBound(APIBaseTest):
    @parameterized.expand(
        [
            ("uuidv4_id", "7c10ab30-3a9c-4b75-89ce-09e51c826989", None),
            ("non_uuid_id", "my-custom-session", None),
            ("implausibly_old_embedded_timestamp", "0000ffff-ffff-7000-8000-000000000000", None),
            ("far_future_embedded_timestamp", "ffffffff-ffff-7000-8000-000000000000", None),
        ]
    )
    def test_returns_no_bound(self, _name: str, session_id: str, expected: None) -> None:
        assert uuidv7_session_lower_bound(session_id) is expected

    def test_derives_bound_from_embedded_timestamp(self) -> None:
        session_start = (now() - relativedelta(days=1)).replace(microsecond=0)
        bound = uuidv7_session_lower_bound(_uuidv7_session_id_for(session_start))
        assert bound == session_start - SESSION_ID_CLOCK_SKEW_SLACK


class TestSessionLookupUsesUuidv7Bound(ClickhouseTestMixin, APIBaseTest):
    def test_finds_session_with_uuidv7_id_seeded_at_its_embedded_time(self) -> None:
        session_start = (now() - relativedelta(days=1)).replace(microsecond=0)
        session_id = _uuidv7_session_id_for(session_start)
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp=session_start,
            last_timestamp=session_start,
            distinct_id="u1",
            retention_period_days=30,
        )

        assert SessionReplayEvents().exists(session_id, self.team) is True
        assert SessionReplayEvents().get_metadata(session_id, self.team) is not None

    def test_finds_session_seeded_far_before_its_ids_embedded_time_via_unbounded_fallback(self) -> None:
        # A recording whose events predate the session id's embedded timestamp by more
        # than the clock-skew slack misses the derived scan window; the lookup retries
        # unbounded so the recording is still found, just on the slower path.
        session_start = (now() - relativedelta(days=1)).replace(microsecond=0)
        session_id = _uuidv7_session_id_for(session_start)
        produce_replay_summary(
            session_id=session_id,
            team_id=self.team.pk,
            first_timestamp=session_start - relativedelta(days=10),
            last_timestamp=session_start - relativedelta(days=10),
            distinct_id="u1",
            retention_period_days=30,
        )

        assert SessionReplayEvents().exists(session_id, self.team)
        assert SessionReplayEvents().get_metadata(session_id, self.team) is not None

    def test_batch_with_mixed_id_formats_finds_all_sessions(self) -> None:
        # One uuidv7 id and one custom id in the same batch: the unparseable id
        # disables the bound for the whole batch, so both stay findable.
        session_start = (now() - relativedelta(days=1)).replace(microsecond=0)
        uuid_id = _uuidv7_session_id_for(session_start)
        custom_id = "my-custom-session-id"
        for session_id in (uuid_id, custom_id):
            produce_replay_summary(
                session_id=session_id,
                team_id=self.team.pk,
                first_timestamp=session_start,
                last_timestamp=session_start,
                distinct_id="u1",
                retention_period_days=30,
            )

        found = SessionReplayEvents()._find_with_timestamps([uuid_id, custom_id], self.team)

        assert {session_id for session_id, _, _, _ in found} == {uuid_id, custom_id}


class TestGetLatestSessionEventProperties(ClickhouseTestMixin, APIBaseTest):
    def _seed_event(self, session_id: str, timestamp, marker: str) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            timestamp=timestamp,
            properties={"$session_id": session_id, "$recording_status": marker},
        )

    @parameterized.expand(
        [
            ("event_within_uuidv7_window", True, relativedelta(minutes=0), "bounded"),
            ("event_outside_uuidv7_window_via_fallback", True, relativedelta(days=10), "fallback"),
            ("non_uuid_session_id_via_fallback", False, relativedelta(minutes=0), "custom"),
        ]
    )
    def test_finds_event(self, _name: str, uuidv7_id: bool, event_age_before_start, marker: str) -> None:
        session_start = (now() - relativedelta(minutes=10)).replace(microsecond=0)
        session_id = _uuidv7_session_id_for(session_start) if uuidv7_id else "my-custom-session-id"
        self._seed_event(session_id, session_start - event_age_before_start, marker)

        properties = get_latest_session_event_properties(session_id, self.team)

        assert properties is not None
        assert properties["$recording_status"] == marker

    def test_filters_response_to_diagnostic_properties(self) -> None:
        session_start = (now() - relativedelta(minutes=10)).replace(microsecond=0)
        session_id = _uuidv7_session_id_for(session_start)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            timestamp=session_start,
            properties={
                "$session_id": session_id,
                "$recording_status": "disabled",
                "$sdk_debug_replay_internal_buffer_length": 0,
                "$current_url": "https://example.com/private-path",
                "email": "person@example.com",
            },
        )

        properties = get_latest_session_event_properties(session_id, self.team)

        assert properties == {
            "$recording_status": "disabled",
            "$sdk_debug_replay_internal_buffer_length": 0,
        }

    def test_returns_none_when_session_has_no_events(self) -> None:
        session_id = _uuidv7_session_id_for(now() - relativedelta(minutes=10))

        assert get_latest_session_event_properties(session_id, self.team) is None

    def test_does_not_leak_another_teams_session(self) -> None:
        session_start = (now() - relativedelta(minutes=10)).replace(microsecond=0)
        session_id = _uuidv7_session_id_for(session_start)
        other_team = Team.objects.create(organization=self.organization, name="other team")
        _create_event(
            team=other_team,
            event="$pageview",
            distinct_id="d1",
            timestamp=session_start,
            properties={"$session_id": session_id, "$recording_status": "secret"},
        )

        assert get_latest_session_event_properties(session_id, self.team) is None

        response = self.client.get(
            f"/api/environments/{self.team.id}/session_recordings/{session_id}/capture_diagnostics"
        )
        assert response.status_code == 200
        assert response.json()["properties"] is None

    def test_capture_diagnostics_endpoint_returns_properties(self) -> None:
        session_start = (now() - relativedelta(minutes=10)).replace(microsecond=0)
        session_id = _uuidv7_session_id_for(session_start)
        self._seed_event(session_id, session_start, "endpoint")

        response = self.client.get(
            f"/api/environments/{self.team.id}/session_recordings/{session_id}/capture_diagnostics"
        )

        assert response.status_code == 200
        assert response.json()["properties"]["$recording_status"] == "endpoint"
