# Activity-log receivers, kept in a module with no API/query-runner imports so
# AppConfig.ready() can wire them cheaply in every process type (celery, temporal,
# migrate) without pulling the viewset import graph into django.setup().

import dataclasses
from typing import Optional

from django.db.models.signals import post_save
from django.dispatch import receiver

from posthog.event_usage import report_user_action
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.annotations.backend.models.annotation import Annotation


@dataclasses.dataclass(frozen=True)
class AnnotationContext(ActivityContextBase):
    scope: str
    dashboard_id: Optional[int] = None
    dashboard_name: Optional[str] = None
    dashboard_item_id: Optional[int] = None
    dashboard_item_short_id: Optional[str] = None
    dashboard_item_name: Optional[str] = None
    recording_id: Optional[str] = None


@receiver(post_save, sender=Annotation, dispatch_uid="hook-annotation-created")
def annotation_created(sender, instance, created, raw, using, **kwargs):
    if instance.created_by:
        event_name: str = "annotation created" if created else "annotation updated"
        report_user_action(instance.created_by, event_name, instance.get_analytics_metadata())


@mutable_receiver(model_activity_signal, sender=Annotation)
def handle_annotation_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    context = AnnotationContext(
        scope=after_update.scope,
        dashboard_id=after_update.dashboard_id,
        dashboard_name=after_update.dashboard_name,
        dashboard_item_id=after_update.dashboard_item_id,
        dashboard_item_short_id=after_update.insight_short_id,
        dashboard_item_name=after_update.insight_name,
        recording_id=after_update.recording_id,
    )

    log_activity(
        organization_id=after_update.organization_id or after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.content,
            context=context,
        ),
    )
