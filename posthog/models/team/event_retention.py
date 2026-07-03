from typing import Optional

from django.conf import settings

import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models.organization import ProductFeature
from posthog.models.team.team import Team

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
