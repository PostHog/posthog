"""Staff requests to enable a team for realtime cohorts or to backfill it, carried out by a Celery task.

`enable` and a team backfill both run ClickHouse scans that can outlast an admin request, so a request
records what staff asked for and the task records how it ended.
"""

from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.cohorts.backend.backfill.runs import (
    check_person_run_preconditions,
    check_run_preconditions,
    create_person_team_backfill_run,
)
from products.cohorts.backend.backfill.sizing import PersonSeedEstimateScanCapExceeded
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.realtime_request import (
    RealtimeCohortRequest,
    RealtimeCohortRequestKind,
    RealtimeCohortRequestState,
)
from products.cohorts.backend.models.team_access import RealtimeCohortAccessPurpose
from products.cohorts.backend.realtime_enablement import (
    AlreadyServing,
    RunFailed,
    RunRefused,
    check_enablement,
    create_behavioral_team_run,
    describe_enablement,
    enable_realtime_cohorts,
)
from products.cohorts.backend.realtime_teams import is_processing_team
from products.cohorts.backend.tasks import REQUEST_TIME_LIMIT, process_realtime_cohort_request

logger = structlog.get_logger(__name__)

# The next submit for the team fails a request that stayed queued or running this long. The threshold is an
# hour past the task's time limit, so the worker of a running request is already dead.
REQUEST_STALE_AFTER = REQUEST_TIME_LIMIT + timedelta(hours=1)


@frozen
class _Outcome:
    state: RealtimeCohortRequestState
    error: str = ""
    detail: str = ""


def submit_enablement(team_id: int, *, requested_by_id: int | None, reason: str) -> RealtimeCohortRequest:
    """Raises ``ValueError``, and writes nothing, when the team cannot be enabled."""
    if check_enablement(team_id, purpose=RealtimeCohortAccessPurpose.BETA) is not None:
        raise ValueError("Already serving realtime cohorts")
    return _submit(
        RealtimeCohortRequest(
            team_id=team_id, kind=RealtimeCohortRequestKind.ENABLE, requested_by_id=requested_by_id, reason=reason
        )
    )


def submit_backfill(
    team_id: int,
    *,
    backfill_kind: CohortBackfillKind,
    cohort_ids: list[int] | None,
    skip_scan_limit: bool,
    requested_by_id: int | None,
) -> RealtimeCohortRequest:
    """Raises ``ValueError``, and writes nothing, when the team's run of that kind cannot be created."""
    if skip_scan_limit and backfill_kind != CohortBackfillKind.BEHAVIORAL:
        raise ValueError("Only a behavioral backfill has a scan limit to skip")
    _check_backfill(team_id, backfill_kind)
    return _submit(
        RealtimeCohortRequest(
            team_id=team_id,
            kind=RealtimeCohortRequestKind.BACKFILL,
            backfill_kind=backfill_kind,
            cohort_ids=cohort_ids,
            skip_scan_limit=skip_scan_limit,
            requested_by_id=requested_by_id,
        )
    )


def _check_backfill(team_id: int, backfill_kind: str) -> None:
    if not is_processing_team(team_id, fresh=True):
        raise ValueError(f"Team {team_id} is not processed by the realtime cohort pipeline")
    # Without them the behavioral creator records a `blocked` run, which holds the team's slot until
    # someone cancels it.
    person = backfill_kind == CohortBackfillKind.PERSON_PROPERTY
    _, missing = check_person_run_preconditions() if person else check_run_preconditions()
    if missing:
        raise ValueError(f"Missing operator attestations: {', '.join(missing)}")


def _submit(request: RealtimeCohortRequest) -> RealtimeCohortRequest:
    now = timezone.now()
    stale_before = now - REQUEST_STALE_AFTER
    try:
        with transaction.atomic():
            RealtimeCohortRequest.objects.for_team(request.team_id).filter(
                Q(state=RealtimeCohortRequestState.QUEUED, created_at__lt=stale_before)
                | Q(state=RealtimeCohortRequestState.RUNNING, started_at__lt=stale_before)
            ).update(
                state=RealtimeCohortRequestState.FAILED,
                error="Did not finish, so a later request replaced it",
                finished_at=now,
            )
            request.save(force_insert=True)
            transaction.on_commit(lambda: _queue(request))
    except IntegrityError as error:
        raise ValueError("This team already has a request in progress") from error
    return request


