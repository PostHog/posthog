from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from .github_sync_config import GitHubSyncConfig


class GitHubSyncPlanStatus(models.TextChoices):
    PENDING = "pending"  # plan computed, PR still open
    APPLIED = "applied"  # merged and synced
    CLOSED = "closed"  # PR closed without merge
    STALE = "stale"  # superseded by newer plan on same PR


class GitHubSyncPlan(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    config = models.ForeignKey(GitHubSyncConfig, on_delete=models.CASCADE, related_name="sync_plans")

    pr_number = models.IntegerField(help_text="GitHub PR number")
    pr_url = models.URLField(max_length=1024, help_text="Full URL to the GitHub PR")
    head_sha = models.CharField(max_length=64, help_text="Commit SHA the plan was computed from")

    plan = models.JSONField(
        help_text="Structured plan: {models: {added, modified, removed, renamed}, dags: {added, modified, removed}}"
    )

    github_comment_id = models.BigIntegerField(
        null=True, blank=True, help_text="GitHub comment ID for the plan comment on the PR"
    )

    status = models.CharField(
        max_length=16,
        choices=GitHubSyncPlanStatus.choices,
        default=GitHubSyncPlanStatus.PENDING,
    )
    applied_at = models.DateTimeField(null=True, blank=True, help_text="When this plan was applied on merge")
    applied_sha = models.CharField(
        max_length=64, blank=True, default="", help_text="Merge commit SHA that applied this plan"
    )

    class Meta:
        app_label = "data_modeling"
        db_table = "posthog_datamodelinggithubsyncplan"
