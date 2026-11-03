"""The investigation agent's decision and claim for an insight alert the platform evaluates.

The same rules as the insight stack's own (`posthog/temporal/alerts/investigation.py`), read from
`InsightAlertInvestigation` instead of `AlertCheck`. An episode is one firing, named by the
platform's `episode_started_at`, rather than a run of FIRING checks.

The decision is a read, so it can run inside an evaluation that a retry repeats. The claim is the
write, and runs once the evaluation is recorded.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from django.db import connection, transaction

import structlog

from posthog.schema import AlertState as InsightAlertState

from posthog.dataclasses import frozen
from posthog.tasks.alerts.metrics_investigation import investigate_metrics_alert, should_investigate_metrics_alert
from posthog.temporal.alerts.investigation import (
    InvestigationDecision,
    carried_verdict_suppresses,
    decide_within_budget,
    investigates,
    refusing_investigations,
)

from products.alerts.backend.investigation_episode import STARTED_INVESTIGATION_STATUSES
from products.alerts.backend.investigation_release import (
    RUNNING_HOLD,
    earlier_in_episode,
    last_verdict,
    previous_verdict_in_episode,
    release_held,
)
from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_investigation_detail import (
    INVESTIGATION_REQUESTED_KEY,
    METRICS_INVESTIGATION_REQUESTED_KEY,
    InvestigationClaims,
    InvestigationStart,
    RequestedInvestigation,
    requested_investigation,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    HeldDelivery,
    HeldDeliveryAddress,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
)
from products.alerts_platform.backend.facade.enums import HoldReleasedBy
from products.alerts_platform.backend.facade.lifecycle import AlertState, NotificationAction

logger = structlog.get_logger(__name__)

_CLAIM_LOCK_SQL: Final = "SELECT pg_advisory_xact_lock(hashtext(%s))"
HOLD_REASON: Final = "investigation"
_EVALUATED_KEYS: Final = ("anomaly_scores", "triggered_points", "triggered_dates", "interval", "triggered_metadata")


@frozen
class InvestigationClaim:
    investigation_id: UUID
    # False when an investigation in flight or inside the cooldown refused it.
    claimed: bool


def decide_investigation(
    alert: AlertConfiguration,
    *,
    firing: bool,
    configuration_id: UUID,
    evaluation_key: str,
    episode_started_at: datetime | None,
) -> InvestigationDecision:
    """Whether this evaluation gets an investigation, and the firing's last verdict so far.

    `firing` is whether the evaluation left the group firing, which the platform's state names
    differently from the insight stack's.

    The cooldown and the in-flight check belong to the claim, which takes a lock for them.
    """
    if not investigates(alert, firing=firing):
        return InvestigationDecision()
    earlier = earlier_in_episode(alert.team_id, configuration_id, episode_started_at, evaluation_key)
    return decide_within_budget(
        started=sum(status in STARTED_INVESTIGATION_STATUSES for status, _ in earlier),
        previous_verdict=last_verdict(earlier),
    )


def claim_investigation(
    alert: AlertConfiguration,
    *,
    configuration_id: UUID,
    evaluation_key: str,
    episode_started_at: datetime | None,
    kind: InsightAlertInvestigation.Kind,
    evaluated: dict[str, Any],
) -> InvestigationClaim:
    """Records this evaluation's investigation, PENDING when it may run and SKIPPED when it may not.

    Refused by an investigation of the same alert that is still in flight, up to the horizon past
    which it is presumed dead, or one that finished inside the cooldown. The lock serializes two
    claims for one alert, so both cannot pass the check. A repeated claim returns the first one's
    answer, so a retry starts the same agent rather than a second.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(_CLAIM_LOCK_SQL, [f"insight-alert-investigation:{configuration_id}"])
        rows = InsightAlertInvestigation.objects.for_team(alert.team_id).filter(configuration_id=configuration_id)
        existing = rows.filter(evaluation_key=evaluation_key).first()
        if existing is not None:
            return InvestigationClaim(
                investigation_id=existing.id, claimed=existing.status != InvestigationStatus.SKIPPED
            )
        refused = rows.filter(refusing_investigations(alert, datetime.now(UTC), status_field="status")).exists()
        investigation = InsightAlertInvestigation.objects.for_team(alert.team_id).create(
            team_id=alert.team_id,
            alert_configuration=alert,
            configuration_id=configuration_id,
            evaluation_key=evaluation_key,
            episode_started_at=episode_started_at,
            kind=kind,
            status=InvestigationStatus.SKIPPED if refused else InvestigationStatus.PENDING,
            evaluated=evaluated,
        )
    return InvestigationClaim(investigation_id=investigation.id, claimed=not refused)


