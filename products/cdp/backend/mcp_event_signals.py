from django.db.models.signals import post_delete
from django.dispatch import receiver

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription
from products.cdp.backend.tasks.mcp_events import reload_mcp_destinations_after_commit


@receiver(post_delete, sender=MCPEventSubscription)
def disable_mcp_event_destination(
    sender: type[MCPEventSubscription], instance: MCPEventSubscription, **kwargs: object
) -> None:
    if instance.hog_function_id is None:
        return
    HogFunction.objects.filter(team_id=instance.team_id, id=instance.hog_function_id).update(
        enabled=False, encrypted_inputs={}
    )
    reload_mcp_destinations_after_commit(team_id=instance.team_id, hog_function_ids=[str(instance.hog_function_id)])
