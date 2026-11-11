"""The finest cadence an organization's plan lets a view refresh at.

Billing sets the floor per plan as the `limit`, in minutes, of the `data_modeling_refresh_interval` product
feature. An organization without that feature has no floor. The `data-modeling-refresh-floor` flag rolls the
floor out, and no floor applies while it is off for an organization.

The flag payload, for example `{"clamp_existing": false}`, decides what happens to views already set faster
than the floor. With `clamp_existing` false only new and
changed cadences are held to the floor, and views already set faster keep running at their setting.
With it true the scheduler also runs those views at the floor, and an endpoint keeps serving such a
view's table for the floor's interval, because the table cannot refresh sooner. A view's saved cadence
is never rewritten in either case, so turning the flag off restores every schedule.
"""

import json
import dataclasses
from datetime import timedelta

import structlog
import posthoganalytics

from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.run_mode import run_mode

from products.data_modeling.backend.logic.freshness import SCHEDULABLE_BUCKETS

logger = structlog.get_logger(__name__)

REFRESH_FLOOR_FLAG = "data-modeling-refresh-floor"

# An endpoint's freshness stops at seven days, so a coarser floor would leave its materialization no cadence to pick.
_COARSEST_FLOOR = timedelta(days=7)
_FLOOR_MINUTES = sorted(
    int(bucket.total_seconds()) // 60 for bucket in SCHEDULABLE_BUCKETS if bucket <= _COARSEST_FLOOR
)

_reported_floor_errors: set[str] = set()


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class PlanRefreshFloor:
    min_interval: timedelta
    clamp_existing: bool

    @property
    def schedule_floor(self) -> timedelta | None:
        """The floor the scheduler applies, or None while views set faster keep their cadence."""
        return self.min_interval if self.clamp_existing else None


class InvalidRefreshFloor(ValueError):
    pass


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class PlanRefreshFloorReading:
    floor: PlanRefreshFloor | None
    evaluated: bool


def read_plan_refresh_floor(team_id: int) -> PlanRefreshFloorReading:
    """The plan floor of the team's organization. See `read_organization_plan_refresh_floor`."""
    organization = Organization.objects.filter(team__id=team_id).first()
    if organization is None:
        return PlanRefreshFloorReading(floor=None, evaluated=True)
    return read_organization_plan_refresh_floor(organization)


def read_organization_plan_refresh_floor(organization: Organization) -> PlanRefreshFloorReading:
    """Read the organization's plan floor without raising.

    Evaluated locally on the organization, so the bounds read and every reconcile can call it without
    a network round trip.
    """
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
        if result is None:
            return PlanRefreshFloorReading(floor=None, evaluated=_no_result_means_no_floor())
        if not result.enabled:
            return PlanRefreshFloorReading(floor=None, evaluated=True)
        min_interval = _plan_min_interval(organization)
        if min_interval is None:
            return PlanRefreshFloorReading(floor=None, evaluated=True)
        return PlanRefreshFloorReading(
            floor=PlanRefreshFloor(min_interval=min_interval, clamp_existing=_clamp_existing(result.payload)),
            evaluated=True,
        )
    except InvalidRefreshFloor as error:
        # The flag payload and the billing feature limit are both set by hand, and neither is checked against
        # the cadences a view can run at. Report a value the code cannot use, so the person who set it hears
        # about it. Every graph build reads the floor, so each bad value is reported once per process.
        if str(error) not in _reported_floor_errors:
            _reported_floor_errors.add(str(error))
            capture_exception(error, {"flag": REFRESH_FLOOR_FLAG, "organization_id": organization_id})
        return PlanRefreshFloorReading(floor=None, evaluated=False)
    except Exception:
        logger.warning("refresh_floor_flag_evaluation_failed", organization_id=organization_id, exc_info=True)
        return PlanRefreshFloorReading(floor=None, evaluated=False)


def _no_result_means_no_floor() -> bool:
    """Tell an instance with no floor from a failed read, because the SDK returns no result for both.

    On deployed cloud, a process with the SDK enabled but no definitions failed to load them, so a
    reconcile could speed up a schedule the floor holds back. Self-hosted instances and E2E stacks may
    never load definitions, and a disabled SDK returns no result for every flag.

    With definitions loaded, no result means the flag was deleted or its conditions need data this
    read does not send. That reads as no floor, so that one flag edit cannot block saves and
    reconciles for every organization until someone edits it again.
    """
    if not run_mode().is_deployed_cloud or posthoganalytics.disabled:
        return True
    definitions = posthoganalytics.feature_flag_definitions()
    if not definitions:
        return False
    if any(flag.get("key") == REFRESH_FLOOR_FLAG for flag in definitions):
        logger.warning("refresh_floor_flag_inconclusive", flag=REFRESH_FLOOR_FLAG)
    return True


def _plan_min_interval(organization: Organization) -> timedelta | None:
    feature = organization.get_available_feature(AvailableFeature.DATA_MODELING_REFRESH_INTERVAL)
    minutes = feature.get("limit") if feature else None
    if minutes is None:
        return None
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes not in _FLOOR_MINUTES:
        raise InvalidRefreshFloor(
            f"{AvailableFeature.DATA_MODELING_REFRESH_INTERVAL} limit must be one of {_FLOOR_MINUTES} minutes, got {minutes!r}"
        )
    return timedelta(minutes=minutes)


def _clamp_existing(payload: object) -> bool:
    if payload is None:
        return False
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise InvalidRefreshFloor("payload is not JSON") from error
    if not isinstance(payload, dict):
        raise InvalidRefreshFloor(f"payload must be an object, got {payload!r}")
    clamp_existing = payload.get("clamp_existing", False)
    if not isinstance(clamp_existing, bool):
        raise InvalidRefreshFloor(f"clamp_existing must be a boolean, got {clamp_existing!r}")
    return clamp_existing
