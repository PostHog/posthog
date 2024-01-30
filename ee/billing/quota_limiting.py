import copy
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Mapping, Optional, Sequence, TypedDict, cast

import dateutil.parser
from django.db.models import Q
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.cache_utils import cache_for
from posthog.event_usage import report_organization_action
from posthog.models.organization import Organization, OrganizationUsageInfo
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    convert_team_usage_rows_to_dict,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_recording_count_in_period,
    get_teams_with_rows_synced_in_period,
)
from posthog.utils import get_current_day

QUOTA_LIMITER_CACHE_KEY = "@posthog/quota-limits/"
# We are updating the quota limiting behavior so we retain data for 7 days before
# permanently dropping it. This will allow us to recover data in the case of incidents
# where usage may have inadvertently exceeded a billing limit.
# Ref: INC-144
QUOTA_OVERAGE_RETENTION_CACHE_KEY = "@posthog/quota-overage-retention/"


class QuotaResource(Enum):
    EVENTS = "events"
    RECORDINGS = "recordings"
    ROWS_SYNCED = "rows_synced"


OVERAGE_BUFFER = {
    QuotaResource.EVENTS: 0,
    QuotaResource.RECORDINGS: 1000,
    QuotaResource.ROWS_SYNCED: 0,
}


def replace_limited_team_tokens(
    resource: QuotaResource, tokens: Mapping[str, int], cache_key: str = QUOTA_LIMITER_CACHE_KEY
) -> None:
    pipe = get_client().pipeline()
    pipe.delete(f"{cache_key}{resource.value}")
    if tokens:
        pipe.zadd(f"{cache_key}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)
    pipe.execute()


def add_limited_team_tokens(
    resource: QuotaResource, tokens: Mapping[str, int], cache_key: str = QUOTA_LIMITER_CACHE_KEY
) -> None:
    redis_client = get_client()
    redis_client.zadd(f"{cache_key}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)


def remove_limited_team_tokens(
    resource: QuotaResource, tokens: List[str], cache_key: str = QUOTA_LIMITER_CACHE_KEY
) -> None:
    redis_client = get_client()
    redis_client.zrem(f"{cache_key}{resource.value}", *tokens)


@cache_for(timedelta(seconds=30), background_refresh=True)
def list_limited_team_attributes(resource: QuotaResource, cache_key: str = QUOTA_LIMITER_CACHE_KEY) -> List[str]:
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{cache_key}{resource.value}", min=now.timestamp(), max="+inf")
    return [x.decode("utf-8") for x in results]


class UsageCounters(TypedDict):
    events: int
    recordings: int
    rows_synced: int


def org_quota_limited_until(organization: Organization, resource: QuotaResource, today: datetime) -> Optional[int]:
    if not organization.usage:
        return None

    summary = organization.usage.get(resource.value, {})
    if not summary:
        return None
    usage = summary.get("usage", 0)
    todays_usage = summary.get("todays_usage", 0)
    data_retained_until = summary.get("retained_period_end", None)
    limit = summary.get("limit")
    needs_save = False

    if limit is None:
        return None

    is_quota_limited = usage + todays_usage >= limit + OVERAGE_BUFFER[resource]
    billing_period_start = round(dateutil.parser.isoparse(organization.usage["period"][0]).timestamp())
    billing_period_end = round(dateutil.parser.isoparse(organization.usage["period"][1]).timestamp())

    if not is_quota_limited:
        # Reset data retention
        if data_retained_until:
            data_retained_until = None
            del summary["retained_period_end"]
            needs_save = True
            return None, None, True
        return None

    if organization.never_drop_data:
        return None

    # Either wasn't set or was set in the previous biling period
    if (
        not data_retained_until
        or round((datetime.fromtimestamp(data_retained_until) - timedelta(days=7)).timestamp()) < billing_period_start
    ):
        data_retained_until = round((today + timedelta(days=7)).timestamp())
        summary["retained_period_end"] = data_retained_until
        needs_save = True

    if billing_period_end:
        return billing_period_end, data_retained_until, needs_save

    return None


def sync_org_quota_limits(organization: Organization):
    if not organization.usage:
        return None

    today_start, _ = get_current_day()
    for resource in [QuotaResource.EVENTS, QuotaResource.RECORDINGS, QuotaResource.ROWS_SYNCED]:
        team_attributes = get_team_attribute_by_quota_resource(organization, resource)
        result = org_quota_limited_until(organization, resource, today_start)
        if result:
            quota_limited_until, data_retained_until, needs_save = result

            if needs_save:
                organization.save()
            if quota_limited_until and data_retained_until < today_start.timestamp():
                add_limited_team_tokens(resource, {x: quota_limited_until for x in team_attributes})
                continue
            elif data_retained_until and data_retained_until >= today_start.timestamp():
                add_limited_team_tokens(
                    resource, {x: quota_limited_until for x in team_attributes}, QUOTA_OVERAGE_RETENTION_CACHE_KEY
                )
                continue
        remove_limited_team_tokens(resource, team_attributes)
        remove_limited_team_tokens(resource, team_attributes, QUOTA_OVERAGE_RETENTION_CACHE_KEY)


def get_team_attribute_by_quota_resource(organization: Organization, resource: QuotaResource):
    if resource in [QuotaResource.EVENTS, QuotaResource.RECORDINGS]:
        team_tokens: List[str] = [x for x in list(organization.teams.values_list("api_token", flat=True)) if x]

        if not team_tokens:
            capture_exception(Exception(f"quota_limiting: No team tokens found for organization: {organization.id}"))
            return

        return team_tokens

    if resource == QuotaResource.ROWS_SYNCED:
        team_ids: List[str] = [x for x in list(organization.teams.values_list("id", flat=True)) if x]

        if not team_ids:
            capture_exception(Exception(f"quota_limiting: No team ids found for organization: {organization.id}"))
            return

        return team_ids


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

    for field in ["events", "recordings", "rows_synced"]:
        resource_usage = new_usage.get(field, {"limit": None, "usage": 0, "todays_usage": 0})
        if not resource_usage:
            continue

        if todays_usage:
            resource_usage["todays_usage"] = todays_usage.get(field, 0)
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
        teams_with_event_count_in_period=convert_team_usage_rows_to_dict(
            get_teams_with_billable_event_count_in_period(period_start, period_end)
        ),
        teams_with_recording_count_in_period=convert_team_usage_rows_to_dict(
            get_teams_with_recording_count_in_period(period_start, period_end)
        ),
        teams_with_rows_synced_in_period=convert_team_usage_rows_to_dict(
            get_teams_with_rows_synced_in_period(period_start, period_end)
        ),
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
            events=all_data["teams_with_event_count_in_period"].get(team.id, 0),
            recordings=all_data["teams_with_recording_count_in_period"].get(team.id, 0),
            rows_synced=all_data["teams_with_rows_synced_in_period"].get(team.id, 0),
        )

        org_id = str(team.organization.id)

        if org_id not in todays_usage_report:
            orgs_by_id[org_id] = team.organization
            todays_usage_report[org_id] = team_report.copy()
        else:
            org_report = todays_usage_report[org_id]
            for field in team_report:
                org_report[field] += team_report[field]  # type: ignore

    quota_limited_orgs: Dict[str, Dict[str, int]] = {"events": {}, "recordings": {}, "rows_synced": {}}
    data_retained_orgs: Dict[str, Dict[str, int]] = {"events": {}, "recordings": {}, "rows_synced": {}}

    # We find all orgs that should be rate limited
    for org_id, todays_report in todays_usage_report.items():
        org = orgs_by_id[org_id]

        # if we don't have limits set from the billing service, we can't risk rate limiting existing customers
        if org.usage and org.usage.get("period"):
            # for each organization, we check if the current usage + today's unreported usage is over the limit
            if set_org_usage_summary(org, todays_usage=todays_report):
                org.save(update_fields=["usage"])

            for field in ["events", "recordings", "rows_synced"]:
                result = org_quota_limited_until(org, QuotaResource(field), period_start)
                if result:
                    quota_limited_until, data_retained_until, needs_save = result

                    if needs_save:
                        org.save(update_fields=["usage"])

                    if data_retained_until and data_retained_until >= period_start.timestamp():
                        data_retained_orgs[field][org_id] = data_retained_until
                    elif quota_limited_until:
                        quota_limited_orgs[field][org_id] = quota_limited_until

    # Get the current quota limits so we can track to posthog if it changes
    orgs_with_changes = set()
    previously_quota_limited_team_tokens: Dict[str, Dict[str, int]] = {
        "events": {},
        "recordings": {},
        "rows_synced": {},
    }

    previously_data_retained_teams: Dict[str, Dict[str, int]] = {
        "events": {},
        "recordings": {},
        "rows_synced": {},
    }

    for field in quota_limited_orgs:
        previously_quota_limited_team_tokens[field] = list_limited_team_attributes(QuotaResource(field))
        previously_data_retained_teams[field] = list_limited_team_attributes(
            QuotaResource(field), QUOTA_OVERAGE_RETENTION_CACHE_KEY
        )

    quota_limited_teams: Dict[str, Dict[str, int]] = {"events": {}, "recordings": {}, "rows_synced": {}}
    data_retained_teams: Dict[str, Dict[str, int]] = {"events": {}, "recordings": {}, "rows_synced": {}}

    # Convert the org ids to team tokens
    for team in teams:
        for field in quota_limited_orgs:
            org_id = str(team.organization.id)
            if org_id in quota_limited_orgs[field]:
                quota_limited_teams[field][team.api_token] = quota_limited_orgs[field][org_id]

                # If the team was not previously quota limited, we add it to the list of orgs that were added
                if team.api_token not in previously_quota_limited_team_tokens[field]:
                    orgs_with_changes.add(org_id)
            elif org_id in data_retained_orgs[field]:
                data_retained_teams[field][team.api_token] = data_retained_orgs[field][org_id]
            else:
                # If the team was previously quota limited, we add it to the list of orgs that were removed
                if (
                    team.api_token in previously_quota_limited_team_tokens[field]
                    or team.api_token in previously_data_retained_teams[field]
                ):
                    orgs_with_changes.add(org_id)

    for org_id in orgs_with_changes:
        properties = {
            "quota_limited_events": quota_limited_orgs["events"].get(org_id, None),
            "quota_limited_recordings": quota_limited_orgs["events"].get(org_id, None),
            "quota_limited_rows_synced": quota_limited_orgs["rows_synced"].get(org_id, None),
        }

        report_organization_action(
            orgs_by_id[org_id],
            "organization quota limits changed",
            properties=properties,
            group_properties=properties,
        )

    if not dry_run:
        for field in data_retained_teams:
            replace_limited_team_tokens(
                QuotaResource(field), data_retained_teams[field], QUOTA_OVERAGE_RETENTION_CACHE_KEY
            )
        for field in quota_limited_teams:
            replace_limited_team_tokens(QuotaResource(field), quota_limited_teams[field])

    return quota_limited_orgs, data_retained_orgs
