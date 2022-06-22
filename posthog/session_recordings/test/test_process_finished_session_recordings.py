import json
from datetime import datetime, timedelta
from unittest.mock import ANY, patch

from dateutil.parser import isoparse
from freezegun import freeze_time

from posthog.client import sync_execute
from posthog.conftest import create_clickhouse_tables
from posthog.session_recordings.process_finished_session_recordings import (
    get_session_recordings_for_oldest_partition,
    process_finished_session_recording,
)
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.test.base import BaseTest

fixed_now = isoparse("2021-08-25T22:09:14.252Z")
seven_days_ago = fixed_now - timedelta(days=7)
four_days_ago = fixed_now - timedelta(days=4)
three_days_ago = fixed_now - timedelta(days=3)
two_days_ago = fixed_now - timedelta(days=2)


def _create_snapshot(session_id: str, timestamp: datetime, team_id: int):
    return create_snapshot(session_id=session_id, window_id="1", team_id=team_id, timestamp=timestamp)


class TestProcessFinishedSessionRecordings(BaseTest):
    """
    <-T0----T1----T2----T3----T4----T5---....
        <-S1--->
                <------------S2--->
                            <-------S3--->
    S1 - not processed because it is in the last three days
    S2 - not processed because it has events within the last 48 hours
    S3 -  processed

    in this example T5 is the most recent partition that can be processed
    """

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

    # need to test that the last three days are not touched
    # need to test that previously migrated recordings are not re-processed
    # need to test that it processes the oldest unprocessed partition

    def test_loads_recordings_from_oldest_partition(self) -> None:
        with freeze_time(fixed_now):
            # session A crosses two partitions and is old enough to process
            _create_snapshot(session_id="a", timestamp=seven_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=seven_days_ago + timedelta(minutes=1), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=four_days_ago + timedelta(minutes=2), team_id=self.team.id)

            # session B is on a single partition and is old enough to process
            _create_snapshot(session_id="b", timestamp=seven_days_ago + timedelta(minutes=2), team_id=self.team.id)
            _create_snapshot(session_id="b", timestamp=seven_days_ago + timedelta(minutes=3), team_id=self.team.id)

            # session C is not old enough to process
            _create_snapshot(session_id="c", timestamp=three_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="c", timestamp=two_days_ago, team_id=self.team.id)

        # don't run within the fixed now... object storage won't write when clock appears skewed
        processed_sessions = get_session_recordings_for_oldest_partition()

        partition = seven_days_ago.strftime("%Y%m%d")
        self.assertEqual(
            sorted(processed_sessions, key=lambda x: x[0]),
            [("a", self.team.id, partition), ("b", self.team.id, partition)],
        )

    @patch("statshog.defaults.django.statsd.incr")
    def test_ignores_empty_session(self, statsd_incr) -> None:
        assert not process_finished_session_recording("a", self.team.id, "20220401")
        self._assert_statsd_incr(statsd_incr, "session_recordings.process_finished_session_recordings.skipping_empty")

    @patch("statshog.defaults.django.statsd.incr")
    def test_ignores_recordings_active_in_last_forty_eight_hours(self, statsd_incr) -> None:
        with freeze_time(fixed_now):
            _create_snapshot(session_id="a", timestamp=seven_days_ago, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=seven_days_ago + timedelta(minutes=1), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=four_days_ago + timedelta(minutes=2), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=three_days_ago + timedelta(minutes=3), team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=two_days_ago + timedelta(minutes=4), team_id=self.team.id)
            processing_result = process_finished_session_recording("a", self.team.id, "20220401")

        assert not processing_result
        self._assert_statsd_incr(
            statsd_incr, "session_recordings.process_finished_session_recordings.skipping_recently_active"
        )

    @patch("ee.kafka_client.client._KafkaProducer.produce")
    @patch("posthog.session_recordings.process_finished_session_recordings.object_storage.write")
    @patch("statshog.defaults.django.statsd.incr")
    def test_finished_recording_is_written_to_sinks(self, statsd_incr, storage_write, kafka_producer) -> None:
        with freeze_time(fixed_now):
            first = seven_days_ago
            second = seven_days_ago + timedelta(minutes=1)
            third = four_days_ago + timedelta(minutes=2)

            _create_snapshot(session_id="a", timestamp=first, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=second, team_id=self.team.id)
            _create_snapshot(session_id="a", timestamp=third, team_id=self.team.id)

            processing_result = process_finished_session_recording("a", self.team.id, "20220401")

        assert processing_result is True
        self._assert_statsd_incr(statsd_incr, "session_recordings.process_finished_session_recordings.succeeded")

        expected_storage_location = f"session_recordings/20220401/{self.team.id}/a/1"
        expected_snapshot_data = [
            {"data": {"source": 0}, "timestamp": ts, "has_full_snapshot": True, "type": 2}
            for ts in [first.timestamp() * 1000, second.timestamp() * 1000, third.timestamp() * 1000]
        ]
        expected_contents = json.dumps({"1": expected_snapshot_data})
        storage_write.assert_called_with(expected_storage_location, expected_contents)

        kafka_producer.assert_called_with(
            topic="clickhouse_session_recordings_test",
            data={
                "session_id": "a",
                "team_id": self.team.id,
                "distinct_id": ANY,
                "session_start": "2021-08-18T22:09:14.252000+00:00",
                "session_end": "2021-08-21T22:11:14.252000+00:00",
                "duration": 259320.0,
                "segments": [
                    {
                        "start_time": "2021-08-18T22:09:14.252000+00:00",
                        "end_time": "2021-08-21T22:11:14.252000+00:00",
                        "window_id": "1",
                        "is_active": False,
                    }
                ],
                "start_and_end_times_by_window_id": {
                    "1": {
                        "start_time": "2021-08-18T22:09:14.252000+00:00",
                        "end_time": "2021-08-21T22:11:14.252000+00:00",
                    }
                },
                "snapshot_data_location": {1: f"session_recordings/20220401/{self.team.id}/a/1"},
            },
            key=ANY,
        )

    def _assert_statsd_incr(self, statsd_incr, identifier: str) -> None:
        self.assertEqual(statsd_incr.call_count, 1)
        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], identifier)
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"team_id": self.team.id}})
