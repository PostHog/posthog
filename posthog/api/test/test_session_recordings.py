import json
from datetime import timedelta

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.helpers.session_recording import compress_to_string
from posthog.models import Person, SessionRecordingEvent
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team import Team
from posthog.queries.sessions.session_recording import RECORDINGS_NUM_SNAPSHOTS_LIMIT
from posthog.test.base import APIBaseTest


def factory_test_session_recordings_api(session_recording_event_factory):
    class TestSessionRecordings(APIBaseTest):
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

        def create_chunked_snapshot(
            self, distinct_id, session_id, timestamp, snapshot_index, chunk_size=5, has_full_snapshot=True
        ):
            session_recording_event_factory(
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

        def test_get_session_recordings(self):
            p = Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            base_time = now() - relativedelta(days=1)
            self.create_snapshot("user", "1", base_time)
            self.create_snapshot("user", "1", base_time + relativedelta(seconds=10))
            self.create_snapshot("user2", "2", base_time + relativedelta(seconds=20))
            self.create_snapshot("user", "1", base_time + relativedelta(seconds=30))

            response = self.client.get("/api/projects/@current/session_recordings")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 2)
            first_session = response_data["results"][0]
            second_session = response_data["results"][1]

            self.assertEqual(first_session["id"], "2")
            self.assertEqual(first_session["distinct_id"], "user2")
            self.assertEqual(parse(first_session["start_time"]), (base_time + relativedelta(seconds=20)))
            self.assertEqual(parse(first_session["end_time"]), (base_time + relativedelta(seconds=20)))
            self.assertEqual(first_session["recording_duration"], "0.0")
            self.assertEqual(first_session["viewed"], False)
            self.assertEqual(first_session["person"]["is_identified"], False)

            self.assertEqual(second_session["id"], "1")
            self.assertEqual(second_session["distinct_id"], "user")
            self.assertEqual(parse(second_session["start_time"]), (base_time))
            self.assertEqual(parse(second_session["end_time"]), (base_time + relativedelta(seconds=30)))
            self.assertEqual(second_session["recording_duration"], "30.0")
            self.assertEqual(second_session["viewed"], False)
            self.assertEqual(second_session["person"]["id"], p.pk)

        def test_session_recordings_dont_leak_teams(self):
            another_team = Team.objects.create(organization=self.organization)

            self.create_snapshot("user", "1", now() - relativedelta(days=1), team_id=another_team.pk)
            self.create_snapshot("user", "2", now() - relativedelta(days=1))

            response = self.client.get("/api/projects/@current/session_recordings")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 1)
            self.assertEqual(response_data["results"][0]["id"], "2")

        def test_session_recording_for_user_with_multiple_distinct_ids(self):
            base_time = now() - timedelta(days=1)
            p = Person.objects.create(
                team=self.team,
                distinct_ids=["d1", "d2"],
                properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            self.create_snapshot("d1", "1", base_time)
            self.create_snapshot("d2", "2", base_time + relativedelta(seconds=30))
            response = self.client.get("/api/projects/@current/session_recordings")
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 2)
            self.assertEqual(response_data["results"][0]["person"]["id"], p.pk)
            self.assertEqual(response_data["results"][1]["person"]["id"], p.pk)

        def test_viewed_state_of_session_recording(self):
            base_time = now() - timedelta(days=1)
            SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="1")
            self.create_snapshot("u1", "1", base_time)
            self.create_snapshot("u1", "2", base_time + relativedelta(seconds=30))
            response = self.client.get("/api/projects/@current/session_recordings")
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 2)
            self.assertEqual(response_data["results"][0]["id"], "2")
            self.assertEqual(response_data["results"][0]["viewed"], False)
            self.assertEqual(response_data["results"][1]["id"], "1")
            self.assertEqual(response_data["results"][1]["viewed"], True)

        def test_get_single_session_recording(self):
            p = Person.objects.create(
                team=self.team, distinct_ids=["d1"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            session_recording_id = "session_1"
            base_time = now() - relativedelta(days=1)
            self.create_snapshot("d1", session_recording_id, base_time)
            self.create_snapshot("d1", session_recording_id, base_time + relativedelta(seconds=30))
            response = self.client.get(f"/api/projects/@current/session_recordings/{session_recording_id}")
            response_data = response.json()
            self.assertEqual(
                response_data["result"]["snapshots"][0], {"timestamp": base_time.timestamp() * 1000, "type": 2}
            )
            self.assertEqual(
                response_data["result"]["snapshots"][1],
                {"timestamp": (base_time + relativedelta(seconds=30)).timestamp() * 1000, "type": 2},
            )
            self.assertEqual(response_data["result"]["person"]["id"], p.pk)
            self.assertEqual(parse(response_data["result"]["start_time"]), base_time)

        def test_get_max_limit_of_snapshots(self):
            base_time = now()
            num_snapshots = 1000

            for s in range(num_snapshots):
                self.create_snapshot("user", "1", base_time)

            response = self.client.get("/api/projects/@current/session_recordings/1")
            response_data = response.json()
            self.assertEqual(len(response_data["result"]["snapshots"]), num_snapshots)

        def test_get_single_chunked_session_recording(self):
            p = Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            chunked_session_id = "chunk_id"
            chunk_size = 5
            expected_num_requests = 1
            num_snapshots = 1000
            num_chunks = int(num_snapshots / chunk_size) * expected_num_requests

            with freeze_time("2020-09-13T12:26:40.000Z"):
                start_time = now()
                for s in range(num_chunks):
                    self.create_chunked_snapshot(
                        "user", chunked_session_id, start_time + relativedelta(seconds=s), s, chunk_size
                    )

                next_url = f"/api/projects/@current/session_recordings/{chunked_session_id}"

                for i in range(expected_num_requests):
                    response = self.client.get(next_url)
                    response_data = response.json()

                    self.assertEqual(len(response_data["result"]["snapshots"]), num_snapshots)
                    self.assertEqual(response_data["result"]["duration"], (num_chunks - 1) * 1000)

                    if i == expected_num_requests - 1:
                        self.assertIsNone(response_data["result"]["next"])
                    else:
                        self.assertIsNotNone(response_data["result"]["next"])
                        self.assertIn("timestamp", response_data["result"]["snapshots"][0])
                        self.assertIn("type", response_data["result"]["snapshots"][0])
                        self.assertEqual(response_data["result"]["person"]["id"], p.pk)

                    next_url = response_data["result"]["next"]

        def test_get_max_limit_of_chunked_snapshots(self):
            chunked_session_id = "chunk_2"
            base_time = now()
            chunk_size = 5
            num_snapshots = 1000
            num_chunks = int(num_snapshots / chunk_size)

            for s in range(num_chunks):
                self.create_chunked_snapshot(
                    "user", chunked_session_id, base_time + relativedelta(seconds=s), s, chunk_size
                )

            response = self.client.get(f"/api/projects/@current/session_recordings/{chunked_session_id}")
            response_data = response.json()
            self.assertEqual(len(response_data["result"]["snapshots"]), num_snapshots)

        def test_single_session_recording_doesnt_leak_teams(self):
            another_team = Team.objects.create(organization=self.organization)
            self.create_snapshot("user", "id_no_team_leaking", now() - relativedelta(days=1), team_id=another_team.pk)
            response = self.client.get("/api/projects/@current/session_recordings/id_no_team_leaking")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_session_recording_with_no_person(self):
            self.create_snapshot("d1", "id_no_person", now() - relativedelta(days=1))
            response = self.client.get("/api/projects/@current/session_recordings/id_no_person")
            response_data = response.json()
            self.assertEqual(response_data["result"]["person"], None)

        def test_session_recording_doesnt_exist(self):
            response = self.client.get("/api/projects/@current/session_recordings/non_existent_id")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_setting_viewed_state_of_session_recording(self):
            self.create_snapshot("u1", "1", now() - relativedelta(days=1))
            response = self.client.get("/api/projects/@current/session_recordings")
            response_data = response.json()
            # Make sure it starts not viewed
            self.assertEqual(response_data["results"][0]["viewed"], False)

            response = self.client.get("/api/projects/@current/session_recordings/1")
            response = self.client.get("/api/projects/@current/session_recordings")
            response_data = response.json()
            # Make sure it remains not viewed
            self.assertEqual(response_data["results"][0]["viewed"], False)

            response = self.client.get("/api/projects/@current/session_recordings/1?save_view=True")
            response = self.client.get("/api/projects/@current/session_recordings")
            response_data = response.json()
            # Make sure the query param sets it to viewed
            self.assertEqual(response_data["results"][0]["viewed"], True)

    return TestSessionRecordings


class TestSessionRecordingsAPI(factory_test_session_recordings_api(SessionRecordingEvent.objects.create)):  # type: ignore
    pass