def with_investigation(check: PlatformAlertCheckInput, evaluation: SourceBatchEvaluation) -> SourceBatchEvaluation:
    """The evaluation of a check the platform owns, with the insight stack's investigation rules applied.

    A firing the agent investigates asks for its claim in `source_detail`, and a gated alert holds the
    firing's delivery until the verdict. A firing past the budget is muted when the firing's last
    verdict suppresses it. A metrics alert's firing asks for its metrics investigation, which holds
    nothing. Only an owned check, because a parallel run must never pay for an agent run.
    """
    if not check.owned_by_platform or check.legacy_configuration_id is None or len(evaluation.outcomes) != 1:
        return evaluation
    outcome = evaluation.outcomes[0]
    if len(outcome.groups) != 1 or outcome.groups[0].new_state != AlertState.FIRING.value:
        return evaluation
    alert = (
        AlertConfiguration.objects.select_related("insight")
        .filter(team_id=check.team_id, id=check.legacy_configuration_id)
        .first()
    )
    if alert is None:
        return evaluation
    group = outcome.groups[0]
    was_firing = check.instance().state == AlertState.FIRING.value
    if should_investigate_metrics_alert(
        alert,
        previous_state=InsightAlertState.FIRING if was_firing else None,
        new_state=InsightAlertState.FIRING,
    ):
        group = replace(
            group, source_detail={**group.source_detail, METRICS_INVESTIGATION_REQUESTED_KEY: str(alert.id)}
        )
        return replace(evaluation, outcomes=(replace(outcome, groups=(group,)),))
    decision = decide_investigation(
        alert,
        firing=True,
        configuration_id=check.id,
        evaluation_key=outcome.evaluation_key,
        episode_started_at=group.firing_episode.started_at if group.firing_episode else None,
    )
    if decision.should_investigate:
        group = replace(group, source_detail={**group.source_detail, INVESTIGATION_REQUESTED_KEY: str(alert.id)})
        held = None
        if evaluation.deliveries and alert.investigation_gates_notifications:
            (request,) = evaluation.deliveries
            held = HeldDelivery(
                request=request, reason=HOLD_REASON, release_after_seconds=int(RUNNING_HOLD.total_seconds())
            )
        return replace(
            evaluation,
            outcomes=(replace(outcome, groups=(group,), held_delivery=held),),
            deliveries=() if held else evaluation.deliveries,
        )
    if group.kind == AlertEventKind.FIRING and carried_verdict_suppresses(alert, decision):
        # As the insight stack: the firing still moves the alert's state and `last_notified_at`.
        group = replace(group, kind=AlertEventKind.CHECK, muted_notification=NotificationAction.FIRE.value)
        return replace(evaluation, outcomes=(replace(outcome, groups=(group,)),), deliveries=())
    return evaluation


def claim_requested_investigations(team_id: int, outcomes: tuple[PlatformAlertOutcome, ...]) -> InvestigationClaims:
    """Claims the investigation each recorded firing asked for, and returns the agent runs to start.

    A refused claim releases the firing's held delivery by the firing's last verdict, as the insight
    stack mutes a check that runs no investigation of its own.
    """
    starts: list[InvestigationStart] = []
    deliveries = []
    metrics: list[tuple[AlertConfiguration, PlatformAlertOutcome, RequestedInvestigation]] = []
    for outcome in outcomes:
        requested = requested_investigation(outcome)
        if requested is None:
            continue
        alert = (
            AlertConfiguration.objects.select_related("insight", "team")
            .filter(team_id=team_id, id=requested.alert_id)
            .first()
        )
        if alert is None:
            # The safety net sends the held firing at its deadline.
            continue
        if requested.metrics:
            metrics.append((alert, outcome, requested))
            continue
        group = outcome.groups[0]
        claim = claim_investigation(
            alert,
            configuration_id=outcome.configuration_id,
            evaluation_key=outcome.evaluation_key,
            episode_started_at=requested.episode_started_at,
            kind=InsightAlertInvestigation.Kind.AGENT,
            evaluated={
                "value": group.value,
                **{key: group.source_detail[key] for key in _EVALUATED_KEYS if key in group.source_detail},
            },
        )
        if claim.claimed:
            starts.append(
                InvestigationStart(
                    team_id=team_id,
                    alert_id=str(alert.id),
                    investigation_id=str(claim.investigation_id),
                    configuration_id=str(outcome.configuration_id),
                    evaluation_key=outcome.evaluation_key,
                    user_id=alert.created_by_id,
                )
            )
            continue
        if outcome.held_delivery is None:
            continue
        previous_verdict = previous_verdict_in_episode(
            team_id, outcome.configuration_id, requested.episode_started_at, outcome.evaluation_key
        )
        request = release_held(
            HeldDeliveryAddress(
                team_id=team_id, configuration_id=str(outcome.configuration_id), evaluation_key=outcome.evaluation_key
            ),
            suppress=carried_verdict_suppresses(alert, InvestigationDecision(previous_verdict=previous_verdict)),
            released_by=HoldReleasedBy.CLAIM_REFUSED,
        )
        if request is not None:
            deliveries.append(request)
    # Last, because each runs metric queries, and an agent's claim should not wait behind them.
    for alert, outcome, requested in metrics:
        _run_metrics_investigation(alert, outcome, requested)
    return InvestigationClaims(starts=tuple(starts), deliveries=tuple(deliveries))


def _run_metrics_investigation(
    alert: AlertConfiguration, outcome: PlatformAlertOutcome, requested: RequestedInvestigation
) -> None:
    """Claims and runs a metrics alert's investigation. Its failure is recorded on its row and never
    fails the claim, because the firing it explains has already gone out."""
    claim = claim_investigation(
        alert,
        configuration_id=outcome.configuration_id,
        evaluation_key=outcome.evaluation_key,
        episode_started_at=requested.episode_started_at,
        kind=InsightAlertInvestigation.Kind.METRICS,
        evaluated={"value": outcome.groups[0].value},
    )
    if not claim.claimed:
        return
    pending = InsightAlertInvestigation.objects.for_team(alert.team_id).filter(
        id=claim.investigation_id, status=InvestigationStatus.PENDING
    )
    investigation = pending.first()
    if investigation is None:
        return
    try:
        summary = investigate_metrics_alert(alert, fired_at=investigation.created_at)
    except Exception as error:
        logger.exception("platform_metrics_alert_investigation_failed", alert_id=str(alert.id))
        pending.update(status=InvestigationStatus.FAILED, error={"message": str(error)[:1000]})
        return
    pending.update(status=InvestigationStatus.DONE, summary=summary)
