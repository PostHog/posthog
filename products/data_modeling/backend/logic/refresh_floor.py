"""The `data-modeling-refresh-floor` flag: the finest cadence an organization's plan lets a view refresh at.

The payload names the floor in the same terms as a view's `sync_frequency`, for example
`{"min_interval": "6hour", "clamp_existing": false}`. With `clamp_existing` false only new and
changed cadences are held to the floor, and views already set faster keep running at their setting.
With it true the scheduler also runs those views at the floor. A view's saved cadence is never
rewritten in either case, so turning the flag off restores every schedule.
"""

import json
import dataclasses
from datetime import timedelta

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization

from products.data_modeling.backend.logic.freshness import SCHEDULABLE_BUCKETS, format_cadence

logger = structlog.get_logger(__name__)

REFRESH_FLOOR_FLAG = "data-modeling-refresh-floor"

_BUCKETS_BY_NAME = {format_cadence(bucket): bucket for bucket in SCHEDULABLE_BUCKETS}


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class PlanRefreshFloor:
    min_interval: timedelta
    clamp_existing: bool

    @property
    def schedule_floor(self) -> timedelta | None:
        """The floor the scheduler applies, or None while views set faster keep their cadence."""
        return self.min_interval if self.clamp_existing else None


class InvalidRefreshFloorPayload(ValueError):
    pass


def plan_refresh_floor_for_team(team_id: int) -> PlanRefreshFloor | None:
    """The plan floor of the team's organization. See `plan_refresh_floor`."""
    organization = Organization.objects.filter(team__id=team_id).first()
    return plan_refresh_floor(organization) if organization is not None else None


def plan_refresh_floor(organization: Organization) -> PlanRefreshFloor | None:
    """The organization's plan floor, or None when its plan sets none.

    Evaluated locally on the organization, so the bounds read and every reconcile can call it without
    a network round trip. Never raises: a flag outage or a bad payload reads as no floor, which only
    keeps today's cadences.
    """
    organization_id = str(organization.id)
    try:
        result = posthoganalytics.get_feature_flag_result(
            REFRESH_FLOOR_FLAG,
            organization_id,
            groups={"organization": organization_id},
            person_properties={"organization_plan": organization.billing_plan_label()},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if result is None or not result.enabled:
            return None
        return _parse(result.payload)
    except InvalidRefreshFloorPayload as error:
        # The payload is typed by hand into the flag, which only checks that it is JSON. Report a value
        # the code cannot use, so the person who set it hears about it.
        capture_exception(error, {"flag": REFRESH_FLOOR_FLAG, "organization_id": organization_id})
        return None
    except Exception:
        logger.warning("refresh_floor_flag_evaluation_failed", organization_id=organization_id, exc_info=True)
        return None


def _parse(payload: object) -> PlanRefreshFloor:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise InvalidRefreshFloorPayload("payload is not JSON") from error
    if not isinstance(payload, dict):
        raise InvalidRefreshFloorPayload(f"payload must be an object, got {payload!r}")
    name = payload.get("min_interval")
    min_interval = _BUCKETS_BY_NAME.get(name) if isinstance(name, str) else None
    if min_interval is None:
        raise InvalidRefreshFloorPayload(f"min_interval must be one of {sorted(_BUCKETS_BY_NAME)}, got {name!r}")
    clamp_existing = payload.get("clamp_existing", False)
    if not isinstance(clamp_existing, bool):
        raise InvalidRefreshFloorPayload(f"clamp_existing must be a boolean, got {clamp_existing!r}")
    return PlanRefreshFloor(min_interval=min_interval, clamp_existing=clamp_existing)
