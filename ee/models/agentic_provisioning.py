from django.db import models

from posthog.models.utils import UUIDModel


class AgenticProvisioningState(UUIDModel):
    class Purpose(models.TextChoices):
        PENDING_AUTH = "pending_auth"
        AUTH_CODE = "auth_code"
        DEEP_LINK = "deep_link"
        RESOURCE_SERVICE = "resource_service"

    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    token = models.CharField(max_length=255, unique=True, db_index=True)
    payload = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["purpose", "expires_at"], name="idx_agentic_state_purpose_exp"),
        ]
