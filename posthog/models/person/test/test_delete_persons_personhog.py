"""Routing and RPC behavior of _delete_persons_for_teams (team deletion path)."""

from contextlib import nullcontext

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog import redis
from posthog.models.instance_setting import override_instance_config
from posthog.models.person.team_delete_batch_slots import QUEUE_KEY, SLOTS_KEY, WAITERS_KEY, TeamDeletePersonsBatchSlots
from posthog.models.team.util import _delete_persons_for_team_via_personhog, _delete_persons_for_teams
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.test.persons import create_person


def _clear_batch_slots() -> None:
    redis.get_client().delete(SLOTS_KEY, QUEUE_KEY, WAITERS_KEY)


# ── Routing tests for _delete_persons_for_teams ─────────────────────


class TestDeletePersonsForTeamsRouting(BaseTest):
    @patch("posthog.models.team.util._raw_delete_batch")
    def test_routes_to_personhog(self, mock_raw_delete_batch):
        with fake_personhog_client():
            _delete_persons_for_teams([1])

        mock_raw_delete_batch.assert_not_called()


class TestDeletePersonsForTeamsSlots(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        _clear_batch_slots()
        self.addCleanup(_clear_batch_slots)
        self.enterContext(override_instance_config("TEAM_DELETE_PERSONS_MAX_CONCURRENT_BATCHES", 1))

    def test_sends_no_batch_while_every_slot_is_held(self) -> None:
        TeamDeletePersonsBatchSlots(max_concurrent=lambda: 1).acquire()
        stops = iter([False, True])

        with fake_personhog_client() as fake:
            finished = _delete_persons_for_team_via_personhog(self.team.pk, should_stop=lambda: next(stops))

            assert not finished
            fake.assert_not_called("delete_persons_batch_for_team")

    @parameterized.expand([("batch_succeeds", None), ("batch_raises", RuntimeError("personhog is unavailable"))])
    def test_releases_its_slot_after_a_batch(self, _name: str, batch_error: Exception | None) -> None:
        with fake_personhog_client() as fake:
            if batch_error is not None:
                self.enterContext(patch.object(fake, "delete_persons_batch_for_team", side_effect=batch_error))

            with self.assertRaises(RuntimeError) if batch_error is not None else nullcontext():
                _delete_persons_for_teams([self.team.pk])

        assert redis.get_client().zcard(SLOTS_KEY) == 0


# ── RPC behavior tests (personhog fake with real test data) ─────────


class TestDeletePersonsForTeamsRPC(BaseTest):
    def test_personhog_path_calls_batch_rpc_per_team(self):
        other_team = self.organization.teams.create(name="Other Team")
        p1 = create_person(team=self.team, distinct_ids=["a"])
        p2 = create_person(team=other_team, distinct_ids=["b"])

        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.pk, person_id=p1.pk, uuid=str(p1.uuid), distinct_ids=["a"])
            fake.add_person(team_id=other_team.pk, person_id=p2.pk, uuid=str(p2.uuid), distinct_ids=["b"])

            _delete_persons_for_teams([self.team.pk, other_team.pk])

            calls = fake.assert_called("delete_persons_batch_for_team")
            team_ids_called = {c.request.team_id for c in calls}
            assert self.team.pk in team_ids_called
            assert other_team.pk in team_ids_called

    def test_personhog_batch_rpc_loops_until_done(self):
        p1 = create_person(team=self.team, distinct_ids=["a"])
        p2 = create_person(team=self.team, distinct_ids=["b"])

        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.pk, person_id=p1.pk, uuid=str(p1.uuid), distinct_ids=["a"])
            fake.add_person(team_id=self.team.pk, person_id=p2.pk, uuid=str(p2.uuid), distinct_ids=["b"])

            _delete_persons_for_teams([self.team.pk])

            # Should have called at least twice: once to delete, once to confirm 0 remaining
            calls = fake.assert_called("delete_persons_batch_for_team")
            assert len(calls) >= 2
            # Last call should have returned deleted_count=0
            assert calls[-1].response.deleted_count == 0
