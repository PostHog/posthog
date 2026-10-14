from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, uuid7


class MCPEventSubscription(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False)
    principal = models.CharField(max_length=255)
    arguments = models.JSONField()
    delivery = EncryptedJSONStringField()
    expires_at = models.DateTimeField(db_index=True)
    active = models.BooleanField(default=False)
    generation = models.UUIDField(default=uuid7)
    verified_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    hog_function = models.OneToOneField(
        "cdp.HogFunction", on_delete=models.SET_NULL, null=True, related_name="mcp_event_subscription"
    )
