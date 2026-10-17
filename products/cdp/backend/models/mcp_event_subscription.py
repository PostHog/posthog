from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.utils import UUIDModel, uuid7


class MCPEventSubscription(UUIDModel):
    objects = EnvironmentScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    principal = models.CharField(max_length=255)
    arguments = models.JSONField()
    delivery = EncryptedJSONStringField()
    expires_at = models.DateTimeField()
    active = models.BooleanField(default=False)
    generation = models.UUIDField(default=uuid7)
    verified_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    hog_function = models.OneToOneField(
        "cdp.HogFunction", on_delete=models.SET_NULL, null=True, related_name="mcp_event_subscription"
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["team", "expires_at"], name="cdp_mcp_active_team_expiry_idx", condition=models.Q(active=True)
            ),
            models.Index(fields=["expires_at"], name="cdp_mcp_active_expiry_idx", condition=models.Q(active=True)),
            models.Index(fields=["team", "created_by", "-created_at", "-id"], name="cdp_mcp_owner_created_idx"),
        ]
