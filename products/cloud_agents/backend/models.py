"""
Django models for cloud_agents.

Keep models thin. Business logic belongs in logic/.
Foreign keys to posthog_team and posthog_user have `db_constraint=False`, so
CreateModel takes no lock on those tables. Django still applies `on_delete`.
"""

from django.db import models
from django.db.models.functions import Lower

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import uuid7

from .facade.enums import CallerKind, CloudAgentReasoningEffort, InferenceMode, SizeName


class RunDefaultsMixin(models.Model):
    """Run defaults that a preset and the project settings both hold. A null field sets no default."""

    # A list of `{"name": "owner/name", "initial_branch": "main" or null}`, the shape of `RepositoryRef`.
    repositories = models.JSONField(null=True, blank=True)
    model = models.CharField(max_length=100, null=True, blank=True)
    reasoning_effort = models.CharField(max_length=16, choices=CloudAgentReasoningEffort.choices, null=True, blank=True)
    size = models.CharField(max_length=16, choices=SizeName.choices, null=True, blank=True)
    inference = models.CharField(max_length=32, choices=InferenceMode.choices, null=True, blank=True)
    instructions = models.TextField(null=True, blank=True)
    create_pr = models.BooleanField(null=True, blank=True)
    idle_minutes = models.PositiveIntegerField(null=True, blank=True)
    output_schema = models.JSONField(null=True, blank=True)

    class Meta:
        abstract = True


class CloudAgentPreset(RunDefaultsMixin, TeamScopedRootMixin):
    # `objects` (TeamScopedManager) from TeamScopedRootMixin is fail-closed. `all_teams` is the
    # unscoped manager that Django internals use through Meta.default_manager_name.
    all_teams = models.Manager()  # noqa: DJ012

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    tags = models.JSONField(default=list, blank=True)

    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(
                "team",
                Lower("name"),
                condition=models.Q(deleted=False),
                name="cloud_agents_preset_unique_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CloudAgentRun(TeamScopedRootMixin):
    all_teams = models.Manager()  # noqa: DJ012

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    caller_kind = models.CharField(max_length=16, choices=CallerKind.choices, default=CallerKind.API.value)
    caller_product = models.CharField(max_length=40, null=True, blank=True)
    billable = models.BooleanField(default=True)

    # The task of the Tasks product that does the work. A plain id, because this product reads
    # Tasks through its facade and must not join to its tables. The status, the result, the agent
    # sessions and the cost of a run are not stored here: each read takes them from Tasks.
    task_id = models.UUIDField(null=True, blank=True, db_index=True)

    prompt = models.TextField()
    # The name of the repository of the run, as a column so that the list can filter by it. The
    # full list, with the branches, is in `config`.
    repository = models.CharField(max_length=255)
    preset = models.ForeignKey(CloudAgentPreset, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    tags = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    request_hash = models.CharField(max_length=64, null=True, blank=True)

    # Snapshot of the resolved configuration (ResolvedRunConfig.to_json), so a later change to a
    # preset or to the project settings does not change a run that already started.
    config = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="cloud_agents_run_unique_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "-created_at"], name="cloud_agents_run_team_created"),
        ]

    def __str__(self) -> str:
        return f"CloudAgentRun({self.id})"


class TeamCloudAgentsConfig(RunDefaultsMixin, TeamScopedRootMixin):
    """Team extension that holds the project defaults and limits. Read it with `logic.team_config.get_team_config`."""

    all_teams = models.Manager()  # noqa: DJ012

    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, related_name="+", db_constraint=False
    )
    default_preset = models.ForeignKey(
        CloudAgentPreset, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Staff set these overrides. A null value means the product default in logic/limits.py.
    max_concurrent_runs = models.PositiveIntegerField(null=True, blank=True)
    create_rate_per_hour = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_manager_name = "all_teams"

    def __str__(self) -> str:
        return f"TeamCloudAgentsConfig(team={self.team_id})"
