from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import RecordingsQuery, SessionRecordingType, SnapshotSource

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.recordings_query_runner import RecordingsQueryRunner
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL


@freeze_time("2021-01-01T13:46:23")
class TestRecordingsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    def _produce_replay(self, session_id: str, **kwargs):
        produce_replay_summary(
            team_id=self.team.pk,
            session_id=session_id,
            distinct_id=kwargs.get("distinct_id", "user1"),
            first_timestamp=kwargs.get("first_timestamp", "2021-01-01T12:00:00"),
            last_timestamp=kwargs.get("last_timestamp", "2021-01-01T12:10:00"),
            first_url=kwargs.get("first_url", "https://example.com"),
            click_count=kwargs.get("click_count", 5),
            keypress_count=kwargs.get("keypress_count", 3),
            mouse_activity_count=kwargs.get("mouse_activity_count", 10),
            active_milliseconds=kwargs.get("active_milliseconds", 300000),
            console_log_count=kwargs.get("console_log_count", 1),
            console_warn_count=kwargs.get("console_warn_count", 0),
            console_error_count=kwargs.get("console_error_count", 2),
        )

    def test_returns_recordings(self):
        self._produce_replay("session-1")
        self._produce_replay("session-2", distinct_id="user2")

        runner = RecordingsQueryRunner(query=RecordingsQuery(), team=self.team)
        response = runner.calculate()

        assert len(response.results) == 2
        assert response.has_next is False

    def test_result_field_mapping(self):
        self._produce_replay("session-1", first_url="https://posthog.com")

        runner = RecordingsQueryRunner(query=RecordingsQuery(), team=self.team)
        response = runner.calculate()

        assert len(response.results) == 1
        recording = response.results[0]

        assert isinstance(recording, SessionRecordingType)
        assert recording.id == "session-1"
        assert recording.distinct_id == "user1"
        assert recording.start_url == "https://posthog.com"
        assert recording.click_count == 5
        assert recording.keypress_count == 3
        assert recording.mouse_activity_count == 10
        assert recording.console_log_count == 1
        assert recording.console_warn_count == 0
        assert recording.console_error_count == 2
        assert recording.recording_duration > 0
        assert recording.viewed is False
        assert recording.viewers == []
        assert recording.snapshot_source == SnapshotSource.WEB

    def test_respects_limit(self):
        for i in range(5):
            self._produce_replay(f"session-{i}")

        runner = RecordingsQueryRunner(query=RecordingsQuery(limit=2), team=self.team)
        response = runner.calculate()

        assert len(response.results) == 2
        assert response.has_next is True

    def test_respects_date_from(self):
        self._produce_replay("session-old", first_timestamp="2020-12-01T12:00:00", last_timestamp="2020-12-01T12:10:00")
        self._produce_replay("session-new", first_timestamp="2021-01-01T12:00:00", last_timestamp="2021-01-01T12:10:00")

        runner = RecordingsQueryRunner(query=RecordingsQuery(date_from="-1d"), team=self.team)
        response = runner.calculate()

        session_ids = [r.id for r in response.results]
        assert "session-new" in session_ids
        assert "session-old" not in session_ids

    @snapshot_clickhouse_queries
    def test_generates_valid_hogql(self):
        self._produce_replay("session-1")

        runner = RecordingsQueryRunner(query=RecordingsQuery(), team=self.team)
        response = runner.calculate()

        assert len(response.results) >= 0

    def test_empty_results(self):
        runner = RecordingsQueryRunner(query=RecordingsQuery(), team=self.team)
        response = runner.calculate()

        assert response.results == []
        assert response.has_next is False
