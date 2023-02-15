import copy
from datetime import timedelta
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, TypedDict, cast

import dateutil.parser
from django.db.models import Q
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.cache_utils import cache_for
from posthog.models.organization import Organization, OrganizationUsageInfo
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    find_count_for_team_in_rows,
    get_teams_with_event_count_in_period,
    get_teams_with_recording_count_in_period,
)
from posthog.utils import get_current_day

RATE_LIMITER_CACHE_KEY = "@posthog/quota-limits/"


class QuotaResource(Enum):
    EVENTS = "events"
    RECORDINGS = "recordings"


OVERAGE_BUFFER = {
    QuotaResource.EVENTS: 0,
    QuotaResource.RECORDINGS: 1000,
}


def replace_limited_team_tokens(resource: QuotaResource, tokens: Mapping[str, int]) -> None:
    pipe = get_client().pipeline()
    pipe.delete(f"{RATE_LIMITER_CACHE_KEY}{resource.value}")
    if tokens:
        pipe.zadd(f"{RATE_LIMITER_CACHE_KEY}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)
    pipe.execute()


def add_limited_team_tokens(resource: QuotaResource, tokens: Mapping[str, int]) -> None:
    redis_client = get_client()
    redis_client.zadd(f"{RATE_LIMITER_CACHE_KEY}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)


def remove_limited_team_tokens(resource: QuotaResource, tokens: List[str]) -> None:
    redis_client = get_client()
    redis_client.zrem(f"{RATE_LIMITER_CACHE_KEY}{resource.value}", *tokens)


@cache_for(timedelta(seconds=30), background_refresh=True)
def list_limited_team_tokens(resource: QuotaResource) -> List[str]:
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{RATE_LIMITER_CACHE_KEY}{resource.value}", min=now.timestamp(), max="+inf")
    return [x.decode("utf-8") for x in results]


class UsageCounters(TypedDict):
    events: int
    recordings: int


def org_quota_limited_until(organization: Organization, resource: QuotaResource) -> Optional[int]:
    if not organization.usage:
        return None

    summary = organization.usage.get(resource.value, {})
    usage = summary.get("usage", 0)
    todays_usage = summary.get("todays_usage", 0)
    limit = summary.get("limit")

    if limit is None:
        return None

    is_rate_limited = usage + todays_usage >= limit + OVERAGE_BUFFER[resource]
    billing_period_end = round(dateutil.parser.isoparse(organization.usage["period"][1]).timestamp())

    if is_rate_limited and billing_period_end:
        return billing_period_end

    return None


def sync_org_quota_limits(organization: Organization):
    if not organization.usage:
        return None

    team_tokens: List[str] = [x for x in list(organization.teams.values_list("api_token", flat=True)) if x]

    if not team_tokens:
        capture_exception(Exception(f"quota_limiting: No team tokens found for organization: {organization.id}"))
        return

    for resource in [QuotaResource.EVENTS, QuotaResource.RECORDINGS]:
        rate_limited_until = org_quota_limited_until(organization, resource)

        if rate_limited_until:
            add_limited_team_tokens(resource, {x: rate_limited_until for x in team_tokens})
        else:
            remove_limited_team_tokens(resource, team_tokens)


def set_org_usage_summary(
    organization: Organization,
    new_usage: Optional[OrganizationUsageInfo] = None,
    todays_usage: Optional[UsageCounters] = None,
) -> bool:
    # TRICKY: We don't want to overwrite the "todays_usage" value unless the usage from the billing service is different than what we have locally.
    # Also we want to return if anything changed so that the caller can update redis

    has_changed = False
    new_usage = new_usage or cast(Optional[OrganizationUsageInfo], organization.usage)

    if not new_usage:
        # If we are not setting it and it doesn't exist we can't update it
        return False

    new_usage = copy.deepcopy(new_usage)

    for field in ["events", "recordings"]:
        resource_usage = new_usage[field]  # type: ignore

        if todays_usage:
            resource_usage["todays_usage"] = todays_usage[field]  # type: ignore
        else:
            # TRICKY: If we are not explictly setting todays_usage, we want to reset it to 0 IF the incoming new_usage is different
            if (organization.usage or {}).get(field, {}).get("usage") != resource_usage.get("usage"):
                resource_usage["todays_usage"] = 0
            else:
                resource_usage["todays_usage"] = organization.usage.get(field, {}).get("todays_usage") or 0

    has_changed = new_usage != organization.usage
    organization.usage = new_usage

    return has_changed


def update_all_org_billing_quotas(dry_run: bool = False) -> Dict[str, Dict[str, int]]:
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

    rate_limited_orgs: Dict[str, Dict[str, int]] = {"events": {}, "recordings": {}}

    # We find all orgs that should be rate limited
    for org_id, todays_report in todays_usage_report.items():
        org = orgs_by_id[org_id]

        # if we don't have limits set from the billing service, we can't risk rate limiting existing customers
        if org.usage and org.usage.get("period"):
            # for each organization, we check if the current usage + today's unreported usage is over the limit
            if set_org_usage_summary(org, todays_usage=todays_report):
                org.save(update_fields=["usage"])

            for field in ["events", "recordings"]:
                rate_limited_until = org_quota_limited_until(org, QuotaResource(field))

                if rate_limited_until:
                    # TODO: Set this rate limit to the end of the billing period
                    rate_limited_orgs[field][org_id] = rate_limited_until

    rate_limited_teams: Dict[str, Dict[str, int]] = {"events": {}, "recordings": {}}

    # Convert the org ids to team tokens
    for team in teams:
        for field in rate_limited_orgs:
            # TODO: Check for specific field on organization to force quota limits on
            if str(team.organization.id) in rate_limited_orgs[field]:
                rate_limited_teams[field][team.api_token] = rate_limited_orgs[field][str(team.organization.id)]

    if not dry_run:
        for field in rate_limited_teams:
            replace_limited_team_tokens(QuotaResource(field), rate_limited_teams[field])

    return rate_limited_orgs
