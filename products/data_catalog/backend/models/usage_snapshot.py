from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from ..facade.enums import UsageSnapshotStatus


class UsageSnapshot(TeamScopedRootMixin, UUIDModel):
    """One scan of how a team's people and agents use the catalog, over a fixed window.

    Every scan writes a new row, so the history of a number stays readable after the next scan.
    The UI reads the newest ``done`` row. ``payload`` holds a ``UsageSnapshotPayload``.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")

    status = models.CharField(
        max_length=16,
        choices=UsageSnapshotStatus.choices,
        default=UsageSnapshotStatus.COMPUTING.value,
        help_text="computing while the scan runs, then done or error.",
    )
    error_message = models.TextField(blank=True, default="", help_text="Why the scan failed, when status is error.")
    window_start = models.DateTimeField(help_text="Start of the scanned window.")
    window_end = models.DateTimeField(help_text="End of the scanned window.")
    judge_model = models.CharField(
        max_length=64, blank=True, default="", help_text="Model that judged adjusted runs in this scan."
    )
    payload = models.JSONField(default=dict, blank=True, help_text="The scan result, one key per section.")
    computed_at = models.DateTimeField(null=True, blank=True, help_text="When the scan finished.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["team", "status", "-computed_at"], name="dc_usage_snapshot_latest")]

    def __str__(self) -> str:
        return f"{self.team_id} {self.window_start:%Y-%m-%d}..{self.window_end:%Y-%m-%d} {self.status}"
