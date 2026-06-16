from datetime import timedelta
from typing import Optional

from django.conf import settings

import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models.organization import ProductFeature
from posthog.models.team.team import EventRetentionPeriod, Team

# Concrete retention window per plan, denormalized onto Team.event_retention_period and synced from the
# billing entitlement. Every plan has a real value — there is no "unlimited" tier.
EVENT_RETENTION_PERIOD_TO_TIMEDELTA: dict[str, timedelta] = {
    EventRetentionPeriod.ONE_YEAR: timedelta(days=365),
    EventRetentionPeriod.TWO_YEARS: timedelta(days=365 * 2),
    EventRetentionPeriod.THREE_YEARS: timedelta(days=365 * 3),
    EventRetentionPeriod.FIVE_YEARS: timedelta(days=365 * 5),
    EventRetentionPeriod.SEVEN_YEARS: timedelta(days=365 * 7),
}

DEFAULT_EVENT_RETENTION = timedelta(days=365 * 7)

# Cohort feature flag — enables enforcement for a project so the rollout can target a specific cohort.
EVENTS_DATA_RETENTION_FLAG = "events-data-retention"


def get_events_retention_period(team: Team) -> timedelta:
    """The team's events retention window, read from the denormalized Team.event_retention_period.

    Always concrete (default 7 years). Read on the HogQL hot path, so this stays a pure field read — no billing
    or DB lookups. The billing entitlement is reconciled onto the field by the sync job.
    """
    return EVENT_RETENTION_PERIOD_TO_TIMEDELTA.get(team.event_retention_period, DEFAULT_EVENT_RETENTION)


def should_enforce_events_retention(team_id: int) -> bool:
    """Whether events-data-retention is enforced for this team — the cohort gate.

    Keyed on team_id so it stays DB-free on the HogQL hot path: the settings override wins (ops kill switch /
    local + test toggle), otherwise a per-project cohort flag on cloud, evaluated locally against the project-group
    key (target the rollout cohort by project group). Self-hosted never enforces — those users own their data.
    """
    if settings.EVENTS_DATA_RETENTION_ENFORCED is not None:
        return settings.EVENTS_DATA_RETENTION_ENFORCED

    if not is_cloud():
        return False

    return bool(
        posthoganalytics.feature_enabled(
            EVENTS_DATA_RETENTION_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def events_retention_window_for_team(team: Optional[Team], team_id: Optional[int]) -> Optional[timedelta]:
    """The retention floor to apply to a query's events scans, or None if retention isn't enforced for this team.

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
        team = Team.objects.filter(id=team_id).only("event_retention_period").first()
        if team is None:
            return None

    return get_events_retention_period(team)


# Billing entitlement key the sync job reconciles Team.event_retention_period against.
EVENTS_DATA_RETENTION_FEATURE = AvailableFeature.EVENT_DATA_RETENTION


def parse_events_feature_to_period(retention_feature: ProductFeature | None) -> str:
    """Map the billing events-retention entitlement to a concrete EventRetentionPeriod value for the sync job.

    Defaults to 7 years when billing exposes no entitlement, so existing paid teams stay grandfathered at their
    current retention rather than being silently reduced.
    """
    if retention_feature is None:
        return EventRetentionPeriod.SEVEN_YEARS

    limit = retention_feature.get("limit")
    unit = retention_feature.get("unit")
    if limit is None or unit is None or limit <= 0:
        return EventRetentionPeriod.SEVEN_YEARS

    match unit.lower():
        case "year" | "years":
            years = limit
        case "month" | "months":
            years = limit // 12
        case "day" | "days":
            years = limit // 365
        case _:
            return EventRetentionPeriod.SEVEN_YEARS

    # A sub-unit entitlement (e.g. 11 months) floors to 0 years; grandfather rather than over-provision a full year.
    if years <= 0:
        return EventRetentionPeriod.SEVEN_YEARS
    if years <= 1:
        return EventRetentionPeriod.ONE_YEAR
    if years <= 2:
        return EventRetentionPeriod.TWO_YEARS
    if years <= 3:
        return EventRetentionPeriod.THREE_YEARS
    if years <= 5:
        return EventRetentionPeriod.FIVE_YEARS
    return EventRetentionPeriod.SEVEN_YEARS
