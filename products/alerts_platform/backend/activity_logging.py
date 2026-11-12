"""Activity-log receiver for platform alert configurations.

Kept free of API and query-runner imports, because `ready()` connects it in every process.
"""

import dataclasses
from typing import Any, cast

from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityScope,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic import source_configs
from products.alerts_platform.backend.models import PlatformAlertConfiguration


@dataclasses.dataclass(frozen=True)
class PlatformAlertConfigurationContext(ActivityContextBase):
    source_kind: str
    # The id the source's pages know the alert by, which differs from `item_id` for a copy of a source row.
    alert_id: str
    # What the alert watches in its source's product, such as an insight's short id and name.
    source_id: str | None = None
    source_name: str | None = None


def _context(instance: PlatformAlertConfiguration) -> PlatformAlertConfigurationContext:
    spec = source_configs.spec(SourceKind(instance.source_kind))
    lookup = spec.activity_source if spec is not None else None
    source = lookup(instance.team_id, instance.source_config) if lookup is not None else None
    return PlatformAlertConfigurationContext(
        source_kind=instance.source_kind,
        alert_id=str(instance.destination_alert_id),
        source_id=source.id if source is not None else None,
        source_name=source.name if source is not None else None,
    )


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
            context=_context(instance),
        ),
    )
