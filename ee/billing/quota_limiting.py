import copy
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, TypedDict, cast, Any

import dateutil.parser
import posthoganalytics
from django.db.models import Q
from django.utils import timezone
from posthog.exceptions_capture import capture_exception

from posthog.cache_utils import cache_for
from posthog.constants import FlagRequestType
from posthog.event_usage import report_organization_action
from posthog.models.organization import Organization, OrganizationUsageInfo
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    convert_team_usage_rows_to_dict,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_recording_count_in_period,
    get_teams_with_rows_synced_in_period,
    get_teams_with_exceptions_captured_in_period,
    get_teams_with_feature_flag_requests_count_in_period,
    get_teams_with_api_queries_metrics,
)
from posthog.utils import get_current_day

QUOTA_LIMIT_DATA_RETENTION_FLAG = "retain-data-past-quota-limit"

QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS = 1
QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS = 3

# Lookup table for trust scores to grace period days
GRACE_PERIOD_DAYS: dict[int, int] = {
    3: 0,
    7: QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS,
    10: QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS,
}


class OrgQuotaLimitingInformation(TypedDict):
    quota_limited_until: Optional[int]
    quota_limiting_suspended_until: Optional[int]


class QuotaResource(Enum):
    EVENTS = "events"
    EXCEPTIONS = "exceptions"
    RECORDINGS = "recordings"
    ROWS_SYNCED = "rows_synced"
    FEATURE_FLAG_REQUESTS = "feature_flag_requests"
    API_QUERIES = "api_queries_read_bytes"


class QuotaLimitingCaches(Enum):
    QUOTA_LIMITER_CACHE_KEY = "@posthog/quota-limits/"
    QUOTA_LIMITING_SUSPENDED_KEY = "@posthog/quota-limiting-suspended/"


OVERAGE_BUFFER = {
    QuotaResource.EVENTS: 0,
    QuotaResource.EXCEPTIONS: 0,
    QuotaResource.RECORDINGS: 1000,
    QuotaResource.ROWS_SYNCED: 0,
    QuotaResource.FEATURE_FLAG_REQUESTS: 0,
    QuotaResource.API_QUERIES: 0,
}

TRUST_SCORE_KEYS = {
    QuotaResource.EVENTS: "events",
    QuotaResource.EXCEPTIONS: "exceptions",
    QuotaResource.RECORDINGS: "recordings",
    QuotaResource.ROWS_SYNCED: "rows_synced",
    QuotaResource.FEATURE_FLAG_REQUESTS: "feature_flags",
    QuotaResource.API_QUERIES: "api_queries",
}


class UsageCounters(TypedDict):
    events: int
    exceptions: int
    recordings: int
    rows_synced: int
    feature_flags: int
    api_queries_read_bytes: int


# -------------------------------------------------------------------------------------------------
# REDIS FUNCTIONS
# -------------------------------------------------------------------------------------------------

# In redis, we store the tokens in a sorted set with the timestamp as the score.
# E.g. key: @posthog/quota-limits/recordings, value: {"phc_PWDYpjHUGMyJOmLhQXB4il4So2lWh1BMjgdXi9FIXYK": 1737867600}
# E.g. key: @posthog/quota-limiting-suspended/recordings, value: {"phc_PWDYpjHUGMyJOmLhQXB4il4So2lWh1BMjgdXi9FIXYK": 1737867600}


