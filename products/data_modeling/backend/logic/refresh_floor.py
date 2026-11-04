"""The `data-modeling-refresh-floor` flag: the finest cadence an organization's plan lets a view refresh at.

The payload names the floor in the same terms as a view's `sync_frequency`, for example
`{"min_interval": "6hour", "clamp_existing": false}`. With `clamp_existing` false only new and
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

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.run_mode import run_mode

from products.data_modeling.backend.logic.freshness import SCHEDULABLE_BUCKETS, format_cadence

logger = structlog.get_logger(__name__)

REFRESH_FLOOR_FLAG = "data-modeling-refresh-floor"

_BUCKETS_BY_NAME = {format_cadence(bucket): bucket for bucket in SCHEDULABLE_BUCKETS} | {"24hour": timedelta(days=1)}


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


def schedule_floor_for_organization(organization: Organization) -> timedelta | None:
    floor = read_organization_plan_refresh_floor(organization).floor
    return floor.schedule_floor if floor is not None else None


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
            person_properties={"organization_plan": organization.billing_plan_label()},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if result is None:
            return PlanRefreshFloorReading(floor=None, evaluated=_no_result_means_no_floor())
        if not result.enabled:
            return PlanRefreshFloorReading(floor=None, evaluated=True)
        return PlanRefreshFloorReading(floor=_parse(result.payload), evaluated=True)
    except InvalidRefreshFloorPayload as error:
        # The payload is typed by hand into the flag, which only checks that it is JSON. Report a value
        # the code cannot use, so the person who set it hears about it.
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
