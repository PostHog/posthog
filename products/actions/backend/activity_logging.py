# Activity-log receivers, kept in a module with no API/query-runner imports so
# AppConfig.ready() can wire them cheaply in every process type (celery, temporal,
# migrate) without pulling the viewset import graph into django.setup().

from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.actions.backend.models.action import Action


@mutable_receiver(model_activity_signal, sender=Action)
def handle_action_change(
    sender, scope, before_update, after_update, activity, was_impersonated=False, **kwargs
) -> None:
    # Detect soft delete/restore by checking the deleted field
    if before_update and after_update:
        if not before_update.deleted and after_update.deleted:
            # Soft deleted
            activity = "deleted"
        elif before_update.deleted and not after_update.deleted:
            # Restored from soft delete
            activity = "updated"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.created_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
        ),
    )
