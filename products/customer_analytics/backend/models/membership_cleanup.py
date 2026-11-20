from typing import ClassVar, Self

from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class MembershipMissingSide(models.TextChoices):
    PERSON = "person", "person"
    GROUP = "group", "group"


class MembershipCleanupScan(TeamScopedRootMixin):
    # Cleanup state must survive project deletion until ClickHouse erasure is confirmed.
    team_id = models.BigIntegerField(unique=True)
    cursor = models.JSONField(default=list)
    last_team_id = models.BigIntegerField(default=0)
    scan_started_at = models.DateTimeField(null=True)
    objects: ClassVar[EnvironmentScopedManager[Self]] = EnvironmentScopedManager()


class MembershipCleanupCandidate(TeamScopedRootMixin):
    team_id = models.BigIntegerField()
    # Keep unbounded group keys and distinct IDs out of the unique index.
    key_hash = models.CharField(max_length=64)
    group_type_index = models.PositiveSmallIntegerField()
    group_key = models.TextField()
    distinct_id = models.TextField()
    missing_side = models.CharField(max_length=6, choices=MembershipMissingSide.choices)
    first_missing_at = models.DateTimeField()
    last_checked_at = models.DateTimeField()
    objects: ClassVar[EnvironmentScopedManager[Self]] = EnvironmentScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team_id", "key_hash", "missing_side"], name="ca_membership_candidate_key")
        ]
        indexes = [models.Index(fields=["team_id", "last_checked_at", "id"], name="ca_membership_candidate_due")]
