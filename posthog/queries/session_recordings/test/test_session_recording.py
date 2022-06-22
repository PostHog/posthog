import math
from typing import Tuple
from urllib.parse import urlencode

from dateutil.relativedelta import relativedelta
from django.http import HttpRequest
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework.request import Request

from posthog.helpers.session_recording import ACTIVITY_THRESHOLD_SECONDS, DecompressedRecordingData, RecordingSegment
from posthog.models import Filter
from posthog.models.team import Team
from posthog.queries.session_recordings.session_recording import RecordingMetadata, SessionRecording
from posthog.session_recordings.test.test_factory import create_chunked_snapshots, create_snapshot
from posthog.test.base import BaseTest


def factory_session_recording_test(session_recording: SessionRecording):
    def create_recording_request_and_filter(session_recording_id, limit=None, offset=None) -> Tuple[Request, Filter]:
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
        return req, Filter(request=req, data=params)

    class TestSessionRecording(BaseTest):
        maxDiff = None

        def test_get_snapshots(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                create_snapshot(
                    has_full_snapshot=False, distinct_id="user", session_id="1", timestamp=now(), team_id=self.team.id
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user",
                    session_id="1",
                    timestamp=now() + relativedelta(seconds=10),
                    team_id=self.team.id,
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user2",
                    session_id="2",
                    timestamp=now() + relativedelta(seconds=20),
                    team_id=self.team.id,
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user",
                    session_id="1",
                    timestamp=now() + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                req, filter = create_recording_request_and_filter("1")
                recording: DecompressedRecordingData = session_recording(  # type: ignore
                    team_id=self.team.id, session_recording_id="1"
                ).get_snapshots(filter.limit, filter.offset)

                self.assertEqual(
                    recording.snapshot_data_by_window_id,
                    {
                        "": [
                            {
                                "timestamp": 1600000000000.0,
                                "type": 2,
                                "data": {"source": 0},
                                "has_full_snapshot": False,
                            },
                            {
                                "timestamp": 1600000010000.0,
                                "type": 2,
                                "data": {"source": 0},
                                "has_full_snapshot": False,
                            },
                            {
                                "timestamp": 1600000030000.0,
                                "type": 2,
                                "data": {"source": 0},
                                "has_full_snapshot": False,
                            },
                        ]
                    },
                )
                self.assertEqual(recording.has_next, False)

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
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user2",
                    session_id="1",
                    timestamp=now(),
                    team_id=self.team.id,
                    data={"source": 0},
                )

                req, filter = create_recording_request_and_filter("1")
                recording: DecompressedRecordingData = session_recording(  # type: ignore
                    team_id=self.team.id, session_recording_id="1"
                ).get_snapshots(filter.limit, filter.offset)

                self.assertEqual(
                    recording.snapshot_data_by_window_id,
                    {
                        "": [
                            {
                                "data": {"source": 0},
                                "timestamp": 1600000000000.0,
                                "has_full_snapshot": False,
                                "type": 2,
                            }
                        ]
                    },
                )

        def test_get_snapshots_with_no_such_session(self):
            req, filter = create_recording_request_and_filter("xxx")
            recording: DecompressedRecordingData = session_recording(  # type: ignore
                team_id=self.team.id, session_recording_id="xxx"
            ).get_snapshots(filter.limit, filter.offset)
            self.assertEqual(recording, DecompressedRecordingData(has_next=False, snapshot_data_by_window_id={}))

        def test_get_chunked_snapshots(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                chunked_session_id = "7"
                snapshots_per_chunk = 2
                chunk_limit = 20
                for _ in range(30):
                    create_chunked_snapshots(
                        snapshot_count=snapshots_per_chunk,
                        distinct_id="user",
                        session_id=chunked_session_id,
                        timestamp=now(),
                        team_id=self.team.id,
                    )

                req, filter = create_recording_request_and_filter(chunked_session_id)
                recording: DecompressedRecordingData = session_recording(  # type: ignore
                    team_id=self.team.id, session_recording_id=chunked_session_id,
                ).get_snapshots(chunk_limit, filter.offset)
                self.assertEqual(len(recording.snapshot_data_by_window_id[""]), chunk_limit * snapshots_per_chunk)
                self.assertTrue(recording.has_next)

        def test_get_chunked_snapshots_with_specific_limit_and_offset(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                chunked_session_id = "7"
                chunk_limit = 10
                chunk_offset = 5
                snapshots_per_chunk = 2
                for index in range(16):
                    create_chunked_snapshots(
                        snapshot_count=snapshots_per_chunk,
                        distinct_id="user",
                        session_id=chunked_session_id,
                        timestamp=now() + relativedelta(minutes=index),
                        team_id=self.team.id,
                    )

                req, filter = create_recording_request_and_filter(chunked_session_id, chunk_limit, chunk_offset)
                recording: DecompressedRecordingData = session_recording(  # type: ignore
                    team_id=self.team.id, session_recording_id=chunked_session_id,
                ).get_snapshots(chunk_limit, filter.offset)

                self.assertEqual(len(recording.snapshot_data_by_window_id[""]), chunk_limit * snapshots_per_chunk)
                self.assertEqual(recording.snapshot_data_by_window_id[""][0]["timestamp"], 1_600_000_300_000)
                self.assertTrue(recording.has_next)

        def test_get_metadata(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                timestamp = now()
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                )
                timestamp += relativedelta(seconds=1)
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=ACTIVITY_THRESHOLD_SECONDS)
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=ACTIVITY_THRESHOLD_SECONDS * 2)
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                )
                timestamp += relativedelta(seconds=1)
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=math.floor(ACTIVITY_THRESHOLD_SECONDS / 2))
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                )
                timestamp += relativedelta(seconds=math.floor(ACTIVITY_THRESHOLD_SECONDS / 2)) - relativedelta(
                    seconds=4
                )
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="1",
                    has_full_snapshot=False,
                    source=3,
                )  # active

                timestamp = now()
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="2",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=ACTIVITY_THRESHOLD_SECONDS * 2)
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="2",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=ACTIVITY_THRESHOLD_SECONDS)
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="2",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=math.floor(ACTIVITY_THRESHOLD_SECONDS / 2))
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="2",
                    has_full_snapshot=False,
                    source=3,
                )  # active
                timestamp += relativedelta(seconds=math.floor(ACTIVITY_THRESHOLD_SECONDS / 2))
                create_chunked_snapshots(
                    team_id=self.team.id,
                    snapshot_count=1,
                    distinct_id="u",
                    session_id="1",
                    timestamp=timestamp,
                    window_id="2",
                )

                req = create_recording_request_and_filter("1")
                recording: RecordingMetadata = session_recording(  # type: ignore
                    team_id=self.team.id, session_recording_id="1"
                ).get_metadata()

                millisecond = relativedelta(microseconds=1000)

                self.assertEqual(
                    recording,
                    RecordingMetadata(
                        distinct_id="u",
                        segments=[
                            RecordingSegment(is_active=True, window_id="2", start_time=now(), end_time=now()),
                            RecordingSegment(
                                is_active=False,
                                window_id="2",
                                start_time=now() + millisecond,
                                end_time=now() + relativedelta(seconds=1) - millisecond,
                            ),
                            RecordingSegment(
                                is_active=True,
                                window_id="1",
                                start_time=now() + relativedelta(seconds=1),
                                end_time=now() + relativedelta(seconds=1 + ACTIVITY_THRESHOLD_SECONDS),
                            ),
                            RecordingSegment(
                                is_active=False,
                                window_id="1",
                                start_time=now() + relativedelta(seconds=1 + ACTIVITY_THRESHOLD_SECONDS) + millisecond,
                                end_time=now() + relativedelta(seconds=2 * ACTIVITY_THRESHOLD_SECONDS) - millisecond,
                            ),
                            RecordingSegment(
                                is_active=True,
                                window_id="2",
                                start_time=now() + relativedelta(seconds=2 * ACTIVITY_THRESHOLD_SECONDS),
                                end_time=now() + relativedelta(seconds=math.floor(3.5 * ACTIVITY_THRESHOLD_SECONDS)),
                            ),
                            RecordingSegment(
                                is_active=True,
                                window_id="1",
                                start_time=now() + relativedelta(seconds=(3 * ACTIVITY_THRESHOLD_SECONDS) + 2),
                                end_time=now() + relativedelta(seconds=(4 * ACTIVITY_THRESHOLD_SECONDS) - 2),
                            ),
                            RecordingSegment(
                                is_active=False,
                                window_id="2",
                                start_time=now()
                                + relativedelta(seconds=(4 * ACTIVITY_THRESHOLD_SECONDS) - 2)
                                + millisecond,
                                end_time=now() + relativedelta(seconds=4 * ACTIVITY_THRESHOLD_SECONDS),
                            ),
                        ],
                        start_and_end_times_by_window_id={
                            "1": {
                                "start_time": now(),
                                "end_time": now() + relativedelta(seconds=ACTIVITY_THRESHOLD_SECONDS * 4 - 2),
                            },
                            "2": {
                                "start_time": now(),
                                "end_time": now() + relativedelta(seconds=ACTIVITY_THRESHOLD_SECONDS * 4),
                            },
                        },
                    ),
                )

        def test_get_metadata_for_non_existant_session_id(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                req, _ = create_recording_request_and_filter("99")
                recording = session_recording(team_id=self.team.id, session_recording_id="1").get_metadata()  # type: ignore
                self.assertEqual(
                    recording, None,
                )

        def test_get_metadata_does_not_leak_teams(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                another_team = Team.objects.create(organization=self.organization)
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user",
                    session_id="1",
                    timestamp=now(),
                    team_id=another_team.pk,
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user",
                    session_id="1",
                    timestamp=now() + relativedelta(seconds=10),
                    team_id=self.team.id,
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user",
                    session_id="1",
                    timestamp=now() + relativedelta(seconds=20),
                    team_id=self.team.id,
                )
                create_snapshot(
                    has_full_snapshot=False,
                    distinct_id="user",
                    session_id="1",
                    timestamp=now() + relativedelta(seconds=30),
                    team_id=self.team.id,
                )

                req, _ = create_recording_request_and_filter("1")
                recording: RecordingMetadata = session_recording(  # type: ignore
                    team_id=self.team.id, session_recording_id="1",
                ).get_metadata()
                self.assertNotEqual(recording.segments[0].start_time, now())

    return TestSessionRecording
