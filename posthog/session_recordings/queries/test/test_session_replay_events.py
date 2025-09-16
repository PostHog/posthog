from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


class SessionReplayEventsQueries(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
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
        metadata = SessionReplayEvents().get_metadata(session_id="1", team_id=self.team.id)
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
            "first_url": "https://example.io/home",
            "keypress_count": 2,
            "mouse_activity_count": 2,
            "retention_period_days": 30,
            "start_time": self.base_time,
            "snapshot_source": "web",
        }

    def test_get_metadata_with_block(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="2", team_id=self.team.id)
        assert metadata == {
            "active_seconds": 1.234,
            "start_time": self.base_time,
            "end_time": self.base_time + relativedelta(seconds=2),
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
            "mouse_activity_count": 300,
            "snapshot_source": "web",
        }

    def test_get_metadata_with_multiple_blocks(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="3", team_id=self.team.id)
        assert metadata == {
            "active_seconds": 2.345,
            "start_time": self.base_time + relativedelta(seconds=1),
            "end_time": self.base_time + relativedelta(seconds=3),
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
            "snapshot_source": "web",
        }

    def test_get_nonexistent_metadata(self) -> None:
        metadata = SessionReplayEvents().get_metadata(session_id="not a session", team_id=self.team.id)
        assert metadata is None

    def test_get_metadata_does_not_leak_between_teams(self) -> None:
        another_team = Team.objects.create(organization=self.organization, name="Another Team")
        metadata = SessionReplayEvents().get_metadata(session_id="1", team_id=another_team.id)
        assert metadata is None

    def test_get_metadata_filters_by_date(self) -> None:
        metadata = SessionReplayEvents().get_metadata(
            session_id="1",
            team_id=self.team.id,
            recording_start_time=self.base_time + relativedelta(days=2),
        )
        assert metadata is None

    def test_get_group_metadata(self) -> None:
        metadata_dict = SessionReplayEvents().get_group_metadata(
            session_ids=["1", "2"],
            team_id=self.team.id,
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
            "first_url": "https://example.io/home",
            "keypress_count": 2,
            "mouse_activity_count": 2,
            "retention_period_days": 30,
            "start_time": self.base_time,
            "snapshot_source": "web",
        }
        assert metadata_dict["2"] == {
            "active_seconds": 1.234,
            "start_time": self.base_time,
            "end_time": self.base_time + relativedelta(seconds=2),
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
            "snapshot_source": "web",
        }

    def test_get_group_metadata_handles_nonexistent_sessions(self) -> None:
        metadata_dict = SessionReplayEvents().get_group_metadata(
            session_ids=["1", "nonexistent", "3"],
            team_id=self.team.id,
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
