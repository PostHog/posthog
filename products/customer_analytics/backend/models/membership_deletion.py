from django.db import models
from django.utils import timezone

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.customer_analytics.backend.facade.membership_deletion_contracts import MembershipDeletionKind


class MembershipDeletionTeam(TeamScopedRootMixin, UUIDModel):
    team_id = models.BigIntegerField(unique=True)

    objects = EnvironmentScopedManager()  # type: ignore[assignment, misc] # Deleted teams require literal IDs.
    all_teams = models.Manager()

    class Meta:
        default_manager_name = "all_teams"


class MembershipDeletionReceipt(TeamScopedRootMixin, UUIDModel):
    team_id = models.BigIntegerField(db_index=True)
    kind = models.CharField(max_length=12, choices=[(kind.value, kind.value) for kind in MembershipDeletionKind])
    source_key = models.CharField(max_length=255)
    person_uuid = models.UUIDField(null=True, blank=True)
    person_version = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    dispatch_claimed_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    # Retries must detect changed identities even after completion erases the identity rows.
    identity_digest = models.CharField(max_length=64, null=True, blank=True)

    objects = EnvironmentScopedManager()  # type: ignore[assignment, misc] # Deleted teams require literal IDs.
    all_teams = models.Manager()

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "kind", "source_key", "person_uuid"],
                condition=models.Q(person_uuid__isnull=False),
                name="ca_mem_receipt_person_source",
            ),
            models.UniqueConstraint(
                fields=["team_id", "kind", "source_key"],
                condition=models.Q(person_uuid__isnull=True),
                name="ca_mem_receipt_team_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["created_at", "id"],
                condition=models.Q(confirmed_at__isnull=False, completed_at__isnull=True),
                name="ca_mem_receipt_pending",
            ),
            models.Index(
                fields=["created_at", "id"],
                condition=models.Q(confirmed_at__isnull=True, completed_at__isnull=True),
                name="ca_mem_receipt_prepared",
            ),
        ]


class MembershipDeletionIdentity(TeamScopedRootMixin):
    id = models.BigAutoField(primary_key=True)
    team_id = models.BigIntegerField(db_index=True)
    receipt = models.ForeignKey(
        "customer_analytics.MembershipDeletionReceipt", on_delete=models.CASCADE, related_name="+"
    )
    distinct_id = models.CharField(max_length=400)
    version = models.BigIntegerField()

    objects = EnvironmentScopedManager()  # type: ignore[misc] # Deleted teams require literal IDs.
    all_teams = models.Manager()

    class Meta:
        default_manager_name = "all_teams"
        constraints = [
            models.UniqueConstraint(fields=["receipt", "distinct_id"], name="ca_mem_identity_receipt_did"),
        ]
        indexes = [models.Index(fields=["receipt", "id"], name="ca_mem_identity_page")]
