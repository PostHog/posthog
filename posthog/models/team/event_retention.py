from collections.abc import Collection, Sequence
from datetime import date
from typing import Optional
from uuid import UUID

from django.conf import settings
from django.db import connection
from django.utils import timezone

import posthoganalytics
from dateutil.relativedelta import relativedelta

from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig, effective_events_retention
from posthog.models.organization import Organization, ProductFeature
from posthog.models.team.team import Team

# Grandfather default: existing teams keep 7 years (84 months) until billing assigns a shorter window.
DEFAULT_EVENT_RETENTION_MONTHS = 84

# Cohort feature flag — gates enforcement so the rollout can target a specific cohort.
EVENTS_DATA_RETENTION_FLAG = "events-data-retention"

EVENTS_DATA_DELETION_FLAG = "events-data-retention-deletion"

# Billing entitlement key the sync job reconciles Team.event_retention_months against.
EVENTS_DATA_RETENTION_FEATURE = AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION

STANDARD_DATA_RETENTION_FEATURE = AvailableFeature.PRODUCT_ANALYTICS_STANDARD_DATA_RETENTION
STANDARD_DEFAULT_PERIOD_MONTHS = 24


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

    The period set in project or organization settings, never past the plan's, else the default. Computed once per
    query in prepare_ast_for_printing. The cohort gate runs first and is DB-free, so non-cohort teams (the vast majority
    during rollout) never hit Postgres here — only an enforced team triggers the lean field load.
    """
    if team_id is None:
        if team is None:
            return None
        team_id = team.id

    if not should_enforce_events_retention(team_id):
        return None

    if team is None:
        team = Team.objects.filter(id=team_id).only("organization_id", "event_retention_months").first()
        if team is None:
            return None

    return _queryable_months(team)


_REQUEST_CACHED_QUERYABLE_MONTHS_ATTR = "_request_cached_queryable_events_retention_months"


def _queryable_months(team: Team) -> int:
    """Memoise the period on the team instance, which is request-scoped in practice.

    Every insight on a dashboard and every query it prints asks again, and each ask is a Postgres query.
    """
    if not hasattr(team, _REQUEST_CACHED_QUERYABLE_MONTHS_ATTR):
        setattr(team, _REQUEST_CACHED_QUERYABLE_MONTHS_ATTR, events_retention_periods([team])[team.id])
    return getattr(team, _REQUEST_CACHED_QUERYABLE_MONTHS_ATTR)


@frozen
class TeamPlan:
    team_id: int
    organization_id: UUID
    plan_months: int


def team_plan(team: Team) -> TeamPlan:
    return TeamPlan(
        team_id=team.id,
        organization_id=team.organization_id,
        plan_months=team.event_retention_months or DEFAULT_EVENT_RETENTION_MONTHS,
    )


def should_delete_past_default_period(team: Team) -> bool:
    if settings.EVENTS_DATA_RETENTION_ENFORCED is not None:
        return settings.EVENTS_DATA_RETENTION_ENFORCED

    if not is_cloud():
        return False

    return bool(
        posthoganalytics.feature_enabled(
            EVENTS_DATA_DELETION_FLAG,
            str(team.id),
            person_properties={
                "plan_retention_months": team_plan(team).plan_months,
                "organization_id": str(team.organization_id),
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def default_period(plan_months: int, standard: bool, min_months: int | None) -> int:
    default = min(plan_months, STANDARD_DEFAULT_PERIOD_MONTHS) if standard else plan_months
    return min(plan_months, max(default, min_months)) if min_months is not None else default


def events_retention_periods(teams: Sequence[Team]) -> dict[int, int]:
    return retention_periods([team_plan(team) for team in teams])


def retention_periods(
    plans: Sequence[TeamPlan], standard_organization_ids: Collection[UUID] | None = None
) -> dict[int, int]:
    setting_months = {
        item.team_id: item.months for item in effective_events_retention(team_ids=[p.team_id for p in plans])
    }
    defaults = default_periods(
        [plan for plan in plans if plan.team_id not in setting_months], standard_organization_ids
    )
    return {
        plan.team_id: min(plan.plan_months, setting_months[plan.team_id])
        if plan.team_id in setting_months
        else defaults[plan.team_id]
        for plan in plans
    }


def default_periods(
    teams: Sequence[TeamPlan], standard_organization_ids: Collection[UUID] | None = None
) -> dict[int, int]:
    shortened = {team.organization_id for team in teams if STANDARD_DEFAULT_PERIOD_MONTHS < team.plan_months}
    if standard_organization_ids is not None:
        standard = shortened.intersection(standard_organization_ids)
    else:
        standard = _standard_retention_organization_ids(shortened) if shortened else set()
    min_months = _minimum_months(standard) if standard else {}
    return {
        team.team_id: default_period(
            team.plan_months, team.organization_id in standard, min_months.get(team.organization_id)
        )
        for team in teams
    }


def _minimum_months(organization_ids: Collection[UUID]) -> dict[UUID, int]:
    return dict(
        OrganizationEventsRetentionConfig.objects.filter(
            organization_id__in=organization_ids, min_events_retention_months__isnull=False
        ).values_list("organization_id", "min_events_retention_months")
    )


def _standard_retention_organization_ids(organization_ids: Collection[UUID]) -> set[UUID]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT id FROM {Organization._meta.db_table}
            WHERE id = ANY(%s::uuid[])
              AND EXISTS (SELECT 1 FROM unnest(available_product_features) AS feature WHERE feature->>'key' = %s)
            """,
            [list(organization_ids), str(STANDARD_DATA_RETENTION_FEATURE)],
        )
        return {organization_id for (organization_id,) in cursor.fetchall()}


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


def organization_events_retention_months(organization: Organization) -> int:
    return parse_events_feature_to_months(organization.get_available_feature(EVENTS_DATA_RETENTION_FEATURE))


def billed_events_retention_months(organization: Organization) -> int | None:
    """The plan period, or None before billing first sends the organization's features."""
    return organization_events_retention_months(organization) if organization.available_product_features else None


def has_standard_retention(organization: Organization) -> bool:
    return organization.is_feature_available(STANDARD_DATA_RETENTION_FEATURE)


def reconcile_organization_events_retention(organization: Organization) -> int:
    """Align the org's teams with its entitlement-derived retention window; returns teams updated.

    Re-reads the persisted entitlement so overlapping billing syncs can't apply a stale in-memory snapshot.
    """
    organization.refresh_from_db(fields=["available_product_features"])
    target_months = organization_events_retention_months(organization)
    return (
        Team.objects.filter(organization=organization)
        .exclude(event_retention_months=target_months)
        .update(event_retention_months=target_months, updated_at=timezone.now())
    )
