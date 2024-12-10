from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig
from posthog.tasks.remote_config import sync_all_remote_configs
from posthog.test.base import BaseTest


class TestRemoteConfig(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.other_team = team

    def test_sync_task_syncs_all_remote_configs(self) -> None:
        # Delete one teams config
        RemoteConfig.objects.get(team=self.other_team).delete()
        configs = RemoteConfig.objects.all()
        assert len(configs) == 1

        last_synced_at = RemoteConfig.objects.get(team=self.team).synced_at

        sync_all_remote_configs()

        configs = RemoteConfig.objects.all()
        assert len(configs) == 2

        assert RemoteConfig.objects.get(team=self.other_team).synced_at > last_synced_at  # type: ignore
        assert RemoteConfig.objects.get(team=self.team).synced_at > last_synced_at  # type: ignore
