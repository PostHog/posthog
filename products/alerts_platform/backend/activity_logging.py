"""Activity-log receiver for platform alert configurations.

Kept free of API and query-runner imports, because `ready()` connects it in every process.
"""

from typing import Any, cast

from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.models import PlatformAlertConfiguration


@mutable_receiver(model_activity_signal, sender=PlatformAlertConfiguration)
def handle_platform_alert_configuration_activity(
    sender: Any,
    scope: str,
    before_update: PlatformAlertConfiguration | None,
    after_update: PlatformAlertConfiguration | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    # A copy its source owns repeats the source's row, which the source logs on its own scope.
    if instance is None or instance.owner != PlatformAlertOwner.PLATFORM:
        return
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
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
