"""Tests for session recording person loading via the personhog path.

Mirrors test_get_session_recordings_includes_person_data from test_session_recordings.py
to ensure the personhog code path returns identical results.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from posthog.models import Person
from posthog.personhog_client.fake_client import fake_personhog_client
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


class TestLoadPersonPersonhogIntegration(TestCase):
    def test_person_found(self) -> None:
        from posthog.models import Organization, Team

        org, _, _ = Organization.objects.bootstrap(None, name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")
        person = Person.objects.create(team=team, distinct_ids=["test_user"], properties={"email": "test@example.com"})

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=team.pk,
                person_id=person.pk,
                uuid=str(person.uuid),
                properties={"email": "test@example.com"},
                distinct_ids=["test_user"],
                is_identified=person.is_identified,
                created_at=int(person.created_at.timestamp() * 1000) if person.created_at else 0,
            )

            recording = SessionRecording(team=team, session_id="test_session", distinct_id="test_user")
            recording.load_person()

            assert recording._person is not None
            assert str(recording._person.uuid) == str(person.uuid)
            assert recording._person.properties == {"email": "test@example.com"}
            assert recording._person.distinct_ids == ["test_user"]
            fake.assert_called("get_person_by_distinct_id")

    def test_person_not_found(self) -> None:
        from posthog.models import Organization, Team

        org, _, _ = Organization.objects.bootstrap(None, name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")

        with fake_personhog_client() as fake:
            recording = SessionRecording(team=team, session_id="test_session", distinct_id="nonexistent_user")
            recording.load_person()

            assert recording._person is None
            fake.assert_called("get_person_by_distinct_id")

    def test_cross_team_isolation(self) -> None:
        from posthog.models import Organization, Team

        org, _, _ = Organization.objects.bootstrap(None, name="Test Org")
        team_a = Team.objects.create(organization=org, name="Team A")
        team_b = Team.objects.create(organization=org, name="Team B")
        person = Person.objects.create(team=team_b, distinct_ids=["shared_did"], properties={"email": "b@example.com"})

        with fake_personhog_client() as fake:
            # Seed person only in team_b
            fake.add_person(
                team_id=team_b.pk,
                person_id=person.pk,
                uuid=str(person.uuid),
                properties={"email": "b@example.com"},
                distinct_ids=["shared_did"],
            )

            # Try to load from team_a — should not find person
            recording = SessionRecording(team=team_a, session_id="test_session", distinct_id="shared_did")
            recording.load_person()

            assert recording._person is None
