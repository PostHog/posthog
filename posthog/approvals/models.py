from datetime import timedelta
from typing import TYPE_CHECKING, Optional

from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

if TYPE_CHECKING:
    from posthog.approvals.actions.base import BaseAction
    from posthog.approvals.models import ApprovalPolicy as ApprovalPolicyType


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

    def get_policy(self) -> Optional["ApprovalPolicyType"]:
        """Get the matching approval policy for this change request."""
        from posthog.approvals.policies import PolicyEngine

        return PolicyEngine().get_policy(self.action_key, self.team, self.organization)

    def get_action_class(self) -> Optional[type["BaseAction"]]:
        """Get the action class for this change request from the registry."""
        from posthog.approvals.actions.registry import get_action

        return get_action(self.action_key)


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

    bypass_org_membership_levels = models.JSONField(default=list)

    bypass_roles = models.ManyToManyField(
        "ee.Role",
        blank=True,
        related_name="bypass_policies",
    )

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

    def set_bypass_roles(self, role_ids: list[str]) -> None:
        """Set bypass roles with validation that they belong to the same organization."""
        if not role_ids:
            self.bypass_roles.clear()
            return

        try:
            from ee.models.rbac.role import Role
        except ImportError:
            pass
        else:
            roles = Role.objects.filter(id__in=role_ids)
            invalid_roles = [r for r in roles if r.organization_id != self.organization_id]
            if invalid_roles:
                invalid_names = [r.name for r in invalid_roles]
                raise ValueError(f"Roles must belong to the same organization: {', '.join(invalid_names)}")

            self.bypass_roles.set(roles)

    def get_approver_user_ids(self) -> list[int]:
        """Get list of user IDs who can approve based on this policy's approver_config."""
        user_ids: set[int] = set()

        if "users" in self.approver_config:
            user_ids.update(self.approver_config["users"])

        approver_roles = self.approver_config.get("roles")
        if approver_roles:
            try:
                from ee.models.rbac.role import RoleMembership

                role_user_ids = RoleMembership.objects.filter(
                    role_id__in=approver_roles,
                    role__organization=self.organization,
                ).values_list("user_id", flat=True)
                user_ids.update(role_user_ids)
            except ImportError:
                pass

        return list(user_ids)
