from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from rest_framework import status

from posthog.models import Person, SessionRecordingEvent
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team import Team
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
                snapshot_data={"timestamp": timestamp.timestamp(), "type": type},
            )

        def test_get_session_recordings(self):
            Person.objects.create(
                team=self.team, distinct_ids=["user"], properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            base_time = now()
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
            self.assertEqual(first_session["email"], None)

            self.assertEqual(second_session["id"], "1")
            self.assertEqual(second_session["distinct_id"], "user")
            self.assertEqual(parse(second_session["start_time"]), (base_time))
            self.assertEqual(parse(second_session["end_time"]), (base_time + relativedelta(seconds=30)))
            self.assertEqual(second_session["recording_duration"], "30.0")
            self.assertEqual(second_session["viewed"], False)
            self.assertEqual(second_session["email"], "bob@bob.com")

        def test_session_recordings_dont_leak_teams(self):
            another_team = Team.objects.create(organization=self.organization)

            self.create_snapshot("user", "1", now(), team_id=another_team.pk)
            self.create_snapshot("user", "2", now())

            response = self.client.get("/api/projects/@current/session_recordings")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 1)
            self.assertEqual(response_data["results"][0]["id"], "2")

        def test_session_recording_for_user_with_multiple_distinct_ids(self):
            Person.objects.create(
                team=self.team,
                distinct_ids=["d1", "d2"],
                properties={"$some_prop": "something", "email": "bob@bob.com"},
            )
            self.create_snapshot("d1", "1", now())
            self.create_snapshot("d2", "2", now() + relativedelta(seconds=30))
            response = self.client.get("/api/projects/@current/session_recordings")
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 2)
            self.assertEqual(response_data["results"][0]["email"], "bob@bob.com")
            self.assertEqual(response_data["results"][1]["email"], "bob@bob.com")

        def test_viewed_state_of_session_recording(self):
            SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="1")
            self.create_snapshot("u1", "1", now())
            self.create_snapshot("u1", "2", now() + relativedelta(seconds=30))
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
            base_time = now()
            self.create_snapshot("d1", "1", base_time)
            self.create_snapshot("d1", "1", base_time + relativedelta(seconds=30))
            response = self.client.get("/api/projects/@current/session_recordings/1")
            response_data = response.json()
            self.assertEqual(response_data["result"]["snapshots"][0], {"timestamp": base_time.timestamp(), "type": 2})
            self.assertEqual(
                response_data["result"]["snapshots"][1],
                {"timestamp": (base_time + relativedelta(seconds=30)).timestamp(), "type": 2},
            )
            self.assertEqual(response_data["result"]["person"]["id"], p.pk)
            self.assertEqual(parse(response_data["result"]["start_time"]), base_time)

        def test_single_session_recording_doesnt_leak_teams(self):
            another_team = Team.objects.create(organization=self.organization)
            self.create_snapshot("user", "1", now(), team_id=another_team.pk)
            response = self.client.get("/api/projects/@current/session_recordings/1")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_session_recording_with_no_person(self):
            self.create_snapshot("d1", "1", now())
            response = self.client.get("/api/projects/@current/session_recordings/1")
            response_data = response.json()
            self.assertEqual(response_data["result"]["person"], None)

        def test_session_recording_doesnt_exist(self):
            response = self.client.get("/api/projects/@current/session_recordings/1")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        def test_setting_viewed_state_of_session_recording(self):
            self.create_snapshot("u1", "1", now())
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
