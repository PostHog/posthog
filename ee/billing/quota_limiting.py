import copy
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, TypedDict, cast

import dateutil.parser
import posthoganalytics
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

QUOTA_LIMIT_DATA_RETENTION_FLAG = "retain-data-past-quota-limit"

QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS = 1
QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS = 3


class OrgQuotaLimitingInformation(TypedDict):
    quota_limited_until: Optional[int]
    quota_limiting_suspended_until: Optional[int]


class QuotaResource(Enum):
    EVENTS = "events"
    RECORDINGS = "recordings"
    ROWS_SYNCED = "rows_synced"


class QuotaLimitingCaches(Enum):
    QUOTA_LIMITER_CACHE_KEY = "@posthog/quota-limits/"
    QUOTA_LIMITING_SUSPENDED_KEY = "@posthog/quota-limiting-suspended/"


OVERAGE_BUFFER = {
    QuotaResource.EVENTS: 0,
    QuotaResource.RECORDINGS: 1000,
    QuotaResource.ROWS_SYNCED: 0,
}


def replace_limited_team_tokens(
    resource: QuotaResource, tokens: Mapping[str, int], cache_key: QuotaLimitingCaches
) -> None:
    pipe = get_client().pipeline()
    pipe.delete(f"{cache_key.value}{resource.value}")
    if tokens:
        pipe.zadd(f"{cache_key.value}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)
    pipe.execute()


def add_limited_team_tokens(resource: QuotaResource, tokens: Mapping[str, int], cache_key: QuotaLimitingCaches) -> None:
    redis_client = get_client()
    redis_client.zadd(f"{cache_key.value}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)


def remove_limited_team_tokens(resource: QuotaResource, tokens: list[str], cache_key: QuotaLimitingCaches) -> None:
    redis_client = get_client()
    redis_client.zrem(f"{cache_key.value}{resource.value}", *tokens)


@cache_for(timedelta(seconds=30), background_refresh=True)
def list_limited_team_attributes(resource: QuotaResource, cache_key: QuotaLimitingCaches) -> list[str]:
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{cache_key.value}{resource.value}", min=now.timestamp(), max="+inf")
    return [x.decode("utf-8") for x in results]


class UsageCounters(TypedDict):
    events: int
    recordings: int
    rows_synced: int


def org_quota_limited_until(
    organization: Organization, resource: QuotaResource, previously_quota_limited_team_tokens: list[str]
) -> Optional[OrgQuotaLimitingInformation]:
    if not organization.usage:
        return None

    summary = organization.usage.get(resource.value, {})
    if not summary:
        return None
    usage = summary.get("usage", 0)
    todays_usage = summary.get("todays_usage", 0)
    limit = summary.get("limit")

    if limit is None:
        return None

    is_over_limit = usage + todays_usage >= limit + OVERAGE_BUFFER[resource]
    billing_period_start = round(dateutil.parser.isoparse(organization.usage["period"][0]).timestamp())
    billing_period_end = round(dateutil.parser.isoparse(organization.usage["period"][1]).timestamp())
    quota_limiting_suspended_until = summary.get("quota_limiting_suspended_until", None)
    # Note: customer_trust_scores can initially be null. This should only happen after the initial migration and therefore
    # should be removed once all existing customers have this field set.
    trust_score = organization.customer_trust_scores.get(resource.value) if organization.customer_trust_scores else 0

    if not is_over_limit:
        if quota_limiting_suspended_until:
            quota_limiting_suspended_until = None
            del summary["quota_limiting_suspended_until"]
            organization.save(update_fields=["usage"])

            return {"quota_limited_until": None, "quota_limiting_suspended_until": None}
        return None

    if organization.never_drop_data or trust_score == 15:
        return None

    team_tokens = get_team_attribute_by_quota_resource(organization)
    team_being_limited = any(x in previously_quota_limited_team_tokens for x in team_tokens)

    if team_being_limited:
        # They are already being limited, do not update their status.
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }

    if posthoganalytics.feature_enabled(
        QUOTA_LIMIT_DATA_RETENTION_FLAG,
        str(organization.id),
        groups={"organization": str(organization.id)},
        group_properties={"organization": {"id": str(organization.id)}},
    ):
        # Don't drop data for this org but record that they would have been limited.
        report_organization_action(
            organization, "quota limiting suspended", properties={"current_usage": usage + todays_usage}
        )
        return None

    _, today_end = get_current_day()

    # These trust score levels are defined in billing::customer::TrustScores.
    # Please keep the logic and levels in sync with what is defined in billing.
    if not trust_score:
        # Set them to the default trust score and immediately limit
        if trust_score is None:
            organization.customer_trust_scores[resource.value] = 0
            organization.save(update_fields=["customer_trust_scores", "usage"])
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }
    elif trust_score == 3:
        # Low trust, immediately limit
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }
    elif trust_score == 7:
        # If limiting suspended was set in the previous period or was never set, update it.
        if (
            not quota_limiting_suspended_until
            or (
                datetime.fromtimestamp(quota_limiting_suspended_until)
                - timedelta(QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS)
            ).timestamp()
            < billing_period_start
        ):
            # Medium trust, retain data for one day
            report_organization_action(
                organization, "quota limiting suspended", properties={"current_usage": usage + todays_usage}
            )
            quota_limiting_suspended_until = round(
                (today_end + timedelta(days=QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS)).timestamp()
            )

            summary["quota_limiting_suspended_until"] = quota_limiting_suspended_until
            organization.save(update_fields=["usage"])
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }
        elif today_end.timestamp() <= quota_limiting_suspended_until:
            # Return existing quota limiting date
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }
    elif trust_score == 10:
        # If limitng suspended was set in the previous period or was never set, update it.
        if (
            not quota_limiting_suspended_until
            or (
                datetime.fromtimestamp(quota_limiting_suspended_until)
                - timedelta(QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS)
            ).timestamp()
            < billing_period_start
        ):
            # Medium high trust, retain data for three days
            report_organization_action(
                organization, "quota limiting suspended", properties={"current_usage": usage + todays_usage}
            )
            quota_limiting_suspended_until = round(
                (today_end + timedelta(days=QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS)).timestamp()
            )
            summary["quota_limiting_suspended_until"] = quota_limiting_suspended_until
            organization.save(update_fields=["usage"])
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }
        elif today_end.timestamp() <= quota_limiting_suspended_until:
            # Return existing quota limiting date
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }
    return {
        "quota_limited_until": billing_period_end,
        "quota_limiting_suspended_until": None,
    }


