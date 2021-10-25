from datetime import timedelta
from typing import Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from dateutil.relativedelta import relativedelta
from django.http import HttpRequest
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework.request import Request

from posthog.helpers.session_recording import compress_and_chunk_snapshots
from posthog.models import Filter
from posthog.models.session_recording_event import SessionRecordingEvent
from posthog.models.team import Team
from posthog.queries.session_recordings.session_recording import DEFAULT_RECORDING_CHUNK_LIMIT, SessionRecording
from posthog.test.base import BaseTest


def factory_session_recording_test(session_recording: SessionRecording, session_recording_event_factory):
    def create_recording_request_and_filter(session_recording_id, limit=None, offset=None) -> Tuple[Request, Filter]:
        params = {}
        if limit:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        build_req = HttpRequest()
        build_req.META = {"HTTP_HOST": "www.testserver"}

        req = Request(
            build_req, f"/api/event/session_recording?session_recording_id={session_recording_id}{urlencode(params)}"
        )
        return (req, Filter(request=req, data=params))

    class TestSessionRecording(BaseTest):
        maxDiff = None

        def test_get_snapshots(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                self.create_snapshot("user", "1", now())
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                req, filt = create_recording_request_and_filter("1")
                recording = session_recording(
                    team=self.team, session_recording_id="1", request=req, filter=filt
                ).get_snapshots()
                self.assertEqual(
                    recording["snapshots"],
                    [
                        {"timestamp": 1_600_000_000_000, "type": 2},
                        {"timestamp": 1_600_000_010_000, "type": 2},
                        {"timestamp": 1_600_000_030_000, "type": 2},
                    ],
                )
                self.assertEqual(recording["next"], None)

        def test_get_snapshots_does_not_leak_teams(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                another_team = Team.objects.create(organization=self.organization)
                self.create_snapshot("user1", "1", now() + relativedelta(seconds=10), team_id=another_team.pk)
                self.create_snapshot("user2", "1", now())

                req, filt = create_recording_request_and_filter("1")
                recording = session_recording(
                    team=self.team, session_recording_id="1", request=req, filter=filt
                ).get_snapshots()
                self.assertEqual(
                    recording["snapshots"], [{"timestamp": 1_600_000_000_000, "type": 2},],
                )

        def test_get_snapshots_with_no_such_session(self):
            req, filt = create_recording_request_and_filter("xxx")
            recording = session_recording(
                team=self.team, session_recording_id="xxx", request=req, filter=filt
            ).get_snapshots()
            self.assertEqual(recording, {"snapshots": [], "next": None})

        def test_get_chunked_snapshots(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                chunked_session_id = "7"
                snapshots_per_chunk = 2
                for _ in range(30):
                    self.create_chunked_snapshots(snapshots_per_chunk, "user", chunked_session_id, now())

                req, filt = create_recording_request_and_filter(chunked_session_id)
                recording = session_recording(
                    team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                ).get_snapshots()
                self.assertEqual(len(recording["snapshots"]), DEFAULT_RECORDING_CHUNK_LIMIT * snapshots_per_chunk)
                self.assertIsNotNone(recording["next"])
                parsed_params = parse_qs(urlparse(recording["next"]).query)
                self.assertEqual(int(parsed_params["offset"][0]), DEFAULT_RECORDING_CHUNK_LIMIT)
                self.assertEqual(int(parsed_params["limit"][0]), DEFAULT_RECORDING_CHUNK_LIMIT)

        def test_get_chunked_snapshots_with_specific_limit_and_offset(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                chunked_session_id = "7"
                chunk_limit = 10
                chunk_offset = 5
                snapshots_per_chunk = 2
                for index in range(16):
                    self.create_chunked_snapshots(
                        snapshots_per_chunk, "user", chunked_session_id, now() + relativedelta(minutes=index)
                    )

                req, filt = create_recording_request_and_filter(chunked_session_id, chunk_limit, chunk_offset)
                recording = session_recording(
                    team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                ).get_snapshots()
                self.assertEqual(len(recording["snapshots"]), chunk_limit * snapshots_per_chunk)
                self.assertEqual(recording["snapshots"][0]["timestamp"], 1_600_000_300_000)
                self.assertIsNotNone(recording["next"])
                parsed_params = parse_qs(urlparse(recording["next"]).query)
                self.assertEqual(int(parsed_params["offset"][0]), chunk_limit + chunk_offset)
                self.assertEqual(int(parsed_params["limit"][0]), chunk_limit)

        def test_get_metadata(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                self.create_snapshot("user", "1", now())
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                req, filt = create_recording_request_and_filter("1")
                recording = session_recording(
                    team=self.team, session_recording_id="1", request=req, filter=filt
                ).get_metadata()
                self.assertEqual(
                    recording,
                    {
                        "distinct_id": "user",
                        "session_id": "1",
                        "start_time": now(),
                        "end_time": now() + relativedelta(seconds=30),
                        "duration": timedelta(seconds=30),
                    },
                )

        def test_get_metadata_for_non_existant_session_id(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):

                req, filt = create_recording_request_and_filter("99")
                recording = session_recording(
                    team=self.team, session_recording_id="1", request=req, filter=filt
                ).get_metadata()
                self.assertEqual(
                    recording,
                    {"distinct_id": None, "session_id": None, "start_time": None, "end_time": None, "duration": None,},
                )

        def test_get_metadata_does_not_leak_teams(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                another_team = Team.objects.create(organization=self.organization)
                self.create_snapshot("user", "1", now(), team_id=another_team.pk)
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                req, filt = create_recording_request_and_filter("1")
                recording = session_recording(
                    team=self.team, session_recording_id="1", request=req, filter=filt
                ).get_metadata()
                self.assertEqual(recording["start_time"], now() + relativedelta(seconds=10))

        def test_get_metadata_for_chunked_snapshots(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                chunked_session_id = "7"
                for index in range(16):
                    self.create_chunked_snapshots(5, "user", chunked_session_id, now() + relativedelta(minutes=index))
                req, filt = create_recording_request_and_filter("xxx")
                recording = session_recording(
                    team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                ).get_metadata()
                self.assertEqual(
                    recording,
                    {
                        "distinct_id": "user",
                        "session_id": chunked_session_id,
                        "start_time": now(),
                        "end_time": now() + relativedelta(seconds=4, minutes=15),
                        "duration": timedelta(seconds=4, minutes=15),
                    },
                )

        def create_snapshot(self, distinct_id, session_id, timestamp, type=2, team_id=None):
            if team_id == None:
                team_id = self.team.pk
            session_recording_event_factory(
                team_id=team_id,
                distinct_id=distinct_id,
                timestamp=timestamp,
                session_id=session_id,
                snapshot_data={"timestamp": timestamp.timestamp() * 1000, "type": type},
            )

        def create_chunked_snapshots(self, snapshot_count, distinct_id, session_id, timestamp, has_full_snapshot=True):
            snapshot = []
            for index in range(snapshot_count):
                snapshot.append(
                    {
                        "event": "$snapshot",
                        "properties": {
                            "$snapshot_data": {
                                "type": 2 if has_full_snapshot else 3,
                                "data": {
                                    "source": 0,
                                    "texts": [],
                                    "attributes": [],
                                    "removes": [],
                                    "adds": [
                                        {
                                            "parentId": 4,
                                            "nextId": 386,
                                            "node": {
                                                "type": 2,
                                                "tagName": "style",
                                                "attributes": {"data-emotion": "css"},
                                                "childNodes": [],
                                                "id": 729,
                                            },
                                        },
                                    ],
                                },
                                "timestamp": (timestamp + timedelta(seconds=index)).timestamp() * 1000,
                            },
                            "$session_id": session_id,
                            "distinct_id": distinct_id,
                        },
                    }
                )
            chunked_snapshots = compress_and_chunk_snapshots(
                snapshot, chunk_size=15
            )  # Small chunk size makes sure the snapshots are chunked for the test
            for snapshot_chunk in chunked_snapshots:
                session_recording_event_factory(
                    team_id=self.team.pk,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    session_id=session_id,
                    snapshot_data=snapshot_chunk["properties"].get("$snapshot_data"),
                )

    return TestSessionRecording


class DjangoSessionRecordingTest(
    factory_session_recording_test(SessionRecording, SessionRecordingEvent.objects.create)  # type: ignore
):
    pass
