from datetime import timedelta
from typing import Dict, List, Optional, Sequence, TypedDict

from django.db.models import Q
from django.utils import timezone

from posthog.cache_utils import cache_for
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    find_count_for_team_in_rows,
    get_teams_with_event_count_in_period,
    get_teams_with_recording_count_in_period,
)
from posthog.utils import get_current_day

RATE_LIMITER_CACHE_KEY = "@posthog/quota-limits/"


class QUOTA_RESOURCES:
    EVENTS = "events"
    RECORDINGS = "recordings"


def add_limited_teams(resource: str, teams: dict) -> None:
    redis_client = get_client()
    redis_client.zadd(f"{RATE_LIMITER_CACHE_KEY}{resource}", teams)


def remove_limited_teams(resource: str, teams: List[str]) -> None:
    redis_client = get_client()
    redis_client.zrem(f"{RATE_LIMITER_CACHE_KEY}{resource}", *teams)


def replace_limited_teams(resource: str, teams: dict) -> None:
    pipe = get_client().pipeline()
    pipe.zremrangebyscore(f"{RATE_LIMITER_CACHE_KEY}{resource}", "-inf", "+inf")
    if teams:
        pipe.zadd(f"{RATE_LIMITER_CACHE_KEY}{resource}", teams)
    pipe.execute()


@cache_for(timedelta(seconds=30))
def list_limited_teams(resource: str) -> List[str]:
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{RATE_LIMITER_CACHE_KEY}{resource}", min=now.timestamp(), max="+inf")
    return [x.decode("utf-8") for x in results]


class UsageCounters(TypedDict):
    events: int
    recordings: int


def update_all_org_billing_quotas(
    dry_run: bool = False,
    only_organization_id: Optional[str] = None,
) -> Dict[str, Dict[str, float]]:  # Dict[str, Any]]:

    period = get_current_day()
    period_start, period_end = period

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = dict(
        teams_with_event_count_in_period=get_teams_with_event_count_in_period(period_start, period_end),
        teams_with_recording_count_in_period=get_teams_with_recording_count_in_period(period_start, period_end),
    )

    teams: Sequence[Team] = list(
        Team.objects.select_related("organization").exclude(
            Q(organization__for_internal_metrics=True) | Q(is_demo=True)
        )
    )

    todays_usage_report: Dict[str, UsageCounters] = {}
    orgs_by_id: Dict[str, Organization] = {}

    # we iterate through all teams, and add their usage to the organization they belong to
    for team in teams:
        team_report = UsageCounters(
            events=find_count_for_team_in_rows(team.id, all_data["teams_with_event_count_in_period"]),
            recordings=find_count_for_team_in_rows(team.id, all_data["teams_with_recording_count_in_period"]),
        )

        org_id = str(team.organization.id)

        if org_id not in todays_usage_report:
            orgs_by_id[org_id] = team.organization
            todays_usage_report[org_id] = team_report.copy()
        else:
            org_report = todays_usage_report[org_id]
            for field in team_report:
                org_report[field] += team_report[field]  # type: ignore

    rate_limited_orgs: Dict[str, Dict[str, float]] = {"events": {}, "recordings": {}}

    # We find all orgs that should be rate limited
    for org_id, todays_report in todays_usage_report.items():
        org = orgs_by_id[org_id]

        if only_organization_id and only_organization_id != org_id:
            continue

        # if we don't have limits set from the billing service, we can't risk rate limiting existing customers
        if org.usage:
            # for each organization, we check if the current usage + today's unreported usage is over the limit
            for field in ["events", "recordings"]:
                usage = org.usage.get(field, {}).get("usage", 0)
                limit = org.usage.get(field, {}).get("limit", 0)
                unreported_usage = todays_report[field]  # type: ignore

                if limit is None:
                    continue

                is_rate_limited = usage + unreported_usage > limit
                if is_rate_limited:
                    # TODO: Set this rate limit to the end of the billing period
                    rate_limited_orgs[field][org_id] = timezone.now().timestamp() + timedelta(days=1).total_seconds()

    rate_limited_teams: Dict[str, Dict[str, float]] = {"events": {}, "recordings": {}}

    # Convert the org ids to team tokens
    for team in teams:
        for field in rate_limited_orgs:
            # TODO: Check for specific field on organization to force quota limits on
            if str(team.organization.id) in rate_limited_orgs[field]:
                rate_limited_teams[field][team.api_token] = rate_limited_orgs[field].pop(str(team.organization.id))

    if not dry_run:
        for field in rate_limited_teams:
            replace_limited_teams(field, rate_limited_teams[field])

    return rate_limited_orgs
