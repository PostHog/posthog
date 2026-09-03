from collections.abc import Iterable

from django.db import models
from django.utils import timezone

from posthog.models.health_issue import _filter_existing_team_ids
from posthog.models.utils import UUIDModel


class HealthCheckRun(UUIDModel):
    """When a health check last evaluated a team.

    Health issues record findings only, so a missing issue cannot be told apart from a check
    that never ran for the team: the daily workflows skip teams whose organization has been
    dormant, and a skipped team keeps whatever the previous run left behind. This row is what
    lets a surface say "checked 3 hours ago" instead of presenting a stale finding as current.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="health_check_runs",
    )

    kind = models.CharField(max_length=100)

    last_run_at = models.DateTimeField(default=timezone.now)

    # Whether the run that wrote this row found anything. Lets a surface tell "checked, all good"
    # apart from "never checked" without joining back to the issue table.
    found_issues = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "kind"], name="unique_health_check_run_per_team_kind"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} for team {self.team_id} at {self.last_run_at}"

    @classmethod
    def record_run(cls, kind: str, team_ids: Iterable[int], teams_with_issues: set[int]) -> None:
        """Stamp `kind` as evaluated for every team in the batch."""
        # Mirror the issue writes: a team deleted between the workflow's team-ID snapshot and this
        # call would fail the FK and roll back the whole batch.
        existing_team_ids = _filter_existing_team_ids(set(team_ids))
        if not existing_team_ids:
            return

        now = timezone.now()
        rows = [
            cls(team_id=team_id, kind=kind, last_run_at=now, found_issues=team_id in teams_with_issues)
            for team_id in sorted(existing_team_ids)
        ]
        cls.objects.bulk_create(
            rows,
            update_conflicts=True,
            update_fields=["last_run_at", "found_issues"],
            unique_fields=["team", "kind"],
        )
