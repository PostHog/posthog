"""Activity log wiring for cross_project_dashboards.

Rows are written against the organization with no team, which `ActivityLog` allows: its
constraint requires a team id or an organization id, not both.

Lives here rather than in the viewset so the receiver connects in every process, including the
ones that mutate dashboards outside a web request.
"""

from typing import Any, cast

from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.cross_project_dashboards.backend.models import CrossProjectDashboard


@mutable_receiver(model_activity_signal, sender=CrossProjectDashboard)
def handle_cross_project_dashboard_change(
    sender: Any,
    scope: str,
    before_update: CrossProjectDashboard | None,
    after_update: CrossProjectDashboard | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    log_activity(
        organization_id=instance.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(cast(ActivityScope, scope), previous=before_update, current=after_update),
            name=instance.name,
        ),
    )
