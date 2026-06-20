"""Tests for personless distinct ID deletion via personhog RPC.

Covers routing for _delete_personless_distinct_ids_for_teams
(team deletion path), which routes through delete_personless_distinct_ids_batch_for_team.
"""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from django.test import SimpleTestCase

from posthog.models.team.util import _delete_personless_distinct_ids_for_teams
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto import DeletePersonlessDistinctIdsBatchForTeamResponse


class TestDeletePersonlessDistinctIdsForTeamsRouting(SimpleTestCase):
    def test_personhog_success(self):
        with fake_personhog_client():
            _delete_personless_distinct_ids_for_teams([1])

    def test_personhog_failure_raises(self):
        with fake_personhog_client() as fake:
            fake.delete_personless_distinct_ids_batch_for_team = MagicMock(side_effect=RuntimeError("grpc timeout"))
            with self.assertRaises(RuntimeError):
                _delete_personless_distinct_ids_for_teams([1])

    def test_personhog_loops_until_zero_deleted(self):
        with fake_personhog_client() as fake:
            fake.delete_personless_distinct_ids_batch_for_team = MagicMock(
                side_effect=[
                    DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=10000),
                    DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=42),
                    DeletePersonlessDistinctIdsBatchForTeamResponse(deleted_count=0),
                ]
            )

            _delete_personless_distinct_ids_for_teams([1])

            assert fake.delete_personless_distinct_ids_batch_for_team.call_count == 3


class TestDeletePersonlessDistinctIdsForTeamsIntegration(BaseTest):
    def test_personhog_path_calls_batch_rpc_per_team(self):
        other_team = self.organization.teams.create(name="Other Team")

        with fake_personhog_client() as fake:
            _delete_personless_distinct_ids_for_teams([self.team.pk, other_team.pk])

            calls = fake.assert_called("delete_personless_distinct_ids_batch_for_team")
            team_ids_called = {c.request.team_id for c in calls}
            assert self.team.pk in team_ids_called
            assert other_team.pk in team_ids_called
            assert all(c.request.batch_size == 10000 for c in calls)