def sync_org_quota_limits(organization: Organization):
    _, today_end = get_current_day()
    if not organization.usage:
        return None

    for resource in [QuotaResource.EVENTS, QuotaResource.RECORDINGS, QuotaResource.ROWS_SYNCED]:
        previously_quota_limited_team_tokens = list_limited_team_attributes(
            resource, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        team_attributes = get_team_attribute_by_quota_resource(organization)
        result = org_quota_limited_until(organization, resource, previously_quota_limited_team_tokens)

        if result:
            quota_limited_until = result.get("quota_limited_until")
            limiting_suspended_until = result.get("quota_limiting_suspended_until")

            if quota_limited_until:
                add_limited_team_tokens(
                    resource,
                    {x: quota_limited_until for x in team_attributes},
                    QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
                )
            elif limiting_suspended_until and limiting_suspended_until >= today_end.timestamp():
                add_limited_team_tokens(
                    resource,
                    {x: limiting_suspended_until for x in team_attributes},
                    QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY,
                )
            else:
                remove_limited_team_tokens(resource, team_attributes, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
                remove_limited_team_tokens(resource, team_attributes, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY)
        else:
            remove_limited_team_tokens(resource, team_attributes, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)
            remove_limited_team_tokens(resource, team_attributes, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY)


def get_team_attribute_by_quota_resource(organization: Organization):
    team_tokens: list[str] = [x for x in list(organization.teams.values_list("api_token", flat=True)) if x]

    if not team_tokens:
        capture_exception(Exception(f"quota_limiting: No team tokens found for organization: {organization.id}"))
        return

    return team_tokens


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
            org_usage_data = organization.usage or {}
            org_field_usage = org_usage_data.get(field, {}) or {}
            org_usage = org_field_usage.get("usage")
            # TRICKY: If we are not explictly setting todays_usage, we want to reset it to 0 IF the incoming new_usage is different
            if org_usage != resource_usage.get("usage"):
                resource_usage["todays_usage"] = 0
            else:
                resource_usage["todays_usage"] = organization.usage.get(field, {}).get("todays_usage") or 0

    has_changed = new_usage != organization.usage
    organization.usage = new_usage

    return has_changed


def update_all_org_billing_quotas(
    dry_run: bool = False,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    period = get_current_day()
    period_start, period_end = period

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = {
        "teams_with_event_count_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_billable_event_count_in_period(period_start, period_end)
        ),
        "teams_with_recording_count_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_recording_count_in_period(period_start, period_end)
        ),
        "teams_with_rows_synced_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_rows_synced_in_period(period_start, period_end)
        ),
    }

    teams: Sequence[Team] = list(
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only(
            "id",
            "api_token",
            "organization__id",
            "organization__usage",
            "organization__created_at",
            "organization__never_drop_data",
        )
    )

    todays_usage_report: dict[str, UsageCounters] = {}
    orgs_by_id: dict[str, Organization] = {}

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

    quota_limited_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limiting_suspended_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}

    # Get the current quota limits so we can track to poshog if it changes
    orgs_with_changes = set()
    previously_quota_limited_team_tokens: dict[str, list[str]] = {x.value: [] for x in QuotaResource}

    for field in quota_limited_orgs:
        previously_quota_limited_team_tokens[field] = list_limited_team_attributes(
            QuotaResource(field), QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )

    # Find all orgs that should be rate limited
    for org_id, todays_report in todays_usage_report.items():
        org = orgs_by_id[org_id]

        # if we don't have limits set from the billing service, we can't risk rate limiting existing customers
        if org.usage and org.usage.get("period"):
            if set_org_usage_summary(org, todays_usage=todays_report):
                org.save(update_fields=["usage"])

            for field in ["events", "recordings", "rows_synced"]:
                # for each organization, we check if the current usage + today's unreported usage is over the limit
                result = org_quota_limited_until(org, QuotaResource(field), previously_quota_limited_team_tokens[field])
                if result:
                    quota_limited_until = result.get("quota_limited_until")
                    limiting_suspended_until = result.get("quota_limiting_suspended_until")
                    if limiting_suspended_until:
                        quota_limiting_suspended_orgs[field][org_id] = limiting_suspended_until
                    elif quota_limited_until:
                        quota_limited_orgs[field][org_id] = quota_limited_until

    quota_limited_teams: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limiting_suspended_teams: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}

    # Convert the org ids to team tokens
    for team in teams:
        for field in quota_limited_orgs:
            org_id = str(team.organization.id)
            if org_id in quota_limited_orgs[field]:
                quota_limited_teams[field][team.api_token] = quota_limited_orgs[field][org_id]

                # If the team was not previously quota limited, we add it to the list of orgs that were added
                if team.api_token not in previously_quota_limited_team_tokens[field]:
                    orgs_with_changes.add(org_id)
            elif org_id in quota_limiting_suspended_orgs[field]:
                quota_limiting_suspended_teams[field][team.api_token] = quota_limiting_suspended_orgs[field][org_id]
            else:
                # If the team was previously quota limited, we add it to the list of orgs that were removed
                if team.api_token in previously_quota_limited_team_tokens[field]:
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
        for field in quota_limited_teams:
            replace_limited_team_tokens(
                QuotaResource(field), quota_limited_teams[field], QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
            )
        for field in quota_limiting_suspended_teams:
            replace_limited_team_tokens(
                QuotaResource(field),
                quota_limiting_suspended_teams[field],
                QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY,
            )

    return quota_limited_orgs, quota_limiting_suspended_orgs