def _queue(request: RealtimeCohortRequest) -> None:
    try:
        process_realtime_cohort_request.delay(team_id=request.team_id, request_id=str(request.id))
    except Exception:
        # Otherwise the row stays `queued`, and every submit for the team fails until the row goes stale.
        RealtimeCohortRequest.objects.for_team(request.team_id).filter(
            id=request.id, state=RealtimeCohortRequestState.QUEUED
        ).update(
            state=RealtimeCohortRequestState.FAILED,
            error="Could not queue the task. Submit the request again.",
            finished_at=timezone.now(),
        )
        raise


def process_request(team_id: int, request_id: UUID) -> None:
    requests = RealtimeCohortRequest.objects.for_team(team_id)
    # A second delivery of the same message finds the request claimed.
    claimed = requests.filter(id=request_id, state=RealtimeCohortRequestState.QUEUED).update(
        state=RealtimeCohortRequestState.RUNNING, started_at=timezone.now()
    )
    if not claimed:
        return
    request = requests.get(id=request_id)
    try:
        outcome = _enable(team_id) if request.kind == RealtimeCohortRequestKind.ENABLE else _backfill(request)
    except Exception as error:
        logger.exception("realtime_cohort_request_failed", team_id=team_id, request_id=str(request_id))
        outcome = _Outcome(state=RealtimeCohortRequestState.FAILED, error=str(error))
    requests.filter(id=request_id).update(
        state=outcome.state, error=outcome.error, detail=outcome.detail, finished_at=timezone.now()
    )


def _enable(team_id: int) -> _Outcome:
    try:
        result = enable_realtime_cohorts(team_id, purpose=RealtimeCohortAccessPurpose.BETA)
    except ValueError as error:
        return _Outcome(state=RealtimeCohortRequestState.REFUSED, error=str(error))
    if isinstance(result, AlreadyServing):
        return _Outcome(state=RealtimeCohortRequestState.DONE, detail=f"Team {team_id}: already serving")
    detail = "\n".join(describe_enablement(team_id, result))
    for kind, outcome in (("Behavioral", result.behavioral), ("Person", result.person)):
        if isinstance(outcome, RunRefused | RunFailed):
            state = (
                RealtimeCohortRequestState.FAILED
                if isinstance(outcome, RunFailed)
                else RealtimeCohortRequestState.REFUSED
            )
            return _Outcome(state=state, error=f"{kind} run {state.value}: {outcome.reason}", detail=detail)
    # A later request finds the team serving and does nothing, so it cannot repair this.
    warning = (
        "The flags cache rebuild was not enqueued. Enqueue update_team_flags_cache and "
        "update_team_service_flags_cache for this team."
        if result.resave.rebuild_dispatch_failed
        else ""
    )
    return _Outcome(state=RealtimeCohortRequestState.DONE, error=warning, detail=detail)


def _backfill(request: RealtimeCohortRequest) -> _Outcome:
    assert request.backfill_kind is not None, "cohort_rtr_backfill_kind_ck sets it on every backfill request"
    try:
        # Again, because the settings can change between the submit and the task.
        _check_backfill(request.team_id, request.backfill_kind)
        if request.backfill_kind == CohortBackfillKind.BEHAVIORAL:
            run = create_behavioral_team_run(
                request.team_id,
                cohort_ids=request.cohort_ids,
                max_events_per_day=0
                if request.skip_scan_limit
                else settings.BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY,
                created_by_id=request.requested_by_id,
            )
        else:
            run = create_person_team_backfill_run(
                request.team_id,
                CohortBackfillTrigger.TEAM_ENABLEMENT,
                settings.BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS,
                request.cohort_ids,
                created_by_id=request.requested_by_id,
            )
    except (ValueError, PersonSeedEstimateScanCapExceeded) as error:
        return _Outcome(state=RealtimeCohortRequestState.REFUSED, error=str(error))
    except IntegrityError:
        return _Outcome(
            state=RealtimeCohortRequestState.REFUSED,
            error=f"Team {request.team_id} already has an active team backfill run ({request.backfill_kind})",
        )
    return _Outcome(state=RealtimeCohortRequestState.DONE, detail=f"Created run {run.id}")
