from datetime import timedelta

from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class ChangeRequestState(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved (awaiting application)"
    APPLIED = "applied", "Applied"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"
    FAILED = "failed", "Failed to apply"


class ValidationStatus(models.TextChoices):
    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    EXPIRED = "expired", "Expired"
    STALE = "stale", "Stale (resource changed)"


class ChangeRequest(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A pending approval request for a gated action"""

    action_key = models.CharField(max_length=128)
    action_version = models.IntegerField(default=1)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    organization = models.ForeignKey("posthog.Organization", on_delete=models.CASCADE)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=128, null=True, blank=True)

    intent = models.JSONField()
    intent_display = models.JSONField()

    policy_snapshot = models.JSONField()

    validation_status = models.CharField(
        max_length=16,
        choices=ValidationStatus.choices,
        default=ValidationStatus.VALID,
    )
    validation_errors = models.JSONField(null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)

    state = models.CharField(
        max_length=16,
        choices=ChangeRequestState.choices,
        default=ChangeRequestState.PENDING,
    )

    applied_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="change_requests_applied",
    )

    expires_at = models.DateTimeField()
    applied_at = models.DateTimeField(null=True, blank=True)

    apply_error = models.TextField(blank=True)
    result_data = models.JSONField(null=True, blank=True)

    class Meta:
        app_label = "posthog"
        indexes = [
            models.Index(fields=["team", "state"]),
            models.Index(fields=["action_key", "state"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["validation_status", "state"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"ChangeRequest({self.action_key}, {self.state})"


class ApprovalDecision(models.TextChoices):
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class Approval(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A single approval vote on a ChangeRequest"""

    change_request = models.ForeignKey(
        ChangeRequest,
        on_delete=models.CASCADE,
        related_name="approvals",
    )

    decision = models.CharField(
        max_length=16,
        choices=ApprovalDecision.choices,
    )
    reason = models.TextField(blank=True)

    class Meta:
        app_label = "posthog"
        unique_together = [["change_request", "created_by"]]
        indexes = [
            models.Index(fields=["change_request", "decision"]),
        ]

    def __str__(self):
        return f"Approval({self.change_request.action_key}, {self.decision})"


class ApprovalPolicyManager(models.Manager):
    def enabled(self):
        """Return only enabled policies"""
        return self.filter(enabled=True)


class ApprovalPolicy(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """Defines when an action requires approval and who can approve"""

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
    )
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    action_key = models.CharField(max_length=128)

    conditions = models.JSONField(default=dict)

    approver_config = models.JSONField()

    allow_self_approve = models.BooleanField(default=False)
    bypass_roles = models.JSONField(default=list)

    expires_after = models.DurationField(
        default=timedelta(days=14),
        help_text="Auto-expire change requests after this duration",
    )

    enabled = models.BooleanField(default=True)

    objects = ApprovalPolicyManager()

    class Meta:
        app_label = "posthog"
        unique_together = [["organization", "team", "action_key"]]
        indexes = [
            models.Index(fields=["action_key", "enabled"]),
            models.Index(fields=["organization", "enabled"]),
            models.Index(fields=["team", "enabled"]),
        ]
        verbose_name_plural = "Approval policies"

    def __str__(self):
        scope = f"Team {self.team.id}" if self.team else f"Org {self.organization.id}"
        return f"ApprovalPolicy({self.action_key}, {scope})"
