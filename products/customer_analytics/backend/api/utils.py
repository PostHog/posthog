from typing import Optional, cast

from loginas.utils import is_impersonated_session

from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, changes_between, log_activity

from products.customer_analytics.backend.models import CustomerProfileConfig


def log_customer_profile_config_activity(
    viewset,
    instance: CustomerProfileConfig,
    activity: str,
    previous: Optional[CustomerProfileConfig] = None,
) -> None:
    name = f"{instance.scope} (ID: {instance.id})"
    changes = changes_between("CustomerProfileConfig", previous=previous, current=instance)
    detail = Detail(name=name, changes=changes)
    log_activity(
        organization_id=viewset.organization.id,
        team_id=viewset.team.id,
        user=cast(User, viewset.request.user),
        was_impersonated=is_impersonated_session(viewset.request),
        item_id=str(instance.id),
        scope="CustomerProfileConfig",
        activity=activity,
        detail=detail,
    )
