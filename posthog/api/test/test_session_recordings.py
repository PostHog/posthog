from datetime import timedelta

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.helpers.session_recording import Event, compress_and_chunk_snapshots
from posthog.models import Organization, Person, SessionRecordingEvent
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team import Team
from posthog.queries.session_recordings.session_recording import DEFAULT_RECORDING_CHUNK_LIMIT
from posthog.test.base import APIBaseTest


def factory_test_session_recordings_api(session_recording_event_factory):
    class TestSessionRecordings(APIBaseTest):
        def create_snapshot(
            self,
            distinct_id,
            session_id,
            timestamp,
            team_id=None,
            window_id="",
            source=0,
            has_full_snapshot=True,
            type=2,
        ):
            if team_id == None:
                team_id = self.team.pk
            session_recording_event_factory(
                team_id=team_id,
                distinct_id=distinct_id,
                timestamp=timestamp,
                session_id=session_id,
                window_id=window_id,
                snapshot_data={
                    "timestamp": timestamp.timestamp() * 1000,
                    "has_full_snapshot": has_full_snapshot,
                    "type": type,
                    "data": {"source": source},
                },
            )

        def create_chunked_snapshots(
            self, snapshot_count, distinct_id, session_id, timestamp, has_full_snapshot=True, window_id=""
        ):
            snapshot = []
            for index in range(snapshot_count):
                event: Event = {
                    "event": "$snapshot",
                    "properties": {
                        "$snapshot_data": {
                            "has_full_snapshot": has_full_snapshot,
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
                        "$window_id": window_id,
                        "$session_id": session_id,
                        "distinct_id": distinct_id,
                    },
                }
                snapshot.append(event)
            chunked_snapshots = compress_and_chunk_snapshots(
                snapshot, chunk_size=15
            )  # Small chunk size makes sure the snapshots are chunked for the test
            for snapshot_chunk in chunked_snapshots:
                session_recording_event_factory(
                    team_id=self.team.pk,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    session_id=session_id,
                    window_id=window_id,
                    snapshot_data=snapshot_chunk["properties"].get("$snapshot_data"),
                )

        def test_get_session_recordings(self):
            p = Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["user2"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            base_time = now() - relativedelta(days=1)
            self.create_snapshot("user", "1", base_time)
            self.create_snapshot("user", "1", base_time + relativedelta(seconds=10))
            self.create_snapshot("user2", "2", base_time + relativedelta(seconds=20))
            self.create_snapshot("user", "1", base_time + relativedelta(seconds=30))

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
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

            self.assertEqual(second_session["id"], "1")
            self.assertEqual(second_session["distinct_id"], "user")
            self.assertEqual(parse(second_session["start_time"]), (base_time))
            self.assertEqual(parse(second_session["end_time"]), (base_time + relativedelta(seconds=30)))
            self.assertEqual(second_session["recording_duration"], "30.0")
            self.assertEqual(second_session["viewed"], False)
            self.assertEqual(second_session["person"]["id"], p.pk)

        def test_session_recordings_dont_leak_teams(self):
            another_team = Team.objects.create(organization=self.organization)
            Person.objects.create(
                team=another_team,
                distinct_ids=["user"],
                properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )

            self.create_snapshot("user", "1", now() - relativedelta(days=1), team_id=another_team.pk)
            self.create_snapshot("user", "2", now() - relativedelta(days=1))

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
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
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 2)
            self.assertEqual(response_data["results"][0]["person"]["id"], p.pk)
            self.assertEqual(response_data["results"][1]["person"]["id"], p.pk)

        def test_viewed_state_of_session_recording(self):
            Person.objects.create(
                team=self.team, distinct_ids=["u1"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            base_time = now() - timedelta(days=1)
            SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="1")
            self.create_snapshot("u1", "1", base_time)
            self.create_snapshot("u1", "2", base_time + relativedelta(seconds=30))
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 2)
            self.assertEqual(response_data["results"][0]["id"], "2")
            self.assertEqual(response_data["results"][0]["viewed"], False)
            self.assertEqual(response_data["results"][1]["id"], "1")
            self.assertEqual(response_data["results"][1]["viewed"], True)

        def test_setting_viewed_state_of_session_recording(self):
            Person.objects.create(
                team=self.team, distinct_ids=["u1"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            self.create_snapshot("u1", "1", now() - relativedelta(days=1))
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
            response_data = response.json()
            # Make sure it starts not viewed
            self.assertEqual(response_data["results"][0]["viewed"], False)

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1")
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
            response_data = response.json()
            # Make sure it remains not viewed
            self.assertEqual(response_data["results"][0]["viewed"], False)

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1?save_view=True")
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
            response_data = response.json()
            # Make sure the query param sets it to viewed
            self.assertEqual(response_data["results"][0]["viewed"], True)

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1")
            response_data = response.json()
            # In the metadata response too
            self.assertEqual(response_data["result"]["session_recording"]["viewed"], True)

        def test_get_single_session_recording_metadata(self):
            p = Person.objects.create(
                team=self.team, distinct_ids=["d1"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            session_recording_id = "session_1"
            base_time = now() - relativedelta(days=1)
            self.create_snapshot("d1", session_recording_id, base_time)
            self.create_snapshot("d1", session_recording_id, base_time + relativedelta(seconds=30))
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_recording_id}")
            response_data = response.json()
            self.assertEqual(response_data["result"]["person"]["id"], p.pk)
            self.assertEqual(parse(response_data["result"]["session_recording"]["start_time"]), base_time)
            self.assertEqual(
                parse(response_data["result"]["session_recording"]["end_time"]), base_time + relativedelta(seconds=30)
            )
            self.assertEqual(response_data["result"]["session_recording"]["recording_duration"], "30.0")
            self.assertEqual(response_data["result"]["session_recording"]["viewed"], False)
            self.assertEqual(response_data["result"]["session_recording"]["distinct_id"], "d1")

        def test_get_single_session_recording_metadata_with_active_segments(self):
            p = Person.objects.create(
                team=self.team, distinct_ids=["d1"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            session_recording_id = "session_1"
            base_time = now() - relativedelta(days=1)
            self.create_snapshot(
                "d1", session_recording_id, base_time, window_id="1", has_full_snapshot=False, source=3, type=3
            )
            self.create_snapshot(
                "d1",
                session_recording_id,
                base_time + relativedelta(seconds=30),
                window_id="1",
                has_full_snapshot=False,
                type=3,
                source=3,
            )
            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recordings/{session_recording_id}?include_active_segments=true"
            )
            response_data = response.json()
            self.assertEqual(response_data["result"]["person"]["id"], p.pk)
            self.assertEqual(parse(response_data["result"]["session_recording"]["start_time"]), base_time)
            self.assertEqual(
                parse(response_data["result"]["session_recording"]["end_time"]), base_time + relativedelta(seconds=30)
            )
            self.assertEqual(response_data["result"]["session_recording"]["recording_duration"], "30.0")
            self.assertEqual(response_data["result"]["session_recording"]["viewed"], False)
            self.assertEqual(response_data["result"]["session_recording"]["distinct_id"], "d1")
            self.assertEqual(response_data["result"]["session_recording"]["distinct_id"], "d1")
            self.assertEqual(
                parse(
                    response_data["result"]["session_recording"]["active_segments_by_window_id"]["1"][0]["start_time"]
                ),
                base_time,
            )
            self.assertEqual(
                parse(response_data["result"]["session_recording"]["active_segments_by_window_id"]["1"][0]["end_time"]),
                base_time + relativedelta(seconds=30),
            )

        def test_get_default_limit_of_chunks(self):
            base_time = now()
            num_snapshots = DEFAULT_RECORDING_CHUNK_LIMIT + 10

            for _ in range(num_snapshots):
                self.create_snapshot("user", "1", base_time)

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1/snapshots")
            response_data = response.json()
            self.assertEqual(len(response_data["result"]["snapshots"]), DEFAULT_RECORDING_CHUNK_LIMIT)

        def test_get_snapshots_for_chunked_session_recording(self):
            chunked_session_id = "chunk_id"
            expected_num_requests = 3
            num_chunks = 60
            snapshots_per_chunk = 2

            with freeze_time("2020-09-13T12:26:40.000Z"):
                start_time = now()
                for s in range(num_chunks):
                    self.create_chunked_snapshots(
                        snapshots_per_chunk, "user", chunked_session_id, start_time + relativedelta(minutes=s),
                    )

                next_url = f"/api/projects/{self.team.id}/session_recordings/{chunked_session_id}/snapshots"

                for i in range(expected_num_requests):
                    response = self.client.get(next_url)
                    response_data = response.json()

                    self.assertEqual(
                        len(response_data["result"]["snapshots"]), snapshots_per_chunk * DEFAULT_RECORDING_CHUNK_LIMIT
                    )
                    if i == expected_num_requests - 1:
                        self.assertIsNone(response_data["result"]["next"])
                    else:
                        self.assertIsNotNone(response_data["result"]["next"])

                    next_url = response_data["result"]["next"]

        def test_get_metadata_for_chunked_session_recording(self):

            with freeze_time("2020-09-13T12:26:40.000Z"):
                p = Person.objects.create(
                    team=self.team, distinct_ids=["d1"], properties={"$some_prop": "something", "email": "bob@bob.com"},
                )
                chunked_session_id = "chunk_id"
                num_chunks = 60
                snapshots_per_chunk = 2
                for index in range(num_chunks):
                    self.create_chunked_snapshots(
                        snapshots_per_chunk, "d1", chunked_session_id, now() + relativedelta(minutes=index),
                    )
                response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{chunked_session_id}")
                response_data = response.json()
                self.assertEqual(response_data["result"]["person"]["id"], p.pk)
                self.assertEqual(parse(response_data["result"]["session_recording"]["start_time"]), now())
                self.assertEqual(
                    parse(response_data["result"]["session_recording"]["end_time"]),
                    now() + relativedelta(minutes=num_chunks - 1, seconds=snapshots_per_chunk - 1),
                )
                self.assertEqual(
                    response_data["result"]["session_recording"]["recording_duration"],
                    str(timedelta(seconds=snapshots_per_chunk - 1, minutes=num_chunks - 1).total_seconds()),
                )
                self.assertEqual(response_data["result"]["session_recording"]["viewed"], False)
                self.assertEqual(response_data["result"]["session_recording"]["distinct_id"], "d1")

        def test_single_session_recording_doesnt_leak_teams(self):
            another_team = Team.objects.create(organization=self.organization)
            self.create_snapshot("user", "id_no_team_leaking", now() - relativedelta(days=1), team_id=another_team.pk)
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/id_no_team_leaking")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/id_no_team_leaking/snapshots")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_session_recording_with_no_person(self):
            self.create_snapshot("d1", "id_no_person", now() - relativedelta(days=1))
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/id_no_person")
            response_data = response.json()
            self.assertEqual(response_data["result"]["person"], {"properties": None})

        def test_session_recording_doesnt_exist(self):
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/non_existent_id")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/non_existent_id/snapshots")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_request_to_another_teams_endpoint_returns_401(self):
            org = Organization.objects.create(name="Separate Org")
            another_team = Team.objects.create(organization=org)
            self.create_snapshot("user", "id_no_team_leaking", now() - relativedelta(days=1), team_id=another_team.pk)
            response = self.client.get(f"/api/projects/{another_team.pk}/session_recordings/id_no_team_leaking")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    return TestSessionRecordings


class TestSessionRecordingsAPI(factory_test_session_recordings_api(SessionRecordingEvent.objects.create)):  # type: ignore
    pass
