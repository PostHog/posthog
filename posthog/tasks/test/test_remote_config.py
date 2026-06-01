from posthog.test.base import BaseTest

from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.tasks.remote_config import sync_all_remote_configs


class TestRemoteConfig(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.other_team_1 = team

        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project 2",
        )
        self.other_team_2 = team

        # Force synchronous RemoteConfig creation for tests since signals are async now
        from posthog.tasks.remote_config import update_team_remote_config

        for team in [self.team, self.other_team_1, self.other_team_2]:
            try:
                RemoteConfig.objects.get(team=team)
            except RemoteConfig.DoesNotExist:
                update_team_remote_config(team.id)

    def test_sync_task_syncs_all_remote_configs(self) -> None:
        # Delete one teams config
        remote_config_deleted = RemoteConfig.objects.get(team=self.team)
        remote_config_deleted_synced_at = remote_config_deleted.synced_at
        remote_config_deleted.delete()

        configs = RemoteConfig.objects.all()
        assert len(configs) == 2

        # Modify the other team's config (indicate something didn't get synced properly)
        remote_config_1 = RemoteConfig.objects.get(team=self.other_team_1)
        remote_config_1.config["token"] = "MODIFIED"
        remote_config_1.save()
        remote_config_1_synced_at = remote_config_1.synced_at

        # No modifications to this one
        remote_config_2 = RemoteConfig.objects.get(team=self.other_team_2)
        remote_config_2_synced_at = remote_config_2.synced_at

        sync_all_remote_configs()

        configs = RemoteConfig.objects.all()
        assert len(configs) == 3

        # This one is deleted so should be synced
        assert RemoteConfig.objects.get(team=self.team).synced_at > remote_config_deleted_synced_at  # type: ignore
        # This one is modified so should be synced
        assert RemoteConfig.objects.get(team=self.other_team_1).synced_at > remote_config_1_synced_at  # type: ignore
        # This one is unchanged so should not be synced
        assert RemoteConfig.objects.get(team=self.other_team_2).synced_at == remote_config_2_synced_at
