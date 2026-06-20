"""Tests for person deletion via personhog RPC.

Covers routing and integration for:
- delete_persons_from_postgres (API delete path)
- _delete_persons_for_teams (team deletion path)
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models.person import Person
from posthog.models.person.util import delete_persons_from_postgres
from posthog.models.team.util import _delete_persons_for_teams
from posthog.personhog_client.fake_client import fake_personhog_client

# ── Routing tests for delete_persons_from_postgres ──────────────────


class TestDeletePersonsFromPostgresRouting(SimpleTestCase):
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.person.util.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing_personhog_success(self, mock_errors_counter, mock_routing_counter):
        mock_person = MagicMock()
        mock_person.uuid = "550e8400-e29b-41d4-a716-446655440000"
        mock_person.delete = MagicMock()

        with fake_personhog_client():
            delete_persons_from_postgres(team_id=1, persons=[mock_person])

        mock_person.delete.assert_not_called()
        mock_routing_counter.labels.assert_called_with(
            operation="delete_persons", source="personhog", client_name="posthog-django"
        )

    def test_personhog_sends_correct_uuids(self):
        mock_persons = []
        for uuid in ["uuid-1", "uuid-2", "uuid-3"]:
            p = MagicMock()
            p.uuid = uuid
            mock_persons.append(p)

        with fake_personhog_client() as fake:
            delete_persons_from_postgres(team_id=42, persons=mock_persons)  # type: ignore[arg-type]

            calls = fake.assert_called("delete_persons", times=1)
            req = calls[0].request
            assert req.team_id == 42
            assert list(req.person_uuids) == ["uuid-1", "uuid-2", "uuid-3"]

    def test_personhog_batches_over_1000(self):
        mock_persons = []
        for i in range(1500):
            p = MagicMock()
            p.uuid = f"uuid-{i}"
            mock_persons.append(p)

        with fake_personhog_client() as fake:
            delete_persons_from_postgres(team_id=1, persons=mock_persons)  # type: ignore[arg-type]

            calls = fake.assert_called("delete_persons", times=2)
            assert len(list(calls[0].request.person_uuids)) == 1000
            assert len(list(calls[1].request.person_uuids)) == 500

    def test_empty_persons_list_is_noop(self):
        with fake_personhog_client() as fake:
            delete_persons_from_postgres(team_id=1, persons=[])
            fake.assert_not_called("delete_persons")


# ── Routing tests for _delete_persons_for_teams ─────────────────────


class TestDeletePersonsForTeamsRouting(SimpleTestCase):
    @patch("posthog.models.team.util._raw_delete_batch")
    def test_routing_personhog_success(self, mock_raw_delete_batch):
        with fake_personhog_client():
            _delete_persons_for_teams([1])

        mock_raw_delete_batch.assert_not_called()


# ── Integration tests (real DB) ─────────────────────────────────────


class TestDeletePersonsFromPostgresIntegration(BaseTest):
    def test_personhog_path_calls_rpc_with_correct_args(self):
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["did-1", "did-2"],
            properties={"email": "test@example.com"},
        )

        with fake_personhog_client() as fake:
            delete_persons_from_postgres(self.team.pk, [person])

            calls = fake.assert_called("delete_persons", times=1)
            req = calls[0].request
            assert req.team_id == self.team.pk
            assert list(req.person_uuids) == [str(person.uuid)]


class TestDeletePersonsForTeamsIntegration(BaseTest):
    def test_personhog_path_calls_batch_rpc_per_team(self):
        other_team = self.organization.teams.create(name="Other Team")
        p1 = Person.objects.create(team=self.team, distinct_ids=["a"])
        p2 = Person.objects.create(team=other_team, distinct_ids=["b"])

        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.pk, person_id=p1.pk, uuid=str(p1.uuid), distinct_ids=["a"])
            fake.add_person(team_id=other_team.pk, person_id=p2.pk, uuid=str(p2.uuid), distinct_ids=["b"])

            _delete_persons_for_teams([self.team.pk, other_team.pk])

            calls = fake.assert_called("delete_persons_batch_for_team")
            team_ids_called = {c.request.team_id for c in calls}
            assert self.team.pk in team_ids_called
            assert other_team.pk in team_ids_called

    def test_personhog_batch_rpc_loops_until_done(self):
        p1 = Person.objects.create(team=self.team, distinct_ids=["a"])
        p2 = Person.objects.create(team=self.team, distinct_ids=["b"])

        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.pk, person_id=p1.pk, uuid=str(p1.uuid), distinct_ids=["a"])
            fake.add_person(team_id=self.team.pk, person_id=p2.pk, uuid=str(p2.uuid), distinct_ids=["b"])

            _delete_persons_for_teams([self.team.pk])

            # Should have called at least twice: once to delete, once to confirm 0 remaining
            calls = fake.assert_called("delete_persons_batch_for_team")
            assert len(calls) >= 2
            # Last call should have returned deleted_count=0
            assert calls[-1].response.deleted_count == 0
