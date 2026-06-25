"""Tests for session recording person loading via the personhog path."""

from posthog.test.base import BaseTest

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.test.persons import create_person


class TestLoadPersonIntegration(BaseTest):
    def test_person_found(self):
        person = create_person(team=self.team, distinct_ids=["test_user"], properties={"email": "test@example.com"})

        recording = SessionRecording(team=self.team, session_id="test_session", distinct_id="test_user")
        recording.load_person()

        assert recording._person is not None
        assert str(recording._person.uuid) == str(person.uuid)
        assert recording._person.properties == {"email": "test@example.com"}

    def test_person_not_found(self):
        recording = SessionRecording(team=self.team, session_id="test_session", distinct_id="nonexistent_user")
        recording.load_person()

        assert recording._person is None

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        create_person(team=other_team, distinct_ids=["shared_did"], properties={"email": "b@example.com"})

        recording = SessionRecording(team=self.team, session_id="test_session", distinct_id="shared_did")
        recording.load_person()

        assert recording._person is None
