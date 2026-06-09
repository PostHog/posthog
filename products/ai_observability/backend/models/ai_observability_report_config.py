from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class AIObservabilityReportConfig(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """Per-team opt-in for the daily AI observability digest.

    When `enabled`, a daily coordinator on the LLMA worker runs the
    `AIObservabilityDigestAgent` for this team: it loads `skill_name` from the
    team's skill store, executes it in a sandbox (gathering the AI observability
    overview via read-only MCP), and posts the result to `slack_channel` on the
    connected `slack_integration`. The agent never files a Signals report — Slack
    is the only output.
    """

    # `objects` (TeamScopedManager) inherited from TeamScopedRootMixin stays fail-closed for
    # explicit user code. `all_teams` is the unscoped sibling the daily coordinator uses to
    # scan every team's config, plus Django framework internals (admin changelist, related
    # access, prefetch) that must not filter by team. Same pattern as SignalScoutConfig.
    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="ai_observability_report_configs",
    )
    enabled = models.BooleanField(default=True, db_default=True)
    # The `LLMSkill` (by name) the digest agent loads and executes. Resolved against the
    # team's skill store at run time — follows-latest, so re-versioning the skill takes
    # effect on the next daily run.
    skill_name = models.CharField(max_length=200)
    # The team's connected Slack OAuth integration the digest is posted through. SET_NULL so
    # disconnecting Slack doesn't cascade-delete the config; the coordinator skips configs
    # whose integration is missing.
    slack_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Slack channel ID (or name) the digest is delivered to.
    slack_channel = models.CharField(max_length=255)
    # Optional free-text steering appended to the skill instructions (e.g. "skip tool
    # insights"). Mirrors the eval-report `report_prompt_guidance` escape hatch.
    additional_instructions = models.TextField(blank=True, default="")
    # Stamped by the coordinator after each dispatch; lets a future change add a due-check
    # without a schema migration.
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "AI observability report config"
        verbose_name_plural = "AI observability report configs"
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["team"], name="unique_ai_observability_report_config_per_team"),
        ]
