"""The investigation agent's decision and claim for an insight alert the platform evaluates.

The same rules as the insight stack's own (`posthog/temporal/alerts/investigation.py`), read from
`InsightAlertInvestigation` instead of `AlertCheck`. An episode is one firing, named by the
platform's `episode_started_at`, rather than a run of FIRING checks.

The decision is a read, so it can run inside an evaluation that a retry repeats. The claim is the
write, and runs once the evaluation is recorded.
"""

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from django.db import connection, transaction

from posthog.dataclasses import frozen
from posthog.temporal.alerts.investigation import (
    InvestigationDecision,
    decide_within_budget,
    investigates,
    refusing_investigations,
)

from products.alerts.backend.investigation_episode import STARTED_INVESTIGATION_STATUSES
from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation

_CLAIM_LOCK_SQL: Final = "SELECT pg_advisory_xact_lock(hashtext(%s))"


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
    # Newest first, so the first verdict is the last one reached. One read, because a firing holds
    # a few rows. Its own row exists when a retry repeats a decision its claim already wrote.
    earlier = list(
        InsightAlertInvestigation.objects.for_team(alert.team_id)
        .filter(configuration_id=configuration_id, episode_started_at=episode_started_at)
        .exclude(evaluation_key=evaluation_key)
        .order_by("-created_at")
        .values_list("status", "verdict")
    )
    return decide_within_budget(
        started=sum(status in STARTED_INVESTIGATION_STATUSES for status, _ in earlier),
        previous_verdict=next((verdict for _, verdict in earlier if verdict is not None), None),
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
