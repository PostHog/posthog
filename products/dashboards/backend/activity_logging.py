from typing import Any, cast

from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_widget import DashboardWidget

# Lives here, not in api/dashboard.py, so these can wire at AppConfig.ready() without dragging the
# dashboard viewset (which pulls scipy via the error-tracking widget query runners) onto the
# django.setup() path. Dashboards are mutated outside web requests, so the audit log must connect
# in every process.


@mutable_receiver(model_activity_signal, sender=DashboardWidget)
def handle_dashboard_widget_change(
    sender: Any,
    scope: str,
    before_update: DashboardWidget | None,
    after_update: DashboardWidget | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    organization_id = Team.objects.values_list("organization_id", flat=True).filter(pk=instance.team_id).first()
    log_activity(
        organization_id=organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(cast(ActivityScope, scope), previous=before_update, current=after_update),
            name=instance.name or instance.widget_type,
        ),
    )


@mutable_receiver(model_activity_signal, sender=Dashboard)
def handle_dashboard_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    if before_update and after_update:
        before_deleted = getattr(before_update, "deleted", None)
        after_deleted = getattr(after_update, "deleted", None)
        if before_deleted is not None and after_deleted is not None and before_deleted != after_deleted:
            activity = "restored" if after_deleted is False else "deleted"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
            type="dashboard",
        ),
    )
