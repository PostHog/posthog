from __future__ import annotations

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class SlackSummaryCadence(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class AccountChannelSummary(TeamScopedRootMixin, UUIDModel):
    """An AI summary of one closed period of an account's bound Slack channel.

    Written by the conversations summary pipeline through the facade. Message text is
    never persisted — only this summary (which cites messages with permalinks) and
    per-message metadata in ``messages`` backing the audit trail.
    """

    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    account = models.ForeignKey(
        "customer_analytics.Account", on_delete=models.CASCADE, related_name="channel_summaries"
    )
    # Kept on the row (not derived from the account) so summaries stay honest about
    # which channel they summarized after a rebinding.
    slack_channel_id = models.CharField(max_length=64)
    cadence = models.CharField(max_length=10, choices=SlackSummaryCadence.choices)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    content = models.TextField()
    message_count = models.PositiveIntegerField(default=0)
    # Audit trail behind message_count: [{author, sent_at, permalink}] per covered
    # message, in transcript order. Metadata only, never message text.
    messages = models.JSONField(default=list)
    model_name = models.CharField(max_length=100, blank=True, default="")
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta(TeamScopedRootMixin.Meta):
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "account", "cadence", "period_start"],
                name="ca_channel_summary_period_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["account_id", "-period_end"], name="ca_channel_summary_acct_idx"),
        ]

    def __str__(self) -> str:
        return f"AccountChannelSummary({self.account_id}, {self.cadence}, {self.period_start:%Y-%m-%d})"
