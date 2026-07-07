from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.tasks.team_metadata import update_related_teams_metadata_cache_task


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestTeamMetadataInvalidationSignals(BaseTest):
    def test_organization_rename_enqueues_fanout(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.name = "Renamed org"
                self.organization.save()

        mock_task.delay.assert_called_once_with(organization_id=self.organization.id, project_id=None)

    def test_project_rename_enqueues_fanout(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.project.name = "Renamed project"
                self.project.save()

        mock_task.delay.assert_called_once_with(organization_id=None, project_id=self.project.id)

    def test_save_with_name_in_update_fields_enqueues(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.name = "Renamed via update_fields"
                self.organization.save(update_fields=["name"])

        mock_task.delay.assert_called_once_with(organization_id=self.organization.id, project_id=None)

    def test_save_without_name_in_update_fields_does_not_enqueue(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.is_member_join_email_enabled = False
                self.organization.save(update_fields=["is_member_join_email_enabled"])

        mock_task.delay.assert_not_called()

    def test_creating_does_not_enqueue(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                Organization.objects.create(name="Brand new org")
                Project.objects.create_with_team(
                    organization=self.organization, initiating_user=self.user, name="Brand new project"
                )

        mock_task.delay.assert_not_called()

    @override_settings(FLAGS_REDIS_URL="")
    def test_no_fanout_when_flags_redis_url_unset(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                self.organization.name = "Renamed org"
                self.organization.save()
                self.project.name = "Renamed project"
                self.project.save()

        mock_task.delay.assert_not_called()

    def test_enqueue_failure_records_counter_and_does_not_propagate(self) -> None:
        with patch("posthog.tasks.team_metadata.update_related_teams_metadata_cache_task") as mock_task:
            mock_task.delay.side_effect = Exception("broker down")
            with patch("posthog.tasks.team_metadata.HYPERCACHE_SIGNAL_UPDATE_COUNTER") as mock_counter:
                try:
                    with self.captureOnCommitCallbacks(execute=True):
                        self.organization.name = "Renamed org"
                        self.organization.save(update_fields=["name"])
                except Exception:
                    self.fail("enqueue failure should not propagate to the caller")

        mock_counter.labels.assert_called_once_with(
            namespace="team_metadata", cache_name="team_metadata", operation="enqueue", result="failure"
        )
        mock_counter.labels.return_value.inc.assert_called_once_with()


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


@override_settings(FLAGS_REDIS_URL="redis://localhost:6379")
class TestOrgProjectDeleteCascadesToTeamClear(BaseTest):
    def test_deleting_project_clears_team_metadata_via_cascade(self) -> None:
        project, team = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user, name="Doomed project"
        )
        team_id = team.id

        # Capture ids at call time: the delete collector nulls each instance's pk after deletion,
        # so reading instance.id after project.delete() returns would see None.
        cleared_team_ids: set[int] = set()
        with patch(
            "posthog.tasks.team_metadata.clear_team_metadata_cache",
            side_effect=lambda instance, **kwargs: cleared_team_ids.add(instance.id),
        ):
            project.delete()

        self.assertIn(team_id, cleared_team_ids)
