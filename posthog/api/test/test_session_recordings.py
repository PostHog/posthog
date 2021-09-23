from unittest.mock import patch

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Person, SessionRecordingEvent
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
            with freeze_time("2020-09-13T12:26:40.000Z"):
                Person.objects.create(
                    team=self.team,
                    distinct_ids=["user"],
                    properties={"$some_prop": "something", "email": "bob@bob.com"},
                )

                self.create_snapshot("user", "1", now())
                self.create_snapshot("user", "1", now() + relativedelta(seconds=10))
                self.create_snapshot("user2", "2", now() + relativedelta(seconds=20))
                self.create_snapshot("user", "1", now() + relativedelta(seconds=30))

                response = self.client.get("/api/projects/@current/session_recordings")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                response_data = response.json()
                self.assertEqual(len(response_data["results"]), 2)
                first_session = response_data["results"][0]
                second_session = response_data["results"][1]

                self.assertEqual(first_session["id"], "2")
                self.assertEqual(first_session["distinct_id"], "user2")
                self.assertEqual(parse(first_session["start_time"]), (now() + relativedelta(seconds=20)))
                self.assertEqual(parse(first_session["end_time"]), (now() + relativedelta(seconds=20)))
                self.assertEqual(first_session["recording_duration"], "0.0")
                self.assertEqual(first_session["viewed"], False)
                self.assertEqual(first_session["email"], None)

                self.assertEqual(second_session["id"], "1")
                self.assertEqual(second_session["distinct_id"], "user")
                self.assertEqual(parse(second_session["start_time"]), (now()))
                self.assertEqual(parse(second_session["end_time"]), (now() + relativedelta(seconds=30)))
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

    return TestSessionRecordings


class TestSessionRecordingsAPI(factory_test_session_recordings_api(SessionRecordingEvent.objects.create)):  # type: ignore
    pass
