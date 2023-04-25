from datetime import datetime, timedelta, timezone
from unittest.mock import ANY
from urllib.parse import urlencode

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.api.session_recording import DEFAULT_RECORDING_CHUNK_LIMIT
from posthog.models import Organization, Person
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team import Team
from posthog.session_recordings.test.test_factory import create_session_recording_events
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    flush_persons_and_events,
    snapshot_postgres_queries,
)


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        # Create a new team each time to ensure no clashing between tests
        self.team = Team.objects.create(organization=self.organization, name="New Team")

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
        snapshot_data=None,
    ):
        if team_id is None:
            team_id = self.team.pk

        snapshot = {
            "timestamp": timestamp.timestamp() * 1000,
            "has_full_snapshot": has_full_snapshot,
            "type": type,
            "data": {"source": source},
        }

        if snapshot_data:
            snapshot.update(snapshot_data)

        create_session_recording_events(
            team_id=team_id,
            distinct_id=distinct_id,
            timestamp=timestamp,
            session_id=session_id,
            window_id=window_id,
            snapshots=[snapshot],
        )

    def create_chunked_snapshots(
        self, snapshot_count, distinct_id, session_id, timestamp, has_full_snapshot=True, window_id=""
    ):
        snapshots = []
        for index in range(snapshot_count):
            snapshots.append(
                {
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
                            }
                        ],
                    },
                    "timestamp": (timestamp + timedelta(seconds=index)).timestamp() * 1000,
                }
            )

        create_session_recording_events(
            team_id=self.team.pk,
            distinct_id=distinct_id,
            timestamp=timestamp,
            session_id=session_id,
            window_id=window_id,
            snapshots=snapshots,
            chunk_size=15,
        )

    def test_get_session_recordings(self):
        p = Person.objects.create(
            team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        Person.objects.create(
            team=self.team, distinct_ids=["user2"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
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
        self.assertEqual(first_session["recording_duration"], 0)
        self.assertEqual(first_session["viewed"], False)

        self.assertEqual(second_session["id"], "1")
        self.assertEqual(second_session["distinct_id"], "user")
        self.assertEqual(parse(second_session["start_time"]), (base_time))
        self.assertEqual(parse(second_session["end_time"]), (base_time + relativedelta(seconds=30)))
        self.assertEqual(second_session["recording_duration"], 30)
        self.assertEqual(second_session["viewed"], False)
        self.assertEqual(second_session["person"]["id"], p.pk)

    @snapshot_postgres_queries
    def test_listing_recordings_is_not_nplus1_for_persons(self):
        # request once without counting queries to cache an ee.license lookup that makes results vary otherwise
        with freeze_time("2022-06-03T12:00:00.000Z"):
            self.client.get(f"/api/projects/{self.team.id}/session_recordings")

            base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
            num_queries = 9

            self._person_with_snapshots(base_time=base_time, distinct_id="user", session_id="1")
            with self.assertNumQueries(num_queries):
                self.client.get(f"/api/projects/{self.team.id}/session_recordings")

            self._person_with_snapshots(base_time=base_time, distinct_id="user2", session_id="2")
            with self.assertNumQueries(num_queries):
                self.client.get(f"/api/projects/{self.team.id}/session_recordings")

            self._person_with_snapshots(base_time=base_time, distinct_id="user3", session_id="3")
            with self.assertNumQueries(num_queries):
                self.client.get(f"/api/projects/{self.team.id}/session_recordings")

    def _person_with_snapshots(self, base_time: datetime, distinct_id: str = "user", session_id: str = "1") -> None:
        Person.objects.create(
            team=self.team, distinct_ids=[distinct_id], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        self.create_snapshot(distinct_id, session_id, base_time)
        self.create_snapshot(distinct_id, session_id, base_time + relativedelta(seconds=10))
        flush_persons_and_events()

    def test_session_recordings_dont_leak_teams(self):
        another_team = Team.objects.create(organization=self.organization)
        Person.objects.create(
            team=another_team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        Person.objects.create(
            team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )

        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        self.create_snapshot("user", "1", base_time, team_id=another_team.pk)
        self.create_snapshot("user", "2", base_time)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(len(response_data["results"]), 1)
        self.assertEqual(response_data["results"][0]["id"], "2")

    def test_session_recording_for_user_with_multiple_distinct_ids(self):
        base_time = (now() - timedelta(days=1)).replace(microsecond=0)
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
            team=self.team, distinct_ids=["u1"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        base_time = (now() - timedelta(days=1)).replace(microsecond=0)
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
            team=self.team, distinct_ids=["u1"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
        self.create_snapshot("u1", "1", base_time)
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
        self.assertEqual(response_data["viewed"], True)

    def test_get_single_session_recording_metadata(self):
        with freeze_time("2023-01-01T12:00:00.000Z"):
            p = Person.objects.create(
                team=self.team, distinct_ids=["d1"], properties={"$some_prop": "something", "email": "bob@bob.com"}
            )
            session_recording_id = "session_1"
            base_time = (now() - relativedelta(days=1)).replace(microsecond=0)
            self.create_snapshot("d1", session_recording_id, base_time)
            self.create_snapshot("d1", session_recording_id, base_time + relativedelta(seconds=30))

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_recording_id}")
        response_data = response.json()

        assert response_data == {
            "id": "session_1",
            "distinct_id": "d1",
            "viewed": False,
            "pinned_count": 0,
            "recording_duration": 30,
            "start_time": base_time.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": (base_time + relativedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "click_count": 0,
            "keypress_count": 0,
            "start_url": None,
            "matching_events": None,
            "person": {
                "id": p.id,
                "name": "bob@bob.com",
                "distinct_ids": ["d1"],
                "properties": {"email": "bob@bob.com", "$some_prop": "something"},
                "created_at": "2023-01-01T12:00:00Z",
                "uuid": ANY,
            },
            "segments": [
                {
                    "start_time": base_time.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end_time": (base_time + relativedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "window_id": "",
                    "is_active": False,
                }
            ],
            "start_and_end_times_by_window_id": {
                "": {
                    "window_id": "",
                    "start_time": base_time.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end_time": (base_time + relativedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "is_active": False,
                }
            },
            "snapshot_data_by_window_id": None,
            "storage": "clickhouse",
        }

    def test_get_default_limit_of_chunks(self):
        base_time = now()
        num_snapshots = DEFAULT_RECORDING_CHUNK_LIMIT + 10

        for _ in range(num_snapshots):
            self.create_snapshot("user", "1", base_time)

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1/snapshots")
        response_data = response.json()
        self.assertEqual(len(response_data["snapshot_data_by_window_id"][""]), DEFAULT_RECORDING_CHUNK_LIMIT)

    def test_get_snapshots_is_compressed(self):
        base_time = now()
        num_snapshots = 2  # small contents aren't compressed, needs to be enough data to trigger compression

        for _ in range(num_snapshots):
            self.create_snapshot("user", "1", base_time)

        custom_headers = {"HTTP_ACCEPT_ENCODING": "gzip"}
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/1/snapshots",
            data=None,
            follow=False,
            secure=False,
            **custom_headers,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("Content-Encoding", None), "gzip")

    def test_get_snapshots_for_chunked_session_recording(self):
        chunked_session_id = "chunk_id"
        expected_num_requests = 3
        num_chunks = 60
        snapshots_per_chunk = 2

        with freeze_time("2020-09-13T12:26:40.000Z"):
            start_time = now()
            for index, s in enumerate(range(num_chunks)):
                self.create_chunked_snapshots(
                    snapshots_per_chunk,
                    "user",
                    chunked_session_id,
                    start_time + relativedelta(minutes=s),
                    window_id="1" if index % 2 == 0 else "2",
                )

            next_url = f"/api/projects/{self.team.id}/session_recordings/{chunked_session_id}/snapshots"

            for i in range(expected_num_requests):
                response = self.client.get(next_url)
                response_data = response.json()

                self.assertEqual(
                    len(response_data["snapshot_data_by_window_id"]["1"]),
                    snapshots_per_chunk * DEFAULT_RECORDING_CHUNK_LIMIT / 2,
                )
                self.assertEqual(
                    len(response_data["snapshot_data_by_window_id"]["2"]),
                    snapshots_per_chunk * DEFAULT_RECORDING_CHUNK_LIMIT / 2,
                )
                if i == expected_num_requests - 1:
                    self.assertIsNone(response_data["next"])
                else:
                    self.assertIsNotNone(response_data["next"])

                next_url = response_data["next"]

    def test_get_metadata_for_chunked_session_recording(self):

        with freeze_time("2020-09-13T12:26:40.000Z"):
            p = Person.objects.create(
                team=self.team, distinct_ids=["d1"], properties={"$some_prop": "something", "email": "bob@bob.com"}
            )
            chunked_session_id = "chunked_session_id"
            num_chunks = 60
            snapshots_per_chunk = 2
            for index in range(num_chunks):
                self.create_chunked_snapshots(
                    snapshots_per_chunk, "d1", chunked_session_id, now() + relativedelta(minutes=index)
                )
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{chunked_session_id}")
            response_data = response.json()
            self.assertEqual(response_data["person"]["id"], p.pk)
            self.assertEqual(
                response_data["start_and_end_times_by_window_id"],
                {
                    "": {
                        "is_active": False,
                        "window_id": "",
                        "start_time": now().replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end_time": (
                            now() + relativedelta(minutes=num_chunks - 1, seconds=snapshots_per_chunk - 1)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                },
            )
            self.assertEqual(
                response_data["segments"],
                [
                    {
                        "start_time": now().replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end_time": (
                            now() + relativedelta(minutes=num_chunks - 1, seconds=snapshots_per_chunk - 1)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "is_active": False,
                        "window_id": "",
                    }
                ],
            )
            self.assertEqual(response_data["viewed"], False)
            self.assertEqual(response_data["id"], chunked_session_id)

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
        self.assertEqual(response_data["person"], None)

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

    def test_session_ids_filter(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"}
            )
            self.create_snapshot("user", "1", now() - relativedelta(days=1))
            self.create_snapshot("user", "2", now() - relativedelta(days=2))
            self.create_snapshot("user", "3", now() - relativedelta(days=3))

            # Fetch playlist
            params_string = urlencode({"session_ids": '["1", "2", "3"]'})
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings?{params_string}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()

            self.assertEqual(len(response_data["results"]), 3)
            self.assertEqual(response_data["results"][0]["id"], "1")
            self.assertEqual(response_data["results"][1]["id"], "2")
            self.assertEqual(response_data["results"][2]["id"], "3")

    def test_empty_list_session_ids_filter_returns_no_recordings(self):
        with freeze_time("2020-09-13T12:26:40.000Z"):
            Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"}
            )
            self.create_snapshot("user", "1", now() - relativedelta(days=1))
            self.create_snapshot("user", "2", now() - relativedelta(days=2))
            self.create_snapshot("user", "3", now() - relativedelta(days=3))

            # Fetch playlist
            params_string = urlencode({"session_ids": "[]"})
            response = self.client.get(f"/api/projects/{self.team.id}/session_recordings?{params_string}")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()

            self.assertEqual(len(response_data["results"]), 0)

    def test_regression_encoded_emojis_dont_crash(self):

        Person.objects.create(
            team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"}
        )
        with freeze_time("2022-01-01T12:00:00.000Z"):
            self.create_snapshot(
                "user",
                "1",
                now() - relativedelta(days=1),
                snapshot_data={"texts": ["\\ud83d\udc83\\ud83c\\udffb"]},  # This is an invalid encoded emoji
            )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/1/snapshots")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        assert not response_data["next"]
        assert response_data["snapshot_data_by_window_id"] == {
            "": [
                {
                    "texts": ["\\ud83d\udc83\\ud83c\\udffb"],
                    "timestamp": 1640952000000.0,
                    "has_full_snapshot": True,
                    "type": 2,
                    "data": {"source": 0},
                }
            ]
        }

    def test_delete_session_recording(self):
        self.create_snapshot("user", "1", now() - relativedelta(days=1), team_id=self.team.pk)
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()

        assert response_data["success"]

        # Trying to delete same recording again returns 404
        response = self.client.delete(f"/api/projects/{self.team.id}/session_recordings/1")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
