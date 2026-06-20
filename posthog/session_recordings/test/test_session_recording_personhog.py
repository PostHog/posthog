"""Tests for session recording person loading via the personhog path.

TestLoadPersonRouting — routing test for the personhog success and failure paths.
TestLoadPersonIntegration — integration test against the personhog path.
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized, parameterized_class

from posthog.personhog_client.test_helpers import PersonhogTestMixin
from posthog.session_recordings.models.session_recording import SessionRecording


class TestLoadPersonRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("person_found", True),
            ("person_not_found", False),
        ]
    )
    @patch("posthog.session_recordings.models.session_recording._fetch_person_by_distinct_id_via_personhog")
    @patch("posthog.session_recordings.models.session_recording.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.session_recordings.models.session_recording.Person.objects")
    def test_personhog_success(
        self,
        _name,
        person_found,
        mock_person_objects,
        mock_routing_counter,
        mock_fetch_personhog,
    ):
        mock_person = MagicMock()
        mock_fetch_personhog.return_value = mock_person if person_found else None

        recording = self._build_recording()
        recording.load_person()

        mock_routing_counter.labels.assert_called_with(
            operation="load_person", source="personhog", client_name="posthog-django"
        )
        mock_person_objects.db_manager.assert_not_called()
        if person_found:
            assert recording._person == mock_person
        else:
            assert recording._person is None

    @patch("posthog.session_recordings.models.session_recording._fetch_person_by_distinct_id_via_personhog")
    @patch("posthog.session_recordings.models.session_recording.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_failure_raises(self, mock_errors_counter, mock_fetch_personhog):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        recording = self._build_recording()
        with self.assertRaises(RuntimeError):
            recording.load_person()

        mock_errors_counter.labels.assert_called_once()

    @staticmethod
    def _build_recording() -> SessionRecording:
        recording = SessionRecording()
        recording.distinct_id = "test-distinct-id"
        recording.team_id = 1
        # Use a real-looking mock for the team FK — bypass Django's descriptor
        mock_team = MagicMock()
        mock_team.pk = 1
        object.__setattr__(recording, "_team_cache", mock_team)
        # Patch the property access used in load_person
        type(recording).team = property(lambda self: mock_team)  # type: ignore[assignment]
        return recording


@parameterized_class(("personhog",), [(True,)])
class TestLoadPersonIntegration(PersonhogTestMixin, BaseTest):
    def test_person_found(self):
        person = self._seed_person(team=self.team, distinct_ids=["test_user"], properties={"email": "test@example.com"})

        recording = SessionRecording(team=self.team, session_id="test_session", distinct_id="test_user")
        recording.load_person()

        assert recording._person is not None
        assert str(recording._person.uuid) == str(person.uuid)
        assert recording._person.properties == {"email": "test@example.com"}
        self._assert_personhog_called("get_person_by_distinct_id")

    def test_person_not_found(self):
        recording = SessionRecording(team=self.team, session_id="test_session", distinct_id="nonexistent_user")
        recording.load_person()

        assert recording._person is None
        self._assert_personhog_called("get_person_by_distinct_id")

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self._seed_person(team=other_team, distinct_ids=["shared_did"], properties={"email": "b@example.com"})

        recording = SessionRecording(team=self.team, session_id="test_session", distinct_id="shared_did")
        recording.load_person()

        assert recording._person is None
