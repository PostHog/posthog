"""Tests for session recording person loading via the personhog path.

TestLoadPersonRouting — Pattern A routing test (gate/fallback logic).
TestLoadPersonIntegration — integration test for person loading.
"""

from posthog.test.base import BaseTest
from unittest.mock import ANY, MagicMock, PropertyMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person import Person
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.test.persons import create_person


class TestLoadPersonRouting(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "personhog_success_person_found",
                True,
                None,
                "personhog",
                True,
            ),
            (
                "personhog_success_person_not_found",
                True,
                None,
                "personhog",
                False,
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                RuntimeError("grpc timeout"),
                "django_orm",
                True,
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                "django_orm",
                True,
            ),
        ]
    )
    @patch("posthog.session_recordings.models.session_recording._fetch_person_by_distinct_id_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.session_recordings.models.session_recording.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.session_recordings.models.session_recording.PERSONHOG_ROUTING_ERRORS_TOTAL")
    @patch("posthog.session_recordings.models.session_recording.Person.objects")
    def test_routing(
        self,
        _name,
        gate_on,
        grpc_exception,
        expected_source,
        person_found,
        mock_person_objects,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
    ):
        mock_use_personhog.return_value = gate_on

        mock_person = MagicMock()
        if grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception
        elif person_found:
            mock_fetch_personhog.return_value = mock_person
        else:
            mock_fetch_personhog.return_value = None

        mock_orm_person = MagicMock()
        if person_found:
            mock_person_objects.db_manager.return_value.get.return_value = mock_orm_person
        else:
            mock_person_objects.db_manager.return_value.get.side_effect = Person.DoesNotExist

        recording = SessionRecording()
        recording.distinct_id = "test-distinct-id"
        recording.team_id = 1
        # Use a real-looking mock for the team FK — bypass Django's descriptor.
        mock_team = MagicMock()
        mock_team.pk = 1

        # Patch `team` at the class level via patch.object so the original FK
        # descriptor is restored afterwards. A bare `type(recording).team = ...`
        # leaks a setter-less property into every later SessionRecording test in
        # the same process (only visible when those tests run on the same shard).
        with patch.object(type(recording), "team", new_callable=PropertyMock, return_value=mock_team):
            recording.load_person()

        mock_routing_counter.labels.assert_called_with(operation="load_person", source=expected_source, client_name=ANY)

        if gate_on and grpc_exception is None:
            mock_person_objects.db_manager.assert_not_called()
            if person_found:
                assert recording._person == mock_person
            else:
                assert recording._person is None
        else:
            if person_found:
                assert recording._person == mock_orm_person

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()


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
