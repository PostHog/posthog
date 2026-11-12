"""The finest cadence an organization's plan lets a view be set to refresh at.

Billing sets the floor per plan as the `limit`, in minutes, of the `data_modeling_refresh_interval` product
feature. An organization without that feature has no floor. The `data-modeling-refresh-floor` flag rolls the
floor out, and no floor applies while it is off for an organization or can't be read.

The floor refuses new and faster cadences. An hourly task rewrites a cadence saved finer than the floor to the floor.
"""

from datetime import timedelta

import structlog

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization
from posthog.ph_client import feature_enabled_or_false

from products.data_modeling.backend.logic.freshness import nearest_schedulable_bucket_at_least

logger = structlog.get_logger(__name__)

REFRESH_FLOOR_FLAG = "data-modeling-refresh-floor"

# An endpoint's freshness stops at seven days, so a coarser floor would leave its materialization no cadence to pick.
MAX_PLAN_REFRESH_FLOOR = timedelta(days=7)


def read_plan_refresh_floor(team_id: int) -> timedelta | None:
    organization = Organization.objects.filter(team__id=team_id).first()
    return organization_plan_refresh_floor(organization) if organization is not None else None


def organization_plan_refresh_floor(organization: Organization) -> timedelta | None:
    feature = organization.get_available_feature(AvailableFeature.DATA_MODELING_REFRESH_INTERVAL)
    minutes = feature.get("limit") if feature else None
    if minutes is None:
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        logger.warning("refresh_floor_limit_invalid", organization_id=str(organization.id), limit=minutes)
        return None
    organization_id = str(organization.id)
    if not feature_enabled_or_false(
        REFRESH_FLOOR_FLAG,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    ):
        return None
    return min(nearest_schedulable_bucket_at_least(timedelta(minutes=minutes)), MAX_PLAN_REFRESH_FLOOR)
