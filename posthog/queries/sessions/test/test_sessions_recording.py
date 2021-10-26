import json
from typing import Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from dateutil.relativedelta import relativedelta
from django.http import HttpRequest
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework.request import Request

from posthog.helpers.session_recording import chunk_string, compress_to_string
from posthog.models import Filter, Person, User
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.session_recording_event import SessionRecordingEvent, SessionRecordingViewed
from posthog.queries.sessions.session_recording import SessionRecording, join_with_session_recordings
from posthog.test.base import BaseTest


def session_recording_test_factory(session_recording, filter_sessions, event_factory):
    def create_recording_request_and_filter(
        team_id, session_recording_id, limit=None, offset=None
    ) -> Tuple[Request, Filter]:
        params = {}
        if limit:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        build_req = HttpRequest()
        build_req.META = {"HTTP_HOST": "www.testserver"}

        req = Request(
            build_req,
            f"/api/projects/{team_id}/session_recordings?session_recording_id={session_recording_id}{urlencode(params)}",
        )
        return (req, Filter(request=req, data=params))

    class TestSessionRecording(BaseTest):
        maxDiff = None

        def test_query_run(self):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"$some_prop": "something"})

                self.create_snapshot("user", "1", now())
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                req, filt = create_recording_request_and_filter(self.team.id, "1")
                session = session_recording(team=self.team, session_recording_id="1", request=req, filter=filt).run()
                self.assertEqual(
                    session["snapshots"],
                    [
                        {"timestamp": 1_600_000_000_000, "type": 2},
                        {"timestamp": 1_600_000_010_000, "type": 2},
                        {"timestamp": 1_600_000_030_000, "type": 2},
                    ],
                )
                self.assertEqual(session["person"]["properties"], {"$some_prop": "something"})
                self.assertEqual(session["start_time"], now())

        def test_query_run_with_no_such_session(self):

            req, filt = create_recording_request_and_filter(self.team.id, "xxx")
            session = session_recording(team=self.team, session_recording_id="xxx", request=req, filter=filt).run()
            self.assertEqual(
                session, {"snapshots": [], "person": None, "start_time": None, "next": None, "duration": 0}
            )

        def _test_filter_sessions(self, filter, expected):
            with freeze_time("2020-09-13T12:26:40.000Z"):
                self.create_snapshot("user", "1", now() + relativedelta(seconds=5))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=33))
                # :TRICKY: same user, different session at the same time
                self.create_snapshot("user", "3", now() + relativedelta(seconds=15))
                self.create_snapshot("user", "3", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "3", now() + relativedelta(seconds=60))
                self.create_chunked_snapshot("user", "4", now() + relativedelta(seconds=999), 0)
                self.create_snapshot("user", "4", now() + relativedelta(seconds=1020), type=1)

                self.create_snapshot("broken-user", "5", now() + relativedelta(seconds=10), type=3)
                self.create_chunked_snapshot(
                    "broken-user", "5", now() + relativedelta(seconds=20), 0, has_full_snapshot=False
                )

                sessions = [
                    {"distinct_id": "user", "start_time": now(), "end_time": now() + relativedelta(seconds=100)},
                    {
                        "distinct_id": "user",
                        "start_time": now() + relativedelta(hours=99),
                        "end_time": now() + relativedelta(hours=100),
                    },
                    {"distinct_id": "user2", "start_time": now(), "end_time": now() + relativedelta(seconds=30)},
                    {"distinct_id": "broken-user", "start_time": now(), "end_time": now() + relativedelta(seconds=100)},
                ]

                results = filter_sessions(self.team, sessions, filter)
                session_recording_results = [r["session_recordings"] for r in results]
                for session_recording_package in session_recording_results:
                    for session_recording in session_recording_package:
                        # TODO: Include start_time and end_time in asserts
                        del session_recording["start_time"]
                        del session_recording["end_time"]
                self.assertEqual([r["session_recordings"] for r in results], expected)

        def test_join_with_session_recordings(self):
            _, team2, user2 = User.objects.bootstrap("Test2", "sessions@posthog.com", None)

            SessionRecordingViewed.objects.create(team=self.team, user_id=self.user.pk, session_id="1")
            SessionRecordingViewed.objects.create(team=team2, user_id=user2.pk, session_id="2")

            self._test_filter_sessions(
                SessionsFilter(data={"user_id": self.user.pk}),
                [
                    [
                        {"id": "1", "recording_duration": 25, "viewed": True},
                        {"id": "3", "recording_duration": 45, "viewed": False},
                    ],
                    [],
                    [{"id": "2", "recording_duration": 13, "viewed": False}],
                    [],
                ],
            )

        def test_filter_sessions_by_recording_duration_gt(self):
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "gt", "value": 15}]}
                ),
                [
                    [
                        {"id": "1", "recording_duration": 25, "viewed": False},
                        {"id": "3", "recording_duration": 45, "viewed": False},
                    ]
                ],
            )

        def test_filter_sessions_by_unseen_recording(self):
            SessionRecordingViewed.objects.create(team=self.team, user_id=self.user.pk, session_id="2")
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "unseen", "value": 1}], "user_id": self.user.pk}
                ),
                [
                    [
                        {"id": "1", "recording_duration": 25, "viewed": False},
                        {"id": "3", "recording_duration": 45, "viewed": False},
                    ]
                ],
            )

        def test_filter_sessions_by_recording_duration_lt(self):
            self._test_filter_sessions(
                SessionsFilter(
                    data={"filters": [{"type": "recording", "key": "duration", "operator": "lt", "value": 30}]}
                ),
                [
                    [{"id": "1", "recording_duration": 25, "viewed": False}],
                    [{"id": "2", "recording_duration": 13, "viewed": False}],
                ],
            )

        def test_query_run_with_no_sessions(self):
            self.assertEqual(filter_sessions(self.team, [], SessionsFilter(data={"offset": 0})), [])

        # Skip #6489
        def _test_query_run_queries_with_default_limit_and_offset(self):
            chunked_session_id = "6"
            num_snapshots = 1000

            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"$some_prop": "something"})

                for s in range(num_snapshots + 1):
                    self.create_chunked_snapshot("user", chunked_session_id, now() + relativedelta(seconds=s), s)

                req, filt = create_recording_request_and_filter(self.team.id, chunked_session_id)
                session = session_recording(
                    team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                ).run()
                self.assertEqual(len(session["snapshots"]), num_snapshots)
                self.assertIsNotNone(session["next"])  # limit is 1 above num_snapshots
                self.assertEqual(session["duration"], num_snapshots * 1000)
                parsed_params = parse_qs(urlparse(session["next"]).query)
                self.assertEqual(int(parsed_params["offset"][0]), num_snapshots)
                self.assertEqual(int(parsed_params["limit"][0]), num_snapshots)

        def test_query_run_queries_with_specific_limit_and_offset(self):
            chunked_session_id = "7"
            limit = 100

            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"$some_prop": "something"})

                for s in range(200):
                    self.create_chunked_snapshot("user", chunked_session_id, now() + relativedelta(seconds=s), s)

                req, filt = create_recording_request_and_filter(self.team.id, chunked_session_id, limit)
                session = session_recording(
                    team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                ).run()
                self.assertEqual(len(session["snapshots"]), limit)
                self.assertEqual(session["duration"], 199 * 1000)
                self.assertIsNotNone(session["next"])  # limit (200) is above defined limit (100)
                parsed_params = parse_qs(urlparse(session["next"]).query)
                self.assertEqual(int(parsed_params["offset"][0]), limit)
                self.assertEqual(int(parsed_params["limit"][0]), limit)

        def test_query_run_sequential_next_urls(self):
            chunked_session_id = "8"
            expected_num_requests = 1
            chunk_size = 5
            num_snapshots = 1000
            num_chunks = int(num_snapshots / chunk_size) * expected_num_requests

            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"$some_prop": "something"})

                start_time = now()
                for s in range(num_chunks):
                    self.create_chunked_snapshot(
                        "user", chunked_session_id, start_time + relativedelta(seconds=s), s, chunk_size
                    )

                # A successful single session recording query will make {num_chunks} requests
                base_req, base_filter = create_recording_request_and_filter(self.team.id, chunked_session_id)
                session = None

                for i in range(expected_num_requests):
                    req = base_req if i == 0 else Request(base_req._request, session["next"])
                    filt = (
                        base_filter
                        if i == 0
                        else Filter(request=req, data={"limit": num_snapshots, "offset": num_snapshots * i,},)
                    )

                    session = session_recording(
                        team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                    ).run()

                    self.assertEqual(len(session["snapshots"]), num_snapshots)
                    self.assertEqual(session["duration"], (num_chunks - 1) * 1000)

                    if i == expected_num_requests - 1:
                        self.assertIsNone(session["next"])
                    else:
                        self.assertIsNotNone(session["next"])
                        parsed_params = parse_qs(urlparse(session["next"]).query)
                        self.assertEqual(int(parsed_params["offset"][0]), num_snapshots * (i + 1))
                        self.assertEqual(int(parsed_params["limit"][0]), num_snapshots)

        def test_query_run_session_with_chunks_with_partial_snapshots(self):
            chunked_session_id = "session_with_partial_chunks"
            num_events = 50
            duration = 100

            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(team=self.team, distinct_ids=["user"], properties={"$some_prop": "something"})
                start_time = now()

                data = [
                    {
                        "timestamp": int(start_time.timestamp() * 1000),
                        "type": 2,
                        "data": dict(map(lambda x: (x, x), "abcdefg")),
                    }
                ] * (num_events // 2) + [
                    {
                        "timestamp": int((start_time + relativedelta(seconds=duration)).timestamp() * 1000),
                        "type": 2,
                        "data": dict(map(lambda x: (x, x), "abcdefg")),
                    }
                ] * (
                    num_events // 2
                )
                compressed_data = compress_to_string(json.dumps(data))
                chunks = chunk_string(compressed_data, len(compressed_data) // 2)

                # Send first chunk with first part of json
                event_factory(
                    team_id=self.team.pk,
                    distinct_id="user",
                    timestamp=start_time,
                    session_id=chunked_session_id,
                    snapshot_data={
                        "chunk_id": "chunky_0",
                        "chunk_index": 0,
                        "chunk_count": 2,
                        "data": chunks[0],
                        "has_full_snapshot": False,
                    },
                )

                # Send second chunk with second and final part of json
                event_factory(
                    team_id=self.team.pk,
                    distinct_id="user",
                    timestamp=start_time + relativedelta(seconds=duration),
                    session_id=chunked_session_id,
                    snapshot_data={
                        "chunk_id": "chunky_0",
                        "chunk_index": 0,
                        "chunk_count": 2,
                        "data": chunks[1],
                        "has_full_snapshot": False,
                    },
                )

                # Do the thing
                req, filt = create_recording_request_and_filter(self.team.id, chunked_session_id)
                session = session_recording(
                    team=self.team, session_recording_id=chunked_session_id, request=req, filter=filt
                ).run()

                # Assert that full data has been received
                self.assertEqual(len(session["snapshots"]), num_events)
                self.assertEqual(session["duration"], duration * 1000)
                self.assertEqual(session["snapshots"], data)

        def create_snapshot(self, distinct_id, session_id, timestamp, type=2):
            event_factory(
                team_id=self.team.pk,
                distinct_id=distinct_id,
                timestamp=timestamp,
                session_id=session_id,
                snapshot_data={"timestamp": timestamp.timestamp() * 1000, "type": type},
            )

        def create_chunked_snapshot(
            self, distinct_id, session_id, timestamp, snapshot_index, chunk_size=5, has_full_snapshot=True
        ):
            event_factory(
                team_id=self.team.pk,
                distinct_id=distinct_id,
                timestamp=timestamp,
                session_id=session_id,
                snapshot_data={
                    "chunk_id": f"chunky_{snapshot_index}",
                    "chunk_index": snapshot_index,
                    "chunk_count": 1,
                    "data": compress_to_string(
                        json.dumps([{"timestamp": timestamp.timestamp() * 1000, "type": 2}] * chunk_size)
                    ),
                    "has_full_snapshot": has_full_snapshot,
                },
            )

    return TestSessionRecording


class DjangoSessionRecordingTest(
    session_recording_test_factory(SessionRecording, join_with_session_recordings, SessionRecordingEvent.objects.create)  # type: ignore
):
    pass
