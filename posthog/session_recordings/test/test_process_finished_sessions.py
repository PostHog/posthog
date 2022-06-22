from datetime import timedelta
from unittest.mock import patch

from dateutil.parser import isoparse
from freezegun import freeze_time

from posthog.session_recordings.process_finished_sessions import (
    get_sessions_for_oldest_partition,
    process_finished_session,
)
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.test.base import BaseTest


class TestProcessFinishedSessions(BaseTest):
    def test_loads_sessions_from_oldest_partition(self) -> None:
        fixed_now = isoparse("2021-08-25T22:09:14.252Z")
        five_days_ago = fixed_now - timedelta(days=5)
        four_days_ago = fixed_now - timedelta(days=4)
        three_days_ago = fixed_now - timedelta(days=3)
        two_days_ago = fixed_now - timedelta(days=2)

        with freeze_time(fixed_now):
            # session A crosses two partitions and is old enough to process

            create_snapshot(session_id="a", window_id="1", timestamp=five_days_ago, team_id=self.team.id)
            create_snapshot(
                session_id="a", window_id="1", timestamp=five_days_ago + timedelta(minutes=1), team_id=self.team.id
            )
            create_snapshot(
                session_id="a", window_id="1", timestamp=four_days_ago + timedelta(minutes=2), team_id=self.team.id
            )

            # session B is on a single partition and is old enough to process
            create_snapshot(
                session_id="b", window_id="1", timestamp=five_days_ago + timedelta(minutes=2), team_id=self.team.id
            )
            create_snapshot(
                session_id="b", window_id="1", timestamp=five_days_ago + timedelta(minutes=3), team_id=self.team.id
            )

            # session C is not old enough to process
            create_snapshot(session_id="c", window_id="1", timestamp=three_days_ago, team_id=self.team.id)
            create_snapshot(session_id="c", window_id="1", timestamp=two_days_ago, team_id=self.team.id)

        # don't run within the fixed now... object storage won't write when clock appears skewed
        processed_sessions = get_sessions_for_oldest_partition()

        partition = five_days_ago.strftime("%Y%m%d")
        self.assertEqual(
            sorted(processed_sessions, key=lambda x: x[0]),
            [("a", self.team.id, partition), ("b", self.team.id, partition)],
        )

    # by type it is possible for metadata or snapshot_data to be None
    # if session was active too recent then ignore it with statsd
    # write to object storage
    # write to kafka - mocked
    # write to table through kafka - integrated
    @patch("statshog.defaults.django.statsd.incr")
    def test_ignores_empty_session(self, statsd_incr) -> None:
        assert not process_finished_session("a", self.team.id, "20220401")
        self._assert_statsd_incr(statsd_incr)

    def _assert_statsd_incr(self, statsd_incr):
        self.assertEqual(statsd_incr.call_count, 1)
        statsd_incr_first_call = statsd_incr.call_args_list[0]
        self.assertEqual(statsd_incr_first_call.args[0], "session_recordings.process_finished_sessions.skipping_empty")
        self.assertEqual(statsd_incr_first_call.kwargs, {"tags": {"team_id": self.team.id}})