def replace_limited_team_tokens(
    resource: QuotaResource, tokens: Mapping[str, int], cache_key: QuotaLimitingCaches
) -> None:
    """
    Replaces the all tokens in the cache with the new ones.
    """
    pipe = get_client().pipeline()
    pipe.delete(f"{cache_key.value}{resource.value}")
    if tokens:
        pipe.zadd(f"{cache_key.value}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)
    pipe.execute()


def add_limited_team_tokens(resource: QuotaResource, tokens: Mapping[str, int], cache_key: QuotaLimitingCaches) -> None:
    redis_client = get_client()
    redis_client.zadd(f"{cache_key.value}{resource.value}", tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)


def remove_limited_team_tokens(resource: QuotaResource, tokens: list[str], cache_key: QuotaLimitingCaches) -> None:
    # This check exists because the * unpacking operator
    # doesn't return anything with an empty list,
    # so zrem only receives one argument and it fails.
    if not tokens:
        return

    redis_client = get_client()
    redis_client.zrem(f"{cache_key.value}{resource.value}", *tokens)


@cache_for(timedelta(seconds=30), background_refresh=True)
def list_limited_team_attributes(resource: QuotaResource, cache_key: QuotaLimitingCaches) -> list[str]:
    """
    Returns a list of team attributes that are still under quota limits. Uses Redis sorted set
    where scores are expiration timestamps. Only returns attributes whose limits haven't expired yet.
    Note: this is cached for 30 seconds so it's not always up to date.
    """
    now = timezone.now()
    redis_client = get_client()
    results = redis_client.zrangebyscore(f"{cache_key.value}{resource.value}", min=now.timestamp(), max="+inf")
    return [x.decode("utf-8") for x in results]


# -------------------------------------------------------------------------------------------------
# MAIN FUNCTIONS
# -------------------------------------------------------------------------------------------------


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
    quota_limited_until = summary.get("quota_limited_until", None)
    quota_limiting_suspended_until = summary.get("quota_limiting_suspended_until", None)
    # Note: customer_trust_scores can initially be null. This should only happen after the initial migration and therefore
    # should be removed once all existing customers have this field set.
    trust_score = (
        organization.customer_trust_scores.get(TRUST_SCORE_KEYS[resource]) if organization.customer_trust_scores else 0
    )

    # Flow for checking quota limits:
    # 1. ignore the limits
    #       a. not over limit
    #       b. 'never_drop_data' set or a high trust score (15)
    #       c. feature flag to retain data past quota limit
    # 2. limit the org
    #       a. already being limited
    #       b. no trust score
    #       b. low trust (3)
    # 3. add quote suspension
    #       a. medium / medium high trust (7, 10)

    # 1a. not over limit
    if not is_over_limit:
        if quota_limiting_suspended_until or quota_limited_until:
            # If they are not over limit, we want to remove the suspension if it exists
            report_organization_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspension removed",
                    "current_usage": usage + todays_usage,
                    "resource": resource.value,
                    "quota_limiting_suspended_until": quota_limiting_suspended_until,
                },
            )
            update_organization_usage_fields(
                organization, resource, {"quota_limited_until": None, "quota_limiting_suspended_until": None}
            )
        return None

    # 1b. never drop or high trust
    if organization.never_drop_data or trust_score == 15:
        report_organization_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "ignored",
                "current_usage": usage + todays_usage,
                "resource": resource.value,
                "never_drop_data": organization.never_drop_data,
                "trust_score": trust_score,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": None, "quota_limiting_suspended_until": None}
        )
        return None

    team_tokens = get_team_attribute_by_quota_resource(organization)
    team_being_limited = any(x in previously_quota_limited_team_tokens for x in team_tokens)

    # 2a. already being limited
    if team_being_limited or quota_limited_until:
        # They are already being limited, do not update their status.
        report_organization_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "already limited",
                "current_usage": usage + todays_usage,
                "resource": resource.value,
                "quota_limited_until": billing_period_end,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None}
        )
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }

    # 1c. feature flag to retain data past quota limit
    # Note: this is rarely used but we want to keep it around for now and this is after check if they are already being limited
    if posthoganalytics.feature_enabled(
        QUOTA_LIMIT_DATA_RETENTION_FLAG,
        str(organization.id),
        groups={"organization": str(organization.id)},
        group_properties={"organization": {"id": str(organization.id)}},
    ):
        # Don't drop data for this org but record that they would have been limited.
        report_organization_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "ignored",
                "current_usage": usage + todays_usage,
                "resource": resource.value,
                "feature_flag": QUOTA_LIMIT_DATA_RETENTION_FLAG,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": None, "quota_limiting_suspended_until": None}
        )
        return None

    _, today_end = get_current_day()

    # Now we check the trust score
    # These trust score levels are defined in billing::customer::TrustScores.
    # Please keep the logic and levels in sync with what is defined in billing.

    # 2b. no trust score
    if not trust_score:
        # Set them to the default trust score and immediately limit
        if trust_score is None:
            organization.customer_trust_scores[resource.value] = 0
            organization.save(update_fields=["customer_trust_scores"])
        report_organization_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "suspended",
                "current_usage": usage + todays_usage,
                "resource": resource.value,
                "trust_score": trust_score,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None}
        )
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }

    # 2c. low trust
    elif trust_score == 3:
        # Low trust, immediately limit
        report_organization_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "suspended",
                "current_usage": usage + todays_usage,
                "resource": resource.value,
                "trust_score": trust_score,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None}
        )
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }

    # 3. medium / medium high trust
    elif trust_score in [7, 10]:
        grace_period_days = GRACE_PERIOD_DAYS[trust_score]

        # If the suspension is expired or never set, we want to suspend the limit for a grace period
        if not quota_limiting_suspended_until or (
            (datetime.fromtimestamp(quota_limiting_suspended_until) - timedelta(grace_period_days)).timestamp()
            < billing_period_start
        ):
            report_organization_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspended",
                    "current_usage": usage + todays_usage,
                    "resource": resource.value,
                    "grace_period_days": grace_period_days,
                    "usage": organization.usage,
                    "summary": summary,
                    "organization_id": organization.id,
                    "quota_limiting_suspended_until": quota_limiting_suspended_until,
                    "billing_period_start": billing_period_start,
                    "billing_period_end": billing_period_end,
                    "if_check": not quota_limiting_suspended_until
                    or (
                        (
                            (
                                datetime.fromtimestamp(quota_limiting_suspended_until) - timedelta(grace_period_days)
                            ).timestamp()
                            < billing_period_start
                        )
                        if quota_limiting_suspended_until
                        else "no quota_limiting_suspended_until"
                    ),
                    "if_check_2": (
                        (
                            datetime.fromtimestamp(quota_limiting_suspended_until) - timedelta(grace_period_days)
                        ).timestamp()
                        if quota_limiting_suspended_until
                        else "no quota_limiting_suspended_until"
                    ),
                    "if_check_3": (
                        (
                            (
                                datetime.fromtimestamp(quota_limiting_suspended_until) - timedelta(grace_period_days)
                            ).timestamp()
                            < billing_period_start
                        )
                        if quota_limiting_suspended_until
                        else "no quota_limiting_suspended_until"
                    ),
                },
            )
            quota_limiting_suspended_until = round((today_end + timedelta(days=grace_period_days)).timestamp())
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": None, "quota_limiting_suspended_until": quota_limiting_suspended_until},
            )
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }

        elif today_end.timestamp() <= quota_limiting_suspended_until:
            # If the suspension is still active (after today's end), we want to return the existing suspension date
            report_organization_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspension not expired",
                    "current_usage": usage + todays_usage,
                    "resource": resource.value,
                    "quota_limiting_suspended_until": quota_limiting_suspended_until,
                },
            )
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": None, "quota_limiting_suspended_until": quota_limiting_suspended_until},
            )
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }
        else:
            # If the suspension is expired, we want to limit the org
            report_organization_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspended expired",
                    "current_usage": usage + todays_usage,
                    "resource": resource.value,
                },
            )
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None},
            )
            return {
                "quota_limited_until": billing_period_end,
                "quota_limiting_suspended_until": None,
            }
    else:
        # Should never reach here - return the default behavior just to be safe
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None}
        )
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }


