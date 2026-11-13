from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.storage.team_metadata_cache import team_metadata_hypercache
from posthog.tasks.team_metadata import (
    evict_rotated_token_team_metadata_cache_task,
    update_related_teams_metadata_cache_task,
)


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestRelatedTeamsMetadataFanoutTask(BaseTest):
    def test_organization_fanout_enqueues_every_team(self) -> None:
        _, second_team = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user, name="Second project"
        )

        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_update:
            update_related_teams_metadata_cache_task(organization_id=self.organization.id)

        enqueued_team_ids = {call.args[0] for call in mock_update.delay.call_args_list}
        self.assertEqual(enqueued_team_ids, {self.team.id, second_team.id})

    def test_project_fanout_enqueues_project_team(self) -> None:
        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_update:
            update_related_teams_metadata_cache_task(project_id=self.project.id)

        enqueued_team_ids = {call.args[0] for call in mock_update.delay.call_args_list}
        self.assertEqual(enqueued_team_ids, {self.team.id})

    def test_fanout_is_noop_without_ids(self) -> None:
        with patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_update:
            update_related_teams_metadata_cache_task()

        mock_update.delay.assert_not_called()

    def test_logs_and_reraises_on_failure(self) -> None:
        with (
            patch("posthog.tasks.team_metadata.update_team_metadata_cache_task") as mock_update,
            patch("posthog.tasks.team_metadata.logger") as mock_logger,
            self.assertRaises(Exception),
        ):
            mock_update.delay.side_effect = Exception("broker down")
            update_related_teams_metadata_cache_task(organization_id=self.organization.id)

        mock_logger.exception.assert_called_once()


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestEvictRotatedTokenTeamMetadataCacheTask(BaseTest):
    @parameterized.expand(
        [
            ("unowned_token_is_deleted_from_every_tier", False, True),
            ("token_owned_again_is_kept", True, False),
        ]
    )
    def test_evicts_only_an_unowned_token(self, _name: str, token_owned: bool, expect_delete: bool) -> None:
        if token_owned:
            Team.objects.create(organization=self.organization, api_token="phc_rotated_token")

        with (
            override_settings(TEST=False),
            patch.object(team_metadata_hypercache, "delete_cache_entry") as mock_delete,
        ):
            evict_rotated_token_team_metadata_cache_task("phc_rotated_token")

        if expect_delete:
            mock_delete.assert_called_once_with("phc_rotated_token", kinds=None)
        else:
            mock_delete.assert_not_called()
