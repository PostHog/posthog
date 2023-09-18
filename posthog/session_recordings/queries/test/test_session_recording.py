from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.http import HttpRequest
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework.request import Request

from posthog.models import Filter
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_events import SessionRecordingEvents
from posthog.session_recordings.session_recording_helpers import (
    DecompressedRecordingData,
)
from posthog.session_recordings.test.test_factory import create_snapshots, create_snapshot
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


def create_recording_filter(session_recording_id, limit=None, offset=None) -> Filter:
    params = {}
    if limit:
        params["limit"] = limit
    if offset:
        params["offset"] = offset
    build_req = HttpRequest()
    build_req.META = {"HTTP_HOST": "www.testserver"}

    req = Request(
        build_req, f"/api/event/session_recording?session_recording_id={session_recording_id}{urlencode(params)}"  # type: ignore
    )
    return Filter(request=req, data=params)


class TestClickhouseSessionRecording(ClickhouseTestMixin, APIBaseTest):

    maxDiff = None

    def test_get_snapshots(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now(),
                team_id=self.team.id,
                use_replay_table=False,
                use_recording_table=True,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now() + relativedelta(seconds=10),
                team_id=self.team.id,
                use_replay_table=False,
                use_recording_table=True,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user2",
                session_id="2",
                timestamp=now() + relativedelta(seconds=20),
                team_id=self.team.id,
                use_replay_table=False,
                use_recording_table=True,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now() + relativedelta(seconds=30),
                team_id=self.team.id,
                use_replay_table=False,
                use_recording_table=True,
            )

            filter = create_recording_filter("1")
            recording: DecompressedRecordingData | None = SessionRecordingEvents(
                team=self.team, session_recording_id="1"
            ).get_snapshots(filter.limit, filter.offset)

            assert recording is not None
            self.assertEqual(
                recording["snapshot_data_by_window_id"],
                {
                    "": [
                        {"timestamp": 1600000000000, "type": 3, "data": {"source": 0}},
                        {"timestamp": 1600000010000, "type": 3, "data": {"source": 0}},
                        {"timestamp": 1600000030000, "type": 3, "data": {"source": 0}},
                    ]
                },
            )
            self.assertEqual(recording["has_next"], False)

    def test_get_snapshots_does_not_leak_teams(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            another_team = Team.objects.create(organization=self.organization)
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user1",
                session_id="1",
                timestamp=now() + relativedelta(seconds=10),
                team_id=another_team.pk,
                data={"source": "other team"},
                use_replay_table=False,
                use_recording_table=True,
            )
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user2",
                session_id="1",
                timestamp=now(),
                team_id=self.team.id,
                data={"source": 0},
                use_replay_table=False,
                use_recording_table=True,
            )

            filter = create_recording_filter("1")
            recording: DecompressedRecordingData | None = SessionRecordingEvents(
                team=self.team, session_recording_id="1"
            ).get_snapshots(filter.limit, filter.offset)

            assert recording is not None
            self.assertEqual(
                recording["snapshot_data_by_window_id"],
                {"": [{"data": {"source": 0}, "timestamp": 1600000000000, "type": 3}]},
            )

    def test_get_snapshots_with_no_such_session(self):
        filter = create_recording_filter("xxx")
        recording: DecompressedRecordingData | None = SessionRecordingEvents(
            team=self.team, session_recording_id="xxx"
        ).get_snapshots(filter.limit, filter.offset)

        assert recording is None

    def test_get_chunked_snapshots(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            chunked_session_id = "7"
            snapshots_per_chunk = 2
            limit = 20
            for _ in range(30):
                create_snapshots(
                    snapshot_count=snapshots_per_chunk,
                    distinct_id="user",
                    session_id=chunked_session_id,
                    timestamp=now(),
                    team_id=self.team.id,
                    use_replay_table=False,
                    use_recording_table=True,
                )

            filter = create_recording_filter(chunked_session_id)
            recording: DecompressedRecordingData | None = SessionRecordingEvents(
                team=self.team, session_recording_id=chunked_session_id
            ).get_snapshots(limit, filter.offset)

            assert recording is not None
            self.assertEqual(len(recording["snapshot_data_by_window_id"][""]), limit * snapshots_per_chunk)
            self.assertTrue(recording["has_next"])

    def test_get_chunked_snapshots_with_specific_limit_and_offset(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            chunked_session_id = "7"
            limit = 10
            offset = 5
            snapshots_per_chunk = 2
            for index in range(16):
                create_snapshots(
                    snapshot_count=snapshots_per_chunk,
                    distinct_id="user",
                    session_id=chunked_session_id,
                    timestamp=now() + relativedelta(minutes=index),
                    team_id=self.team.id,
                    use_replay_table=False,
                    use_recording_table=True,
                )

            filter = create_recording_filter(chunked_session_id, limit, offset)
            recording: DecompressedRecordingData | None = SessionRecordingEvents(
                team=self.team, session_recording_id=chunked_session_id
            ).get_snapshots(limit, filter.offset)

            assert recording is not None
            self.assertEqual(len(recording["snapshot_data_by_window_id"][""]), limit * snapshots_per_chunk)
            self.assertEqual(recording["snapshot_data_by_window_id"][""][0]["timestamp"], 1_600_000_300_000)
            self.assertTrue(recording["has_next"])

    def test_get_snapshots_with_date_filter(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            # This snapshot should be filtered out
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now() - relativedelta(days=2),
                team_id=self.team.id,
                use_replay_table=False,
                use_recording_table=True,
            )
            # This snapshot should appear
            create_snapshot(
                has_full_snapshot=False,
                distinct_id="user",
                session_id="1",
                timestamp=now(),
                team_id=self.team.id,
                use_replay_table=False,
                use_recording_table=True,
            )

            filter = create_recording_filter(
                "1",
            )
            recording: DecompressedRecordingData | None = SessionRecordingEvents(
                team=self.team, session_recording_id="1", recording_start_time=now()
            ).get_snapshots(filter.limit, filter.offset)

            assert recording is not None
            self.assertEqual(len(recording["snapshot_data_by_window_id"][""]), 1)