def update_org_billing_quotas(organization: Organization):
    """
    This method is basically update_all_orgs_billing_quotas but for a single org. It's called more often
    when the user loads the billing page and when usage reports are run.
    """
    _, today_end = get_current_day()
    if not organization.usage:
        return None

    for resource in [
        QuotaResource.EVENTS,
        QuotaResource.EXCEPTIONS,
        QuotaResource.RECORDINGS,
        QuotaResource.ROWS_SYNCED,
        QuotaResource.FEATURE_FLAG_REQUESTS,
        QuotaResource.API_QUERIES,
    ]:
        previously_quota_limited_team_tokens = list_limited_team_attributes(
            resource,
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            # Get the teams tokens (e.g. ["phc_123", "phc_456"])
        )

        # Get the quota limiting information (e.g. {"quota_limited_until": 1737867600, "quota_limiting_suspended_until": 1737867600})
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


def set_org_usage_summary(
    organization: Organization,
    new_usage: Optional[OrganizationUsageInfo] = None,
    todays_usage: Optional[UsageCounters] = None,
) -> bool:
    # TRICKY: We don't want to overwrite the "todays_usage" value unless the usage from the billing service is different than what we have locally.
    # Also we want to return if anything changed so that the caller can update redis

    has_changed = False
    new_usage = new_usage or cast(Optional[OrganizationUsageInfo], organization.usage)
    original_usage = cast(dict, copy.deepcopy(organization.usage)) if organization.usage else {}

    if not new_usage:
        # If we are not setting it and it doesn't exist we can't update it
        return False

    new_usage = copy.deepcopy(new_usage)

    for field in [
        "events",
        "exceptions",
        "recordings",
        "rows_synced",
        "feature_flag_requests",
        "api_queries_read_bytes",
    ]:
        original_field_usage = original_usage.get(field, {}) if original_usage else {}
        resource_usage = cast(dict, new_usage.get(field, {"limit": None, "usage": 0, "todays_usage": 0}))

        if not resource_usage:
            continue

        # Preserve quota_limited_until and quota_limiting_suspended_until if it exists
        if (
            original_field_usage
            and "quota_limited_until" in original_field_usage
            and "quota_limited_until" not in resource_usage
        ):
            resource_usage["quota_limited_until"] = original_field_usage["quota_limited_until"]
        if (
            original_field_usage
            and "quota_limiting_suspended_until" in original_field_usage
            and "quota_limiting_suspended_until" not in resource_usage
        ):
            resource_usage["quota_limiting_suspended_until"] = original_field_usage["quota_limiting_suspended_until"]

        if todays_usage:
            resource_usage["todays_usage"] = todays_usage.get(field, 0)
        else:
            # TRICKY: If we are not explicitly setting todays_usage, we want to reset it to 0 IF the incoming new_usage is different
            original_usage_value = original_field_usage.get("usage") if original_field_usage else None
            if original_usage_value != resource_usage.get("usage"):
                resource_usage["todays_usage"] = 0
            else:
                todays_usage_value = original_field_usage.get("todays_usage", 0) if original_field_usage else 0
                resource_usage["todays_usage"] = todays_usage_value

    has_changed = new_usage != organization.usage
    organization.usage = new_usage

    return has_changed


