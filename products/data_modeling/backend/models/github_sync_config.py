import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields

logger = logging.getLogger(__name__)


class GitHubSyncStatus(models.TextChoices):
    IDLE = "idle"
    SYNCING = "syncing"
    ERROR = "error"


class GitHubSyncConfig(CreatedMetaFields, UpdatedMetaFields):
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True)
    team_id: int

    integration = models.ForeignKey("posthog.Integration", on_delete=models.SET_NULL, null=True, blank=True)
    integration_id: int | None

    repository = models.CharField(
        max_length=1024, blank=True, default="", help_text="GitHub repo in 'owner/repo' format"
    )
    environment_name = models.CharField(
        max_length=256, blank=True, default="production", help_text="Environment name that maps to this team"
    )
    models_directory = models.CharField(
        max_length=256, blank=True, default="models", help_text="Directory within the repo containing model SQL files"
    )

    last_synced_sha = models.CharField(max_length=64, blank=True, default="", help_text="Last synced Git commit SHA")
    last_synced_at = models.DateTimeField(null=True, blank=True, help_text="When the last sync completed")
    sync_status = models.CharField(
        max_length=32,
        choices=GitHubSyncStatus,
        default=GitHubSyncStatus.IDLE,
    )
    last_sync_error = models.TextField(blank=True, default="", help_text="Error message from the last failed sync")

    auto_merge_prs = models.BooleanField(default=False, help_text="Auto-merge PRs created by PostHog for this env")

    def __str__(self) -> str:
        return f"GitHubSyncConfig {self.repository or '(unconfigured)'}"

    class Meta:
        app_label = "data_modeling"
        db_table = "posthog_datamodelinggithubsyncconfig"


register_team_extension_signal(GitHubSyncConfig, logger=logger)
