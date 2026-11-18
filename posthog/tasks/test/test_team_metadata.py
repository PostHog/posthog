from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import override_settings

from posthog.models.project import Project
from posthog.storage import object_storage
from posthog.tasks.team_metadata import (
    clear_team_metadata_cache_for_token_task,
    team_metadata_hypercache,
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


class TestClearTeamMetadataCacheForTokenTask(BaseTest):
    def test_skips_a_token_that_belongs_to_a_team(self) -> None:
        with patch.object(team_metadata_hypercache, "delete_cache_entry") as mock_delete:
            clear_team_metadata_cache_for_token_task(self.team.api_token)

        mock_delete.assert_not_called()

    def test_failed_mirror_delete_raises_so_the_task_retries(self) -> None:
        mirror = Mock()
        mirror.delete.side_effect = ConnectionError("mirror down")

        with (
            patch.object(team_metadata_hypercache, "secondary_cache_client", mirror),
            patch.object(object_storage, "delete"),
            self.assertRaises(ConnectionError),
        ):
            clear_team_metadata_cache_for_token_task("phc_retired_token")
