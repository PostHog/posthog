from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import uuid7


class ContextLayerConfig(models.Model):
    """One row per organization with the context layer enabled.

    `head_sha` is the compare-and-swap pointer to the current repo bundle in
    object storage; every landing writer updates it with
    `UPDATE ... WHERE head_sha = <expected>` so a lost race is explicit.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
    )
    head_sha = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Nightly dreaming lane state: skip-overlap bookkeeping and a per-org
    # circuit breaker that pauses the lane after repeated dispatch failures.
    last_dream_started_at = models.DateTimeField(null=True, blank=True)
    dream_failure_streak = models.PositiveIntegerField(default=0)
    dreaming_paused = models.BooleanField(default=False)

    # Set when a purge rewrote the history but could not remove every old
    # bundle; cleared by the next fully successful purge.
    purge_incomplete_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "context_layer_config"


class WikiPageProposal(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task_id = models.UUIDField()
    path = models.CharField(max_length=512)
    original_content = models.TextField()
    content = models.TextField()
    base_head = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_head = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["created_by", "-created_at"], name="wiki_proposal_author_created")]


class ContextSelectionAssignment(TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    task = models.OneToOneField(
        "tasks.Task", on_delete=models.CASCADE, db_constraint=False, related_name="context_selection_assignment"
    )
    mode = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)


class ContextSelectionAttempt(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    run = models.ForeignKey("tasks.TaskRun", on_delete=models.CASCADE, related_name="context_selections")
    actor = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    message_id = models.CharField(max_length=128)
    input_hash = models.CharField(max_length=64)
    mode = models.CharField(max_length=16)
    status = models.CharField(max_length=32, default="preparing")
    context = models.TextField(default="")
    evidence = models.JSONField(default=dict)
    receipt = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "message_id"], name="context_selection_run_message")]


class ContextSelectionProjection(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    version = models.CharField(max_length=64)
    payload = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "version"], name="context_projection_team_version")]


class ContextSelectionSearchState(TeamScopedRootMixin):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    version = models.CharField(max_length=64)
    archive_id = models.UUIDField()
    built_at = models.DateTimeField()
    refresh_seconds = models.FloatField()


class ContextSelectionSearchDocument(TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    source_kind = models.CharField(max_length=32)
    source_id = models.CharField(max_length=64)
    title = models.TextField()
    text = models.TextField()
    revision = models.CharField(max_length=128)
    status = models.CharField(max_length=64)
    reference = models.TextField()
    tables = models.JSONField(default=list)
    search_vector = SearchVectorField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "source_kind", "source_id"], name="context_search_source")
        ]
        indexes = [GinIndex(fields=["search_vector"], name="context_search_vector_gin")]
