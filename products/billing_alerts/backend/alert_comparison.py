"""The billing side of the alerts platform comparison contract.

Production billing keeps a row for every attempt it makes: one `BillingAlertEvaluationClaim` per
evaluation date and configuration revision, and one `BillingAlertEvent` per attempt at that claim.
The platform mints its evaluation key from the same three parts, so a platform check names the
production attempt it corresponds to, and the correspondence is a lookup rather than a walk.

A check the platform skipped carries a slot key and names no date. It is reported as unknown, because
a skip decided nothing to compare.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from posthog.models import Team

from products.alerts_platform.backend.facade.contracts import (
    CheckRef,
    IntentionalDivergence,
    PlatformCheck,
    SourceCorrespondence,
    SourceCoverage,
    SourceKind,
    SourceVerdict,
)
from products.alerts_platform.backend.facade.lifecycle import BILLING_ALERT_POLICY
from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)
from products.billing_alerts.backend.platform_source_cycle import EvaluationAttempt, parse_evaluation_key


def _platform_check_failed(check: PlatformCheck, verdict: SourceVerdict) -> bool:
    return bool(check.error_message) and verdict.coverage is SourceCoverage.EVALUATED


BILLING_INTENTIONAL_DIVERGENCES: tuple[IntentionalDivergence, ...] = (
    IntentionalDivergence(
        cause="platform_failure_retry_budget",
        recognizes=_platform_check_failed,
        why=(
            "Production retries a failed billing fetch or evaluation inside one attempt, through "
            "Temporal activity retries. The platform tries once and spends an attempt on the failure, "
            "so at the same attempt production can hold a verdict the platform has not reached. A "
            "billing service the platform worker cannot reach also lands here, which is why it is "
            "counted under its own cause rather than as agreement."
        ),
    ),
)


class BillingCorrespondence(SourceCorrespondence):
    source = SourceKind.BILLING
    # The platform adapter runs production's own state machine, so the two policies are one.
    production_policy = BILLING_ALERT_POLICY
    platform_policy = BILLING_ALERT_POLICY
    intentional_divergences = BILLING_INTENTIONAL_DIVERGENCES

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        verdicts: dict[CheckRef, SourceVerdict] = {}
        keyed: list[tuple[PlatformCheck, UUID, EvaluationAttempt]] = []
        for check in checks:
            attempt = parse_evaluation_key(check.evaluation_key)
            if check.legacy_configuration_id is None:
                verdicts[check.ref] = _unknown("the platform configuration names no billing alert")
            elif attempt is None:
                verdicts[check.ref] = _unknown("a skipped check names no evaluation date")
            else:
                keyed.append((check, check.legacy_configuration_id, attempt))

        if not keyed:
            return verdicts

        team_ids = {check.team_id for check, _, _ in keyed}
        # Read per team and its organization, so a check cannot read an alert of another team in the batch.
        organizations = dict(Team.objects.filter(id__in=team_ids).values_list("id", "organization_id"))
        known_alerts: set[tuple[int, UUID]] = set()
        for team_id, organization_id in organizations.items():
            known_alerts.update(
                BillingAlertConfiguration.objects.filter(
                    id__in={alert_id for check, alert_id, _ in keyed if check.team_id == team_id},
                    organization_id=organization_id,
                    team_id=team_id,
                ).values_list("team_id", "id")
            )
        wanted = {
            (alert_id, attempt.evaluation_date, attempt.configuration_revision)
            for check, alert_id, attempt in keyed
            if (check.team_id, alert_id) in known_alerts
        }
        claims = {
            (claim.alert_id, claim.evaluation_date, claim.configuration_revision): claim
            for claim in BillingAlertEvaluationClaim.objects.filter(
                alert_id__in={alert_id for alert_id, _, _ in wanted},
                evaluation_date__in={evaluation_date for _, evaluation_date, _ in wanted},
                configuration_revision__in={revision for _, _, revision in wanted},
            ).only("id", "alert_id", "evaluation_date", "configuration_revision", "status")
            if (claim.alert_id, claim.evaluation_date, claim.configuration_revision) in wanted
        }
        # A claim holds at most `MAX_EVALUATION_ATTEMPTS` events, so this read is bounded by the claims.
        attempts: dict[UUID, list[BillingAlertEvent]] = {claim.id: [] for claim in claims.values()}
        for event in (
            BillingAlertEvent.objects.filter(claim_id__in=list(attempts), team_id__in=team_ids)
            .only("id", "claim_id", "attempt_number", "state_after", "created_at")
            .order_by("claim_id", "attempt_number")
        ):
            attempts[event.claim_id].append(event)

        for check, alert_id, attempt in keyed:
            if (check.team_id, alert_id) not in known_alerts:
                verdicts[check.ref] = _unknown("no billing alert with that id in this project")
                continue
            claim = claims.get((alert_id, attempt.evaluation_date, attempt.configuration_revision))
            if claim is None:
                verdicts[check.ref] = _behind("production has not evaluated this date")
                continue
            verdicts[check.ref] = _verdict_at(check, claim, attempts[claim.id], attempt.number)

        return verdicts


# Production makes no further attempt at a claim it completed, or one a newer revision replaced.
_SETTLED = frozenset({BillingAlertEvaluationClaim.Status.COMPLETED, BillingAlertEvaluationClaim.Status.SUPERSEDED})


def _unknown(detail: str) -> SourceVerdict:
    return SourceVerdict(caught_up_at=None, coverage=SourceCoverage.UNKNOWN, state=None, detail=detail)


def _behind(detail: str) -> SourceVerdict:
    return SourceVerdict(caught_up_at=None, coverage=SourceCoverage.BEHIND, state=None, detail=detail)


def _verdict_at(
    check: PlatformCheck,
    claim: BillingAlertEvaluationClaim,
    events: Sequence[BillingAlertEvent],
    number: int,
) -> SourceVerdict:
    """What production held at the same attempt of the same date.

    A production stack that settled the date or revision in fewer attempts holds its last state at
    every later attempt, because it makes no further check of it.
    """
    matched = next((event for event in events if event.attempt_number == number), None)
    if matched is None and claim.status in _SETTLED and events:
        matched = events[-1]
    if matched is None:
        return _behind(f"production has not made attempt {number} at this date")

    caught_up = next(
        (event for event in events if event.created_at > check.occurred_at and event.state_after == check.state),
        None,
    )
    return SourceVerdict(
        coverage=SourceCoverage.EVALUATED,
        state=matched.state_after,
        caught_up_at=caught_up.created_at if caught_up is not None else None,
        evidence_id=str(matched.id),
    )
