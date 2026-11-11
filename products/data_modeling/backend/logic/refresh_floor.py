"""The finest cadence an organization's plan lets a view refresh at.

Billing sets the floor per plan as the `limit`, in minutes, of the `data_modeling_refresh_interval` product
feature. An organization without that feature has no floor. The `data-modeling-refresh-floor` flag rolls the
floor out, and no floor applies while it is off for an organization or can't be read.

The flag payload, for example `{"clamp_existing": true}`, decides what happens to views already set faster
than the floor. With `clamp_existing` false or missing, the floor refuses new and faster cadences only, and
views already set faster keep running at their setting. With it true the scheduler also runs those views at
the floor, and an endpoint keeps serving such a view's table for the floor's interval. A view's saved cadence
is never rewritten, so turning the flag off restores every schedule. The hourly drift sweep moves running
schedules after a flag or plan change.
"""

import json
import dataclasses
from datetime import timedelta

import structlog
import posthoganalytics

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization

from products.data_modeling.backend.logic.freshness import nearest_schedulable_bucket_at_least

logger = structlog.get_logger(__name__)

REFRESH_FLOOR_FLAG = "data-modeling-refresh-floor"

# An endpoint's freshness stops at seven days, so a coarser floor would leave its materialization no cadence to pick.
_COARSEST_FLOOR = timedelta(days=7)


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class PlanRefreshFloor:
    min_interval: timedelta
    clamp_existing: bool

    @property
    def schedule_floor(self) -> timedelta | None:
        """The floor the scheduler applies, or None while views set faster keep their cadence."""
        return self.min_interval if self.clamp_existing else None


def read_plan_refresh_floor(team_id: int) -> PlanRefreshFloor | None:
    organization = Organization.objects.filter(team__id=team_id).first()
    return organization_plan_refresh_floor(organization) if organization is not None else None


def schedule_floor_for_organization(organization: Organization) -> timedelta | None:
    floor = organization_plan_refresh_floor(organization)
    return floor.schedule_floor if floor is not None else None


def plan_limit(organization: Organization) -> timedelta | None:
    """The plan's floor whether or not the flag applies it, or None when the plan sets none."""
    feature = organization.get_available_feature(AvailableFeature.DATA_MODELING_REFRESH_INTERVAL)
    minutes = feature.get("limit") if feature else None
    if minutes is None:
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        logger.warning("refresh_floor_limit_invalid", organization_id=str(organization.id), limit=minutes)
        return None
    return min(nearest_schedulable_bucket_at_least(timedelta(minutes=minutes)), _COARSEST_FLOOR)


def organization_plan_refresh_floor(organization: Organization) -> PlanRefreshFloor | None:
    min_interval = plan_limit(organization)
    if min_interval is None:
        return None
    organization_id = str(organization.id)
    try:
        result = posthoganalytics.get_feature_flag_result(
            REFRESH_FLOOR_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("refresh_floor_flag_evaluation_failed", organization_id=organization_id, exc_info=True)
        return None
    if result is None or not result.enabled:
        return None
    return PlanRefreshFloor(min_interval=min_interval, clamp_existing=_clamp_existing(result.payload, organization_id))


def _clamp_existing(payload: object, organization_id: str) -> bool:
    if payload is None:
        return False
    try:
        parsed = json.loads(payload) if isinstance(payload, str) else payload
    except ValueError:
        parsed = None
    clamp_existing = parsed.get("clamp_existing", False) if isinstance(parsed, dict) else None
    if not isinstance(clamp_existing, bool):
        logger.warning("refresh_floor_payload_invalid", organization_id=organization_id, payload=payload)
        return False
    return clamp_existing