def update_all_orgs_billing_quotas(
    dry_run: bool = False,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """
    This is called on a cron job every 30 minutes to update all orgs with their quotas.
    Specifically it's update quota_limited_until and quota_limiting_suspended_until in their usage
    field on the Organization model.

    # Start and end of the current day
    """
    period = get_current_day()
    period_start, period_end = period

    api_queries_usage = get_teams_with_api_queries_metrics(period_start, period_end)

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = {
        "teams_with_event_count_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_billable_event_count_in_period(period_start, period_end)
        ),
        "teams_with_exceptions_captured_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_exceptions_captured_in_period(period_start, period_end)
        ),
        "teams_with_recording_count_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_recording_count_in_period(period_start, period_end)
        ),
        "teams_with_rows_synced_in_period": convert_team_usage_rows_to_dict(
            get_teams_with_rows_synced_in_period(period_start, period_end)
        ),
        "teams_with_decide_requests_count": convert_team_usage_rows_to_dict(
            get_teams_with_feature_flag_requests_count_in_period(period_start, period_end, FlagRequestType.DECIDE)
        ),
        "teams_with_local_evaluation_requests_count": convert_team_usage_rows_to_dict(
            get_teams_with_feature_flag_requests_count_in_period(
                period_start, period_end, FlagRequestType.LOCAL_EVALUATION
            )
        ),
        "teams_with_api_queries_read_bytes": convert_team_usage_rows_to_dict(api_queries_usage["read_bytes"]),
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
        decide_requests = all_data["teams_with_decide_requests_count"].get(team.id, 0)
        local_evaluation_requests = all_data["teams_with_local_evaluation_requests_count"].get(team.id, 0)

        team_report = UsageCounters(
            events=all_data["teams_with_event_count_in_period"].get(team.id, 0),
            exceptions=all_data["teams_with_exceptions_captured_in_period"].get(team.id, 0),
            recordings=all_data["teams_with_recording_count_in_period"].get(team.id, 0),
            rows_synced=all_data["teams_with_rows_synced_in_period"].get(team.id, 0),
            feature_flags=decide_requests + (local_evaluation_requests * 10),  # Same weighting as in _get_team_report
            api_queries_read_bytes=all_data["teams_with_api_queries_read_bytes"].get(team.id, 0),
        )

        org_id = str(team.organization.id)

        if org_id not in todays_usage_report:
            orgs_by_id[org_id] = team.organization
            todays_usage_report[org_id] = team_report.copy()
        else:
            org_report = todays_usage_report[org_id]
            for field in team_report:
                org_report[field] += team_report[field]  # type: ignore

    # Now we have the usage for all orgs for the current day
    # orgs_by_id is a dict of orgs by id (e.g. {"018e9acf-b488-0000-259c-534bcef40359": <Organization: 018e9acf-b488-0000-259c-534bcef40359>})
    # todays_usage_report is a dict of orgs by id with their usage for the current day (e.g. {"018e9acf-b488-0000-259c-534bcef40359": {"events": 100, "exceptions": 100, "recordings": 100, "rows_synced": 100, "feature_flag_requests": 100, "api_queries_read_bytes": 100}})
    quota_limited_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limiting_suspended_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}

    # Get the current quota limits so we can track to PostHog if it changes
    orgs_with_changes = set()
    previously_quota_limited_team_tokens: dict[str, list[str]] = {x.value: [] for x in QuotaResource}

    # All teams that are currently under quota limits
    for field in quota_limited_orgs:
        previously_quota_limited_team_tokens[field] = list_limited_team_attributes(
            QuotaResource(field), QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
    # We have the teams that are currently under quota limits
    # previously_quota_limited_team_tokens is a dict of resources to team tokens from redis (e.g. {"events": ["phc_123", "phc_456"], "exceptions": ["phc_123", "phc_456"], "recordings": ["phc_123", "phc_456"], "rows_synced": ["phc_123", "phc_456"], "feature_flag_requests": ["phc_123", "phc_456"], "api_queries_read_bytes": ["phc_123", "phc_456"]})

    # Find all orgs that should be rate limited
    report_index = 1
    for org_id, todays_report in todays_usage_report.items():
        try:
            org = orgs_by_id[org_id]

            if org.usage and org.usage.get("period"):
                if set_org_usage_summary(org, todays_usage=todays_report):
                    org.save(update_fields=["usage"])

                for field in [
                    "events",
                    "exceptions",
                    "recordings",
                    "rows_synced",
                    "feature_flag_requests",
                    "api_queries_read_bytes",
                ]:
                    # for each organization, we check if the current usage + today's unreported usage is over the limit
                    result = org_quota_limited_until(
                        org, QuotaResource(field), previously_quota_limited_team_tokens[field]
                    )
                    if result:
                        quota_limited_until = result.get("quota_limited_until")
                        limiting_suspended_until = result.get("quota_limiting_suspended_until")
                        if limiting_suspended_until:
                            quota_limiting_suspended_orgs[field][org_id] = limiting_suspended_until
                        elif quota_limited_until:
                            quota_limited_orgs[field][org_id] = quota_limited_until

            report_index += 1
        except Exception as e:
            capture_exception(e)

    # Now we have the teams that are currently under quota limits
    # quota_limited_orgs is a dict of resources to org ids (e.g. {"events": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "exceptions": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "recordings": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "rows_synced": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "feature_flag_requests": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "api_queries_read_bytes": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}})
    # quota_limiting_suspended_orgs is a dict of resources to org ids (e.g. {"events": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "exceptions": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "recordings": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "rows_synced": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "feature_flag_requests": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "api_queries_read_bytes": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}})

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

    # Now we have the teams that are currently under quota limits
    # quota_limited_teams is a dict of resources to team tokens (e.g. {"events": {"phc_123": 1737867600}, "exceptions": {"phc_123": 1737867600}, "recordings": {"phc_123": 1737867600}, "rows_synced": {"phc_123": 1737867600}, "feature_flag_requests": {"phc_123": 1737867600}, "api_queries_read_bytes": {"phc_123": 1737867600}})
    # quota_limiting_suspended_teams is a dict of resources to team tokens (e.g. {"events": {"phc_123": 1737867600}, "exceptions": {"phc_123": 1737867600}, "recordings": {"phc_123": 1737867600}, "rows_synced": {"phc_123": 1737867600}, "feature_flag_requests": {"phc_123": 1737867600}, "api_queries_read_bytes": {"phc_123": 1737867600}})

    for org_id in orgs_with_changes:
        properties = {
            "quota_limited_events": quota_limited_orgs["events"].get(org_id, None),
            "quota_limited_exceptions": quota_limited_orgs["exceptions"].get(org_id, None),
            "quota_limited_recordings": quota_limited_orgs["recordings"].get(org_id, None),
            "quota_limited_rows_synced": quota_limited_orgs["rows_synced"].get(org_id, None),
            "quota_limited_feature_flags": quota_limited_orgs["feature_flag_requests"].get(org_id, None),
            "quota_limited_api_queries": quota_limited_orgs["api_queries_read_bytes"].get(org_id, None),
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


# -------------------------------------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------------------------------------


def get_team_attribute_by_quota_resource(organization: Organization) -> list[str]:
    team_tokens: list[str] = [x for x in list(organization.teams.values_list("api_token", flat=True)) if x]

    if not team_tokens:
        capture_exception(Exception(f"quota_limiting: No team tokens found for organization: {organization.id}"))

    return team_tokens


def update_organization_usage_field(organization: Organization, resource: QuotaResource, key: str, value: Any) -> None:
    """
    Helper function to safely update a field within organization.usage[resource][key]
    If value is None, the key will be deleted.

    Note: For updating multiple fields at once, use update_organization_usage_fields instead
    to reduce database calls.
    """
    update_organization_usage_fields(organization, resource, {key: value})


def update_organization_usage_fields(
    organization: Organization, resource: QuotaResource, fields: dict[str, Any]
) -> None:
    """
    Helper function to safely update multiple fields within organization.usage[resource]
    If a value is None, the key will be deleted.
    This is more efficient than calling update_organization_usage_field multiple times
    as it only makes one database call.
    """
    if not organization.usage:
        capture_exception(Exception(f"quota_limiting: No usage found for organization: {organization.id}"))
        return
    if resource.value not in organization.usage:
        capture_exception(
            Exception(
                f"quota_limiting: No usage found for resource: {resource.value} for organization: {organization.id}"
            )
        )
        return

    for key, value in fields.items():
        if value is None:
            if key in organization.usage[resource.value]:
                del organization.usage[resource.value][key]
        else:
            organization.usage[resource.value][key] = value

    organization.save(update_fields=["usage"])
