from uuid import uuid4

from django.db import models

from posthog.helpers.encrypted_fields import EncryptedTextField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class AccountAuditCredential(models.Model):
    public_key_id = models.UUIDField(default=uuid4, unique=True, editable=False)
    signing_secret = EncryptedTextField()
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, db_constraint=False, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AccountAuditAdmission(TeamScopedRootMixin):
    credential = models.ForeignKey(AccountAuditCredential, on_delete=models.PROTECT, related_name="admissions")
    webhook_id = models.CharField(max_length=255)
    organization_id = models.UUIDField()
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    reason = models.CharField(max_length=500, default="", db_default="")
    skill_project = models.BigIntegerField(null=True)
    skill_name = models.CharField(max_length=64, default="account-audit", db_default="account-audit")
    task_run_id = models.UUIDField(unique=True)
    notebook_short_id = models.CharField(max_length=12)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["credential", "webhook_id"], name="account_audit_admission_delivery"),
        ]
