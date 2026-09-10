import uuid

from django.db import models

from posthog.models.utils import uuid7


class TemporalSchedulerPermitPool(models.Model):
    scheduler = models.CharField(max_length=128)
    region = models.CharField(max_length=32)
    tenant_key = models.CharField(max_length=128, default="", db_default="")
    in_flight = models.PositiveIntegerField(default=0, db_default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_temporalschedulerpermitpool"
        constraints = [
            models.UniqueConstraint(
                fields=["scheduler", "region", "tenant_key"],
                name="uniq_temporal_sched_pool_scope",
            ),
        ]


class TemporalSchedulerState(models.Model):
    scheduler = models.CharField(max_length=128)
    region = models.CharField(max_length=32)
    discovery_cursor = models.CharField(max_length=128, default="", db_default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_temporalschedulerstate"
        constraints = [
            models.UniqueConstraint(
                fields=["scheduler", "region"],
                name="uniq_temporal_sched_state_scope",
            ),
        ]


class TemporalSchedulerClaim(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        QUARANTINED = "quarantined", "Quarantined"

    ACTIVE_STATUSES = (Status.RESERVED, Status.CONFIRMED)

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    scheduler = models.CharField(max_length=128)
    region = models.CharField(max_length=32)
    tenant_key = models.CharField(max_length=128)
    occurrence_hash = models.CharField(max_length=64)
    occurrence_key = models.TextField()
    workflow_id = models.CharField(max_length=512)
    claim_token = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices)
    attempt_count = models.PositiveIntegerField(default=1, db_default=1)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="", db_default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_temporalschedulerclaim"
        constraints = [
            models.UniqueConstraint(
                fields=["scheduler", "region", "occurrence_hash"],
                name="uniq_temporal_sched_claim_occurrence",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status="completed", completed_at__isnull=False)
                    | (~models.Q(status="completed") & models.Q(completed_at__isnull=True))
                ),
                name="temporal_sched_claim_completed_at",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=["reserved", "confirmed"], lease_expires_at__isnull=False)
                    | (~models.Q(status__in=["reserved", "confirmed"]) & models.Q(lease_expires_at__isnull=True))
                ),
                name="temporal_sched_claim_lease",
            ),
        ]
        indexes = [
            models.Index(
                fields=["scheduler", "region", "lease_expires_at"],
                condition=models.Q(status__in=["reserved", "confirmed"]),
                name="tsc_active_lease",
            ),
            models.Index(
                fields=["scheduler", "region", "tenant_key", "status"],
                name="tsc_tenant_status",
            ),
            models.Index(
                fields=["scheduler", "region", "status", "updated_at"],
                name="tsc_inactive_cleanup",
            ),
        ]
