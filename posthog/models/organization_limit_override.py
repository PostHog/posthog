from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDModel


class OrganizationLimitOverride(UUIDModel):
    """Per-team raise of a resource limit.

    Staff writes a row here when approving a :class:`LimitIncreaseRequest` so
    the evaluator in :mod:`posthog.resource_limits.evaluator` returns the
    raised value instead of the registry default.

    Despite the historical name this override is always team-scoped; to bump
    every team in an org, grant one per team.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="limit_overrides",
    )
    limit_key = models.CharField(max_length=128)
    # Null means unlimited.
    value = models.BigIntegerField(null=True, blank=True)
    reason = models.TextField()
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_limit_overrides",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["team", "limit_key"])]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "limit_key"],
                name="uniq_team_limit_override",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.limit_key} = {self.value} (team {self.team_id})"
