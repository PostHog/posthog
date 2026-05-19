"""Tests for session recording person loading via the personhog path.

TestLoadPersonRouting — Pattern A routing test (gate/fallback logic).
TestLoadPersonIntegration — parameterized integration test (ORM + personhog).
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

        from posthog.models.person import Person

        mock_orm_person = MagicMock()
        if person_found:
            mock_person_objects.db_manager.return_value.get.return_value = mock_orm_person
        else:
            mock_person_objects.db_manager.return_value.get.side_effect = Person.DoesNotExist

        recording = SessionRecording()
        recording.distinct_id = "test-distinct-id"
        recording.team_id = 1
        # Use a real-looking mock for the team FK — bypass Django's descriptor
        mock_team = MagicMock()
        mock_team.pk = 1
        recording.__dict__["_team_cache"] = mock_team
        object.__setattr__(recording, "_team_cache", mock_team)
        # Patch the property access used in load_person
        type(recording).team = property(lambda self: mock_team)  # type: ignore[assignment]

        recording.load_person()

        mock_routing_counter.labels.assert_called_with(
            operation="load_person", source=expected_source, client_name="posthog-django"
        )

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


@parameterized_class(("personhog",), [(False,), (True,)])
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
