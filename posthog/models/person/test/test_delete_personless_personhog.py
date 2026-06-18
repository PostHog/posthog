"""Tests for personless distinct ID deletion via personhog RPC.

Covers routing, fallback, and integration for _delete_personless_distinct_ids_for_teams
(team deletion path), which routes through delete_personless_distinct_ids_batch_for_team
and falls back to the raw batched SQL delete.
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.person import PersonlessDistinctId
from posthog.models.team.util import _delete_personless_distinct_ids_for_teams
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto import DeletePersonlessDistinctIdsBatchForTeamResponse


class TestDeletePersonlessDistinctIdsForTeamsRouting(SimpleTestCase):
    @parameterized.expand(
        [
            ("personhog_success", True, None),
            ("personhog_failure_falls_back_to_orm", True, RuntimeError("grpc timeout")),
            ("gate_off_uses_orm_directly", False, None),
        ]
    )
    @patch("posthog.models.team.util._raw_delete_personless_distinct_ids_for_team")
    def test_routing(self, _name, gate_on, grpc_exception, mock_raw_delete):
        with fake_personhog_client(gate_enabled=gate_on) as fake:
            if grpc_exception is not None:
                fake.delete_personless_distinct_ids_batch_for_team = MagicMock(side_effect=grpc_exception)

            _delete_personless_distinct_ids_for_teams([1])

        if gate_on and grpc_exception is None:
            mock_raw_delete.assert_not_called()
        else:
            mock_raw_delete.assert_called_once_with(1)

    @patch("posthog.models.team.util._raw_delete_personless_distinct_ids_for_team")
    def test_personhog_loops_until_zero_deleted(self, mock_raw_delete):
        # The real RPC returns the number of rows deleted per batch; the caller loops
        # until it returns 0. The fake hardcodes 0, so override it with a sequence that
        # forces the while loop to run multiple times before breaking.
        with fake_personhog_client(gate_enabled=True) as fake:
            fake.delete_personless_distinct_ids_batch_for_team = MagicMock(
                side_effect=[
                    DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=10000),
                    DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=42),
                    DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=0),
                ]
            )

            _delete_personless_distinct_ids_for_teams([1])

            # Looped until a batch returned 0: three calls, last returning 0.
            assert fake.delete_personless_distinct_ids_batch_for_team.call_count == 3

        # Personhog handled it — no ORM fallback.
        mock_raw_delete.assert_not_called()


class TestDeletePersonlessDistinctIdsForTeamsIntegration(BaseTest):
    def _create_personless(self, team_id: int, distinct_id: str) -> None:
        PersonlessDistinctId.objects.create(  # nosemgrep: no-direct-persons-db-orm
            team_id=team_id, distinct_id=distinct_id, is_merged=False, created_at=timezone.now()
        )

    def test_orm_fallback_deletes_personless_ids(self):
        self._create_personless(self.team.pk, "did-1")
        self._create_personless(self.team.pk, "did-2")
        assert PersonlessDistinctId.objects.filter(team_id=self.team.pk).count() == 2

        with fake_personhog_client(gate_enabled=False):
            _delete_personless_distinct_ids_for_teams([self.team.pk])

        assert PersonlessDistinctId.objects.filter(team_id=self.team.pk).count() == 0

    def test_personhog_path_calls_batch_rpc_per_team(self):
        other_team = self.organization.teams.create(name="Other Team")

        with fake_personhog_client(gate_enabled=True) as fake:
            _delete_personless_distinct_ids_for_teams([self.team.pk, other_team.pk])

            calls = fake.assert_called("delete_personless_distinct_ids_batch_for_team")
            team_ids_called = {c.request.team_id for c in calls}
            assert self.team.pk in team_ids_called
            assert other_team.pk in team_ids_called
            assert all(c.request.batch_size == 10000 for c in calls)

    def test_personhog_fallback_on_error_deletes_via_orm(self):
        self._create_personless(self.team.pk, "did-1")

        with fake_personhog_client(gate_enabled=True) as fake:
            fake.delete_personless_distinct_ids_batch_for_team = MagicMock(side_effect=RuntimeError("grpc timeout"))
            _delete_personless_distinct_ids_for_teams([self.team.pk])

        assert PersonlessDistinctId.objects.filter(team_id=self.team.pk).count() == 0

    def test_cross_team_isolation(self):
        other_team = self.organization.teams.create(name="Other Team")
        self._create_personless(self.team.pk, "a")
        self._create_personless(other_team.pk, "b")

        with fake_personhog_client(gate_enabled=False):
            _delete_personless_distinct_ids_for_teams([self.team.pk])

        assert PersonlessDistinctId.objects.filter(team_id=self.team.pk).count() == 0
        assert PersonlessDistinctId.objects.filter(team_id=other_team.pk).count() == 1
