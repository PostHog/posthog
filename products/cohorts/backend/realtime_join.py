"""A project joins the realtime cohorts beta when a member opts in. The frontend asks for the join, because
Django never sees the opt-in, and reads back how far the project got."""

from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.instance_setting import get_instance_setting

from products.cohorts.backend.models.realtime_request import (
    RealtimeCohortRequest,
    RealtimeCohortRequestKind,
    RealtimeCohortRequestState,
)
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_enablement import check_enablement
from products.cohorts.backend.realtime_requests import REQUEST_STALE_AFTER, submit_enablement
from products.cohorts.backend.realtime_teams import ACCESS_SNAPSHOT_TTL

# After a refused request, the project reads `refused` and a join files no new request for a week. After a failed
# one, it reads `failed` for an hour. Without the hold, the join that the frontend asks for on every page load of a
# member who opted in would file the same request again each time. A refusal that expires lets a project that
# changed, or a check staff relaxed, take effect with no staff step, at the cost of one resave a week.
REFUSAL_HELD_FOR = timedelta(days=7)
FAILURE_HELD_FOR = timedelta(hours=1)


class RealtimeCohortsJoinState(models.TextChoices):
    SERVING = "serving", "Serving"
    SETTING_UP = "setting_up", "Setting up"
    AVAILABLE = "available", "Available"
    NOT_OPEN = "not_open", "Not open"
    REFUSED = "refused", "Refused"
    FAILED = "failed", "Failed"


@frozen
class JoinFacts:
    # When the project's access row became `serving`. None below `serving`.
    serving_since: datetime | None
    join_open: bool
    # Whether `check_enablement` refuses the project now.
    enablement_refused: bool
    # The project's newest `enable` request.
    last_request: RealtimeCohortRequest | None


def decide_join_state(facts: JoinFacts, now: datetime) -> RealtimeCohortsJoinState:
    if facts.serving_since is not None:
        # Until every web process reads the new row, a cohort request served by another process refuses
        # the project's realtime cohorts.
        if now - facts.serving_since < ACCESS_SNAPSHOT_TTL:
            return RealtimeCohortsJoinState.SETTING_UP
        return RealtimeCohortsJoinState.SERVING
    last_request = facts.last_request
    if last_request is not None and _in_progress(last_request, now):
        return RealtimeCohortsJoinState.SETTING_UP
    # After the two rules above, so that closing the join never hides a project that is in or on its way in.
    if not facts.join_open:
        return RealtimeCohortsJoinState.NOT_OPEN
    if facts.enablement_refused:
        return RealtimeCohortsJoinState.REFUSED
    if last_request is not None and last_request.finished_at is not None:
        ended_ago = now - last_request.finished_at
        if last_request.state == RealtimeCohortRequestState.REFUSED and ended_ago < REFUSAL_HELD_FOR:
            return RealtimeCohortsJoinState.REFUSED
        if last_request.state == RealtimeCohortRequestState.FAILED and ended_ago < FAILURE_HELD_FOR:
            return RealtimeCohortsJoinState.FAILED
    return RealtimeCohortsJoinState.AVAILABLE


def _in_progress(request: RealtimeCohortRequest, now: datetime) -> bool:
    # The same stale rule as `realtime_requests._submit`, which fails a stale request on the next submit.
    since: datetime | None
    match request.state:
        case RealtimeCohortRequestState.QUEUED:
            since = request.created_at
        case RealtimeCohortRequestState.RUNNING:
            since = request.started_at
        case _:
            return False
    return since is not None and now - since < REQUEST_STALE_AFTER


def join_state(team_id: int) -> RealtimeCohortsJoinState:
    return decide_join_state(_join_facts(team_id), timezone.now())


def _join_facts(team_id: int) -> JoinFacts:
    # The request comes first because the task writes `serving` to the row before it marks the request `done`. In
    # the other order, a read that spans both writes sees the old row and the finished request, and decides
    # `available` for a project that just joined.
    last_request = (
        RealtimeCohortRequest.objects.for_team(team_id)
        .filter(kind=RealtimeCohortRequestKind.ENABLE)
        .order_by("-created_at")
        .first()
    )
    row = RealtimeCohortTeamAccess.objects.filter(team_id=team_id).first()
    try:
        check_enablement(team_id, purpose=RealtimeCohortAccessPurpose.BETA)
        enablement_refused = False
    except ValueError:
        enablement_refused = True
    return JoinFacts(
        serving_since=row.changed_at if row is not None and row.level == RealtimeCohortLevel.SERVING else None,
        join_open=get_instance_setting("REALTIME_COHORT_JOIN_OPEN"),
        enablement_refused=enablement_refused,
        last_request=last_request,
    )


def request_join(team_id: int, *, requested_by_id: int) -> bool:
    """Files an `enable` request when the project is `available`. Returns whether it filed one."""
    if join_state(team_id) != RealtimeCohortsJoinState.AVAILABLE:
        return False
    try:
        submit_enablement(
            team_id, requested_by_id=requested_by_id, reason="A member opted into the realtime cohorts beta"
        )
    except ValueError:
        # Another member filed first, or a check changed after the state was read.
        return False
    except Exception as error:
        # The task could not be queued. The submit marked the request `failed`, so the next state read reports it.
        capture_exception(error)
        return False
    return True
