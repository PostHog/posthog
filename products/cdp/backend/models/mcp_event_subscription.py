from functools import partial

from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, uuid7
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class MCPEventSubscription(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False)
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
            models.Index(fields=["expires_at"], name="cdp_mcp_active_expiry_idx", condition=models.Q(active=True))
        ]


@receiver(post_delete, sender=MCPEventSubscription)
def disable_mcp_event_destination(
    sender: type[MCPEventSubscription], instance: MCPEventSubscription, **kwargs: object
) -> None:
    if instance.hog_function_id is None:
        return
    HogFunction.objects.filter(team_id=instance.team_id, id=instance.hog_function_id).update(
        enabled=False, encrypted_inputs={}
    )
    transaction.on_commit(
        partial(
            reload_hog_functions_on_workers,
            team_id=instance.team_id,
            hog_function_ids=[str(instance.hog_function_id)],
        )
    )
