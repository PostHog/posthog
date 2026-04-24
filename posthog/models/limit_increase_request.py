from django.conf import settings
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.utils import timezone

from posthog.models.utils import UUIDModel


class LimitIncreaseRequestStatus(models.TextChoices):
    PENDING = "pending", "pending"
    APPROVED = "approved", "approved"
    DENIED = "denied", "denied"


class LimitIncreaseRequest(UUIDModel):
    """A customer request to raise a resource limit for a team.

    Auto-submitted server-side the first time a team hits a given limit, then
    reused (``hit_count`` bumped) on subsequent hits — the partial unique
    constraint guarantees at most one ``pending`` request per
    ``(team, limit_key)``.

    Resolution happens via Django admin. On approve, staff writes an
    :class:`~posthog.models.team_limit_override.TeamLimitOverride`
    scoped to the same team and flips ``status`` to ``approved``.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="limit_increase_requests",
    )
    limit_key = models.CharField(max_length=128)

    limit_at_first_hit = models.BigIntegerField()
    count_at_first_hit = models.BigIntegerField()
    requested_value = models.BigIntegerField(null=True, blank=True)
    justification = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=LimitIncreaseRequestStatus.choices,
        default=LimitIncreaseRequestStatus.PENDING,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="limit_increase_requests",
    )
    hit_count = models.IntegerField(default=1)
    last_hit_at = models.DateTimeField(default=timezone.now)

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_limit_increase_requests",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["status", "last_hit_at"]),
        ]
        constraints = [
            UniqueConstraint(
                fields=["team", "limit_key"],
                condition=Q(status="pending"),
                name="one_pending_limit_increase_request_per_team_key",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.limit_key} ({self.status}, team {self.team_id})"
