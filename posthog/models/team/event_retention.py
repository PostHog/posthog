from datetime import date
from typing import TYPE_CHECKING, Optional

from django.conf import settings
from django.db.models import F
from django.utils import timezone

import posthoganalytics
from dateutil.relativedelta import relativedelta

from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models.organization import ProductFeature
from posthog.models.team.team import Team

if TYPE_CHECKING:
    from posthog.models.organization import Organization

# Grandfather default: existing teams keep 7 years (84 months) until billing assigns a shorter window.
DEFAULT_EVENT_RETENTION_MONTHS = 84

# Cohort feature flag — gates enforcement so the rollout can target a specific cohort.
EVENTS_DATA_RETENTION_FLAG = "events-data-retention"

# Billing entitlement key the sync job reconciles Team.event_retention_months against.
EVENTS_DATA_RETENTION_FEATURE = AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION


def should_enforce_events_retention(team_id: int) -> bool:
    """Whether events-data-retention is enforced for this team — the cohort gate.

    Keyed on team_id so it stays DB-free on the HogQL hot path: the settings override wins (ops kill switch /
    local + test toggle), otherwise a cohort flag on cloud, evaluated locally against the team's distinct id.
    Self-hosted never enforces — those users own their data.
    """
    if settings.EVENTS_DATA_RETENTION_ENFORCED is not None:
        return settings.EVENTS_DATA_RETENTION_ENFORCED

    if not is_cloud():
        return False

    return bool(
        posthoganalytics.feature_enabled(
            EVENTS_DATA_RETENTION_FLAG,
            str(team_id),
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def events_retention_months_for_team(team: Optional[Team], team_id: Optional[int]) -> Optional[int]:
    """Months of events retention to floor a query's events scans to, or None if retention isn't enforced.

    Computed once per query in prepare_ast_for_printing. The cohort gate runs first and is DB-free, so non-cohort
    teams (the vast majority during rollout) never hit Postgres here — only an enforced team triggers the lean
    field load.
    """
    if team_id is None:
        if team is None:
            return None
        team_id = team.id

    if not should_enforce_events_retention(team_id):
        return None

    if team is None:
        team = Team.objects.filter(id=team_id).only("event_retention_months").first()
        if team is None:
            return None

    return team.event_retention_months or DEFAULT_EVENT_RETENTION_MONTHS


def events_retention_floor_date(team: Team, retention_months: int) -> date:
    return (timezone.now() - relativedelta(months=retention_months)).astimezone(team.timezone_info).date()


def parse_events_feature_to_months(retention_feature: ProductFeature | None) -> int:
    """Map the billing events-retention entitlement to a number of months for the sync job.

    Defaults to 7 years (84 months) when billing exposes no entitlement, so existing paid teams stay grandfathered
    rather than being silently reduced. Honors billing's value exactly — no bucketing — since the field stores the
    real duration.
    """
    if retention_feature is None:
        return DEFAULT_EVENT_RETENTION_MONTHS

    limit = retention_feature.get("limit")
    unit = retention_feature.get("unit")
    if limit is None or unit is None or limit <= 0:
        return DEFAULT_EVENT_RETENTION_MONTHS

    match unit.lower():
        case "year" | "years":
            return limit * 12
        case "month" | "months":
            return limit
        case _:
            # Events retention is a months/years concept; an unexpected unit (e.g. days) grandfathers rather than
            # introducing a lossy day→month conversion.
            return DEFAULT_EVENT_RETENTION_MONTHS


def organization_events_retention_months(organization: "Organization") -> int:
    return parse_events_feature_to_months(organization.get_available_feature(EVENTS_DATA_RETENTION_FEATURE))


def events_retention_target_months(organization_months: int, grant_months: Optional[int]) -> int:
    return max(organization_months, grant_months or 0)


def reconcile_organization_events_retention(organization: "Organization") -> int:
    """Align the org's teams with its entitlement-derived retention window; returns teams updated.

    Re-reads the persisted entitlement so overlapping billing syncs can't apply a stale in-memory snapshot.
    """
    organization.refresh_from_db(fields=["available_product_features"])
    organization_months = organization_events_retention_months(organization)
    rows = (
        Team.objects.filter(organization=organization)
        .annotate(grant_months=F("events_retention_grant__retention_months"))
        .values_list("id", "event_retention_months", "grant_months")
    )
    team_ids_by_change: dict[tuple[int, int], list[int]] = {}
    for team_id, current_months, grant_months in rows:
        target_months = events_retention_target_months(organization_months, grant_months)
        if current_months != target_months:
            team_ids_by_change.setdefault((current_months, target_months), []).append(team_id)
    updated = 0
    for (current_months, target_months), team_ids in team_ids_by_change.items():
        # Only rows still at the value read above, so a grant saved in between keeps its window.
        updated += Team.objects.filter(pk__in=team_ids, event_retention_months=current_months).update(
            event_retention_months=target_months, updated_at=timezone.now()
        )
    return updated


def reconcile_team_events_retention(team: Team) -> None:
    grant_months = (
        Team.objects.filter(pk=team.pk)
        .annotate(grant_months=F("events_retention_grant__retention_months"))
        .values_list("grant_months", flat=True)
        .first()
    )
    target_months = events_retention_target_months(
        organization_events_retention_months(team.organization), grant_months
    )
    Team.objects.filter(pk=team.pk).exclude(event_retention_months=target_months).update(
        event_retention_months=target_months, updated_at=timezone.now()
    )
