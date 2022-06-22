from datetime import datetime, timedelta
from unittest.mock import patch

from dateutil.parser import isoparse
from freezegun import freeze_time

from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.session_recordings.process_finished_session_recordings import (
    get_sessions_for_oldest_partition,
    process_finished_session,
)
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest

fixed_now = isoparse("2021-08-25T22:09:14.252Z")
five_days_ago = fixed_now - timedelta(days=5)
four_days_ago = fixed_now - timedelta(days=4)
three_days_ago = fixed_now - timedelta(days=3)
two_days_ago = fixed_now - timedelta(days=2)


def _create_snapshot(session_id: str, timestamp: datetime, team_id: int):
    return create_snapshot(session_id=session_id, window_id="1", team_id=team_id, timestamp=timestamp)


class TestProcessFinishedSessionRecordings(BaseTest):
    def setUp(self):
        self.recreate_database()
        return super().setUp()

    def tearDown(self):
        self.recreate_database()
        super().tearDown()

    def recreate_database(self):
        sync_execute(f"DROP DATABASE {CLICKHOUSE_DATABASE} SYNC")
        sync_execute(f"CREATE DATABASE {CLICKHOUSE_DATABASE}")
        create_clickhouse_tables(0)

    def test_loads_recordings_from_oldest_partition(self) -> None:
        with freeze_time(fixed_now):
            # session A crosses two partitions and is old enough to process
            _create_snapshot(session_id="a", timestamp=five_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=five_days_ago + timedelta(minutes=1), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=four_days_ago + timedelta(minutes=2), team_id=self.team.id)

            # session B is on a single partition and is old enough to process
            _create_snapshot(session_id="b", timestamp=five_days_ago + timedelta(minutes=2), team_id=self.team.id)
            _create_snapshot(session_id="b", timestamp=five_days_ago + timedelta(minutes=3), team_id=self.team.id)

            # session C is not old enough to process
            _create_snapshot(session_id="c", timestamp=three_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="c", timestamp=two_days_ago, team_id=self.team.id)

        # don't run within the fixed now... object storage won't write when clock appears skewed
        processed_sessions = get_sessions_for_oldest_partition()

        partition = five_days_ago.strftime("%Y%m%d")
        self.assertEqual(
            sorted(processed_sessions, key=lambda x: x[0]),
            [("a", self.team.id, partition), ("b", self.team.id, partition)],
        )

    # write to object storage
    # write to kafka - mocked
    # write to table through kafka - integrated
    @patch("statshog.defaults.django.statsd.incr")
    def test_ignores_empty_session(self, statsd_incr) -> None:
        assert not process_finished_session("a", self.team.id, "20220401")
        self._assert_statsd_incr(statsd_incr, "session_recordings.process_finished_session_recordings.skipping_empty")

    @patch("statshog.defaults.django.statsd.incr")
    def test_ignores_recordings_active_in_last_forty_eight_hours(self, statsd_incr) -> None:
        with freeze_time(fixed_now):
            _create_snapshot(session_id="a", timestamp=five_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=five_days_ago + timedelta(minutes=1), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=four_days_ago + timedelta(minutes=2), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=three_days_ago + timedelta(minutes=3), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=two_days_ago + timedelta(minutes=4), team_id=self.team.id)
            processing_result = process_finished_session("a", self.team.id, "20220401")

        assert not processing_result
        self._assert_statsd_incr(
            statsd_incr, "session_recordings.process_finished_session_recordings.skipping_recently_active"
        )

    @patch("posthog.session_recordings.process_finished_session_recordings.object_storage.write")
    @patch("statshog.defaults.django.statsd.incr")
    def test_finished_recording_is_written_to_object_storage(self, statsd_incr, storage_write) -> None:
        with freeze_time(fixed_now):
            _create_snapshot(session_id="a", timestamp=five_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=five_days_ago + timedelta(minutes=1), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=four_days_ago + timedelta(minutes=2), team_id=self.team.id)

            processing_result = process_finished_session("a", self.team.id, "20220401")

        assert processing_result is True
        self._assert_statsd_incr(statsd_incr, "session_recordings.process_finished_session_recordings.succeeded")

    def _assert_statsd_incr(self, statsd_incr, identifier: str) -> None:
        self.assertEqual(statsd_incr.call_count, 1)
        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], identifier)
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"team_id": self.team.id}})
