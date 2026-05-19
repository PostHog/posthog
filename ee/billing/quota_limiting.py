import copy
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import Enum
from time import time
from typing import Any, Optional, TypedDict, cast

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.db.models.expressions import RawSQL
from django.utils import timezone

import structlog
import dateutil.parser
import posthoganalytics

from posthog.cache_utils import cache_for
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.constants import FlagRequestType
from posthog.event_usage import report_organization_action
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization, OrganizationUsageInfo
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    convert_team_usage_rows_to_dict,
    get_teams_with_ai_credits_used_in_period,
    get_teams_with_ai_event_count_in_period,
    get_teams_with_api_queries_metrics,
    get_teams_with_billable_event_count_in_period,
    get_teams_with_cdp_billable_invocations_in_period,
    get_teams_with_exceptions_captured_in_period,
    get_teams_with_feature_flag_requests_count_in_period,
    get_teams_with_logs_bytes_in_period,
    get_teams_with_recording_count_in_period,
    get_teams_with_rows_exported_in_period,
    get_teams_with_rows_synced_in_period,
    get_teams_with_survey_responses_count_in_period,
    get_teams_with_workflow_billable_invocations_in_period,
    get_teams_with_workflow_emails_sent_in_period,
)
from posthog.utils import get_current_day

logger = structlog.get_logger(__name__)

QUOTA_LIMIT_DATA_RETENTION_FLAG = "retain-data-past-quota-limit"

QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS = 1
QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS = 3
QUOTA_LIMIT_HIGH_TRUST_GRACE_PERIOD_DAYS = 5

# Feature flags always get a 2-day grace period regardless of trust score
FEATURE_FLAGS_GRACE_PERIOD_DAYS = 2

# Lookup table for trust scores to grace period days
GRACE_PERIOD_DAYS: dict[int, int] = {
    3: 0,
    7: QUOTA_LIMIT_MEDIUM_TRUST_GRACE_PERIOD_DAYS,
    10: QUOTA_LIMIT_MEDIUM_HIGH_TRUST_GRACE_PERIOD_DAYS,
    15: QUOTA_LIMIT_HIGH_TRUST_GRACE_PERIOD_DAYS,
}


class OrgQuotaLimitingInformation(TypedDict):
    quota_limited_until: Optional[int]
    quota_limiting_suspended_until: Optional[int]


# These quota resource identifiers match billing default_plans_config.yml usage_key.
# These keys should match OrganizationUsageInfo and UsageCounters.
class QuotaResource(Enum):
    EVENTS = "events"
    EXCEPTIONS = "exceptions"
    RECORDINGS = "recordings"
    ROWS_SYNCED = "rows_synced"
    FEATURE_FLAG_REQUESTS = "feature_flag_requests"
    API_QUERIES = "api_queries_read_bytes"
    SURVEY_RESPONSES = "survey_responses"
    LLM_EVENTS = "llm_events"
    CDP_TRIGGER_EVENTS = "cdp_trigger_events"
    ROWS_EXPORTED = "rows_exported"
    AI_CREDITS = "ai_credits"
    WORKFLOW_EMAILS = "workflow_emails"
    WORKFLOW_DESTINATIONS = "workflow_destinations_dispatched"
    LOGS_MB_INGESTED = "logs_mb_ingested"


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
    QuotaResource.SURVEY_RESPONSES: 0,
    QuotaResource.LLM_EVENTS: 0,
    QuotaResource.CDP_TRIGGER_EVENTS: 0,
    QuotaResource.ROWS_EXPORTED: 0,
    QuotaResource.AI_CREDITS: 0,
    QuotaResource.WORKFLOW_EMAILS: 0,
    QuotaResource.WORKFLOW_DESTINATIONS: 0,
    QuotaResource.LOGS_MB_INGESTED: 0,
}

# These resources are exempt from any grace periods, whether trust-based or never_drop_data
GRACE_PERIOD_EXEMPT_RESOURCES: set[QuotaResource] = {
    QuotaResource.AI_CREDITS,
}


# These should be kept in sync with OrganizationUsageInfo and QuotaResource values.
class UsageCounters(TypedDict):
    events: int
    exceptions: int
    recordings: int
    rows_synced: int
    feature_flag_requests: int
    api_queries_read_bytes: int
    survey_responses: int
    llm_events: int
    cdp_trigger_events: int
    rows_exported: int
    ai_credits: int
    workflow_emails: int
    workflow_destinations_dispatched: int
    logs_mb_ingested: int


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


def is_team_limited(team_api_token: str, resource: QuotaResource, cache_key: QuotaLimitingCaches) -> bool:
    limited_team_attributes = list_limited_team_attributes(resource, cache_key)
    return team_api_token in limited_team_attributes


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

    # - customer_trust_scores can be empty {} for orgs not yet synced from billing. Default to 0 (no grace period)
    # - customer_trust_scores in posthog_organization use usage_key values (matching QuotaResource values)
    # - The billing service stores trust scores by product_key, but billing_manager.py translates them to usage_key
    #   when syncing billing_customer to posthog_organization
    trust_score = organization.customer_trust_scores.get(resource.value) if organization.customer_trust_scores else 0

    # Flow for checking quota limits:
    # 1. ignore the limits
    #       a. not over limit
    #       b. 'never_drop_data' set
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

    # 1b. never drop
    if resource not in GRACE_PERIOD_EXEMPT_RESOURCES and organization.never_drop_data:
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

    # Set minimum grace period for specific resources
    minimum_grace_period = 0
    if resource == QuotaResource.FEATURE_FLAG_REQUESTS:
        minimum_grace_period = FEATURE_FLAGS_GRACE_PERIOD_DAYS

    # Now we check the trust score
    # These trust score levels are defined in billing::customer::TrustScores.
    # Please keep the logic and levels in sync with what is defined in billing.

    # 2b. no trust score
    if (not trust_score or resource in GRACE_PERIOD_EXEMPT_RESOURCES) and minimum_grace_period == 0:
        # Set them to the default trust score and immediately limit
        if trust_score is None:
            organization.customer_trust_scores = {**(organization.customer_trust_scores or {}), resource.value: 0}
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
    elif trust_score == 3 and minimum_grace_period == 0:
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

    # 3. medium / medium high / high trust
    elif trust_score in [7, 10, 15] or minimum_grace_period > 0:
        trust_score_grace_period = GRACE_PERIOD_DAYS.get(trust_score, 0)
        grace_period_days = max(trust_score_grace_period, minimum_grace_period)

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
                    "trust_score": trust_score,
                    "trust_score_grace_period": trust_score_grace_period,
                    "minimum_grace_period": minimum_grace_period,
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

    for resource in QuotaResource:
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
                    dict.fromkeys(team_attributes, quota_limited_until),
                    QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
                )
            elif limiting_suspended_until and limiting_suspended_until >= today_end.timestamp():
                add_limited_team_tokens(
                    resource,
                    dict.fromkeys(team_attributes, limiting_suspended_until),
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

    for resource in QuotaResource:
        field = resource.value
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


def _patch_organization_usage_jsonb(organization: Organization, ops: Sequence[tuple[list[str], Any]]) -> None:
    """
    Applies a sequence of partial-write operations to `posthog_organization.usage` for
    one row, composing them into a single nested `jsonb_set` / `#-` expression so that
    only the targeted paths are touched and billing-owned siblings (e.g. `usage`,
    `limit`, `period`) are preserved against stale in-memory snapshots.

    Each op is `(path, value)`: a `None` value deletes the path, anything else sets it
    (json-encoded). The UPDATE goes through the ORM via `RawSQL`, so the table name
    comes from `Organization._meta.db_table` rather than being hardcoded. Like
    `QuerySet.update()` this bypasses model signals — callers must mirror in-memory
    state separately if they need it visible later in the same request/cron iteration.
    """
    if not ops:
        return

    sql_expr = "usage"
    params: list[Any] = []
    for path, value in ops:
        if value is None:
            sql_expr = f"({sql_expr}) #- %s::text[]"
            params.append(path)
        else:
            sql_expr = f"jsonb_set({sql_expr}, %s::text[], %s::jsonb)"
            params.append(path)
            params.append(json.dumps(value))

    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (sql_expr is built from fixed jsonb_set/#- templates; all dynamic values flow through %s params)
    Organization.objects.filter(id=organization.id).update(usage=RawSQL(sql_expr, params))


def _patch_todays_usage(organization: Organization, todays_report: "UsageCounters") -> bool:
    """
    Cron-only: patches `usage[resource].todays_usage` for each `QuotaResource` where the
    org has a non-empty resource dict. Mutates `organization.usage` in-memory and emits a
    single targeted UPDATE via `_patch_organization_usage_jsonb` so billing-owned fields
    (`usage`, `limit`, `period`) are not clobbered by stale snapshots. Returns True if
    any value changed.
    """
    if not organization.usage:
        return False

    ops: list[tuple[list[str], Any]] = []

    for resource in QuotaResource:
        field = resource.value
        existing_resource = organization.usage.get(field)
        if not existing_resource:
            continue

        new_todays_usage = todays_report[field]  # type: ignore[literal-required]
        if existing_resource.get("todays_usage") == new_todays_usage:
            continue

        existing_resource["todays_usage"] = new_todays_usage
        ops.append(([field, "todays_usage"], new_todays_usage))

    if not ops:
        return False

    _patch_organization_usage_jsonb(organization, ops)
    return True


def _identify_refresh_candidates(
    orgs_by_id: dict[str, Organization],
    todays_usage_report: dict[str, "UsageCounters"],
    teams_by_org: dict[str, list[str]],
    previously_quota_limited_team_tokens: dict[str, list[str]],
    previously_quota_limiting_suspended_team_tokens: dict[str, list[str]],
) -> set[str]:
    """
    Returns the set of org ids whose quota decision could change in this run, computed
    from in-memory state only. Stale `usage` only matters for these orgs — for everyone
    else `org_quota_limited_until` short-circuits before consulting any field that could
    have moved since the queries phase, so they don't need a fresh DB read.

    An org is a candidate if any of:
      1. one of its teams is in the Redis quota-limiter set or the Redis
         quota-limiting-suspended set;
      2. its cached `usage[resource]` already carries a `quota_limited_until` or
         `quota_limiting_suspended_until` marker;
      3. it appears newly limitable from cached state — `usage + todays_usage >= limit + buffer`
         for any resource.
    """
    # Either Redis set is reason enough to refresh, so union them once up front and
    # do a single membership check per resource below.
    redis_indicator_lookup: dict[str, set[str]] = {
        resource.value: set(previously_quota_limited_team_tokens.get(resource.value, []))
        | set(previously_quota_limiting_suspended_team_tokens.get(resource.value, []))
        for resource in QuotaResource
    }

    candidates: set[str] = set()
    for org_id, todays_report in todays_usage_report.items():
        org = orgs_by_id.get(org_id)
        if org is None or not org.usage or not org.usage.get("period"):
            continue

        team_token_set: set[str] = set(teams_by_org.get(org_id, []))
        is_candidate = False

        for resource in QuotaResource:
            field = resource.value

            # Redis check first: an org with a stale entry in either Redis set must be
            # refreshed and re-evaluated even when its `usage[resource]` is empty or
            # missing — otherwise we'd never get the chance to clear that stale entry.
            redis_tokens = redis_indicator_lookup.get(field)
            if team_token_set and redis_tokens and not team_token_set.isdisjoint(redis_tokens):
                is_candidate = True
                break

            usage_for_resource = org.usage.get(field)
            if not usage_for_resource:
                continue

            if usage_for_resource.get("quota_limited_until") or usage_for_resource.get(
                "quota_limiting_suspended_until"
            ):
                is_candidate = True
                break

            limit = usage_for_resource.get("limit")
            if limit is None:
                continue
            usage_value = usage_for_resource.get("usage") or 0
            todays_for_field = todays_report[field]  # type: ignore[literal-required]
            if usage_value + todays_for_field >= limit + OVERAGE_BUFFER[resource]:
                is_candidate = True
                break

        if is_candidate:
            candidates.add(org_id)

    return candidates


def _timed_query(name, fn, *args, **kwargs):
    start = time()
    result = fn(*args, **kwargs)
    logger.info(
        "quota_limiting_run", phase="query", status="done", query=name, duration_ms=round((time() - start) * 1000, 1)
    )
    return result


def update_all_orgs_billing_quotas(
    dry_run: bool = False,
    progress_callback: Callable[[str, str, str], None] | None = None,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]], dict[str, float | int]]:
    """
    This is called on a cron job every 30 minutes to update all orgs with their quotas.
    Specifically it's update quota_limited_until and quota_limiting_suspended_until in their usage
    field on the Organization model.

    # Start and end of the current day
    """
    total_start = time()
    period = get_current_day()
    period_start, period_end = period

    tag_queries(product=Product.BILLING, feature=Feature.QUOTA_LIMITING)
    logger.info("quota_limiting_run", phase="queries", status="start")
    queries_start = time()

    api_queries_usage = _timed_query(
        "api_queries_metrics", get_teams_with_api_queries_metrics, period_start, period_end
    )
    _, exception_metrics = _timed_query(
        "exceptions_captured", get_teams_with_exceptions_captured_in_period, period_start, period_end
    )

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = {
        "teams_with_event_count_in_period": convert_team_usage_rows_to_dict(
            _timed_query("billable_events", get_teams_with_billable_event_count_in_period, period_start, period_end)
        ),
        "teams_with_exceptions_captured_in_period": convert_team_usage_rows_to_dict(exception_metrics),
        "teams_with_recording_count_in_period": convert_team_usage_rows_to_dict(
            _timed_query("recordings", get_teams_with_recording_count_in_period, period_start, period_end)
        ),
        "teams_with_rows_synced_in_period": convert_team_usage_rows_to_dict(
            _timed_query("rows_synced", get_teams_with_rows_synced_in_period, period_start, period_end)
        ),
        "teams_with_decide_requests_count": convert_team_usage_rows_to_dict(
            _timed_query(
                "decide_requests",
                get_teams_with_feature_flag_requests_count_in_period,
                period_start,
                period_end,
                FlagRequestType.DECIDE,
            )
        ),
        "teams_with_local_evaluation_requests_count": convert_team_usage_rows_to_dict(
            _timed_query(
                "local_evaluation_requests",
                get_teams_with_feature_flag_requests_count_in_period,
                period_start,
                period_end,
                FlagRequestType.LOCAL_EVALUATION,
            )
        ),
        "teams_with_api_queries_read_bytes": convert_team_usage_rows_to_dict(api_queries_usage["read_bytes"]),
        "teams_with_cdp_trigger_events_metrics": convert_team_usage_rows_to_dict(
            _timed_query("cdp_invocations", get_teams_with_cdp_billable_invocations_in_period, period_start, period_end)
        ),
        "teams_with_rows_exported_in_period": convert_team_usage_rows_to_dict(
            _timed_query("rows_exported", get_teams_with_rows_exported_in_period, period_start, period_end)
        ),
        "teams_with_survey_responses_count_in_period": convert_team_usage_rows_to_dict(
            _timed_query("survey_responses", get_teams_with_survey_responses_count_in_period, period_start, period_end)
        ),
        "teams_with_ai_event_count_in_period": convert_team_usage_rows_to_dict(
            _timed_query("ai_events", get_teams_with_ai_event_count_in_period, period_start, period_end)
        ),
        "teams_with_ai_credits_used_in_period": convert_team_usage_rows_to_dict(
            _timed_query("ai_credits", get_teams_with_ai_credits_used_in_period, period_start, period_end)
        ),
        "teams_with_workflow_emails_sent_in_period": convert_team_usage_rows_to_dict(
            _timed_query("workflow_emails", get_teams_with_workflow_emails_sent_in_period, period_start, period_end)
        ),
        "teams_with_workflow_destinations_in_period": convert_team_usage_rows_to_dict(
            _timed_query(
                "workflow_invocations", get_teams_with_workflow_billable_invocations_in_period, period_start, period_end
            )
        ),
        "teams_with_logs_mb_in_period": {
            team_id: int(bytes_val // 1_000_000)
            for team_id, bytes_val in convert_team_usage_rows_to_dict(
                _timed_query("logs_bytes", get_teams_with_logs_bytes_in_period, period_start, period_end)
            ).items()
        },
    }

    queries_duration_s = round((time() - queries_start), 1)
    logger.info(
        "quota_limiting_run",
        phase="queries",
        status="done",
        duration_ms=round(queries_duration_s * 1000, 1),
        query_count=len(all_data),
    )
    if progress_callback:
        progress_callback("queries_done", f"duration={queries_duration_s}s", f"query_count={len(all_data)}")

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
            "organization__customer_trust_scores",
            "organization__customer_id",
        )
    )

    todays_usage_report: dict[str, UsageCounters] = {}
    orgs_by_id: dict[str, Organization] = {}
    teams_by_org: dict[str, list[str]] = {}

    # we iterate through all teams, and add their usage to the organization they belong to
    for team in teams:
        decide_requests = all_data["teams_with_decide_requests_count"].get(team.id, 0)
        local_evaluation_requests = all_data["teams_with_local_evaluation_requests_count"].get(team.id, 0)

        team_report = UsageCounters(
            events=all_data["teams_with_event_count_in_period"].get(team.id, 0),
            exceptions=all_data["teams_with_exceptions_captured_in_period"].get(team.id, 0),
            recordings=all_data["teams_with_recording_count_in_period"].get(team.id, 0),
            rows_synced=all_data["teams_with_rows_synced_in_period"].get(team.id, 0),
            feature_flag_requests=decide_requests
            + (local_evaluation_requests * 10),  # Same weighting as in _get_team_report
            api_queries_read_bytes=all_data["teams_with_api_queries_read_bytes"].get(team.id, 0),
            survey_responses=all_data["teams_with_survey_responses_count_in_period"].get(team.id, 0),
            llm_events=all_data["teams_with_ai_event_count_in_period"].get(team.id, 0),
            ai_credits=all_data["teams_with_ai_credits_used_in_period"].get(team.id, 0),
            cdp_trigger_events=all_data["teams_with_cdp_trigger_events_metrics"].get(team.id, 0),
            rows_exported=all_data["teams_with_rows_exported_in_period"].get(team.id, 0),
            workflow_emails=all_data["teams_with_workflow_emails_sent_in_period"].get(team.id, 0),
            workflow_destinations_dispatched=all_data["teams_with_workflow_destinations_in_period"].get(team.id, 0),
            logs_mb_ingested=all_data["teams_with_logs_mb_in_period"].get(team.id, 0),
        )

        org_id = str(team.organization.id)

        if org_id not in todays_usage_report:
            orgs_by_id[org_id] = team.organization
            todays_usage_report[org_id] = team_report.copy()
        else:
            org_report = todays_usage_report[org_id]
            for field in team_report:
                org_report[field] += team_report[field]  # type: ignore

        if team.api_token:
            teams_by_org.setdefault(org_id, []).append(team.api_token)

    # Now we have the usage for all orgs for the current day
    # orgs_by_id is a dict of orgs by id (e.g. {"018e9acf-b488-0000-259c-534bcef40359": <Organization: 018e9acf-b488-0000-259c-534bcef40359>})
    # todays_usage_report is a dict of orgs by id with their usage for the current day (e.g. {"018e9acf-b488-0000-259c-534bcef40359": {"events": 100, "exceptions": 100, "recordings": 100, "rows_synced": 100, "feature_flag_requests": 100, "api_queries_read_bytes": 100, "survey_responses": 100}})
    quota_limited_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limiting_suspended_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}

    # Get the current quota limits so we can track to PostHog if it changes
    orgs_with_changes = set()
    previously_quota_limited_team_tokens: dict[str, list[str]] = {x.value: [] for x in QuotaResource}
    previously_quota_limiting_suspended_team_tokens: dict[str, list[str]] = {x.value: [] for x in QuotaResource}

    # All teams that are currently under quota limits or in a suspension grace period
    for resource in QuotaResource:
        previously_quota_limited_team_tokens[resource.value] = list_limited_team_attributes(
            resource, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
        )
        previously_quota_limiting_suspended_team_tokens[resource.value] = list_limited_team_attributes(
            resource, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY
        )
    # We have the teams that are currently under quota limits
    # previously_quota_limited_team_tokens is a dict of resources to team tokens from redis (e.g. {"events": ["phc_123", "phc_456"], "exceptions": ["phc_123", "phc_456"], "recordings": ["phc_123", "phc_456"], "rows_synced": ["phc_123", "phc_456"], "feature_flag_requests": ["phc_123", "phc_456"], "api_queries_read_bytes": ["phc_123", "phc_456"], "survey_responses": ["phc_123", "phc_456"]})
    # previously_quota_limiting_suspended_team_tokens has the same shape, drawn from the suspension Redis set.

    # Identify the orgs whose quota decision could change in this run
    candidates_start = time()
    refresh_candidates = _identify_refresh_candidates(
        orgs_by_id,
        todays_usage_report,
        teams_by_org,
        previously_quota_limited_team_tokens,
        previously_quota_limiting_suspended_team_tokens,
    )
    logger.info(
        "quota_limiting_run",
        phase="refresh_candidates",
        status="done",
        duration_ms=round((time() - candidates_start) * 1000, 1),
        candidate_count=len(refresh_candidates),
        org_count=len(todays_usage_report),
    )

    # Find all orgs that should be rate limited
    total_orgs = len(todays_usage_report)
    logger.info("quota_limiting_run", phase="org_loop", status="start", org_count=total_orgs)
    org_loop_start = time()
    orgs_processed = 0
    orgs_limited_count = 0
    orgs_suspended_count = 0
    refresh_count = 0
    refresh_total_seconds = 0.0

    for org_id, todays_report in todays_usage_report.items():
        # Check and refresh DB connections if needed on every iteration.
        # The database_sync_to_async wrapper only closes connections at start/end,
        # but this loop can run for up to 30min.
        # Skip in tests to avoid breaking test transactions.

        if not settings.TEST:
            close_old_connections()

        try:
            org = orgs_by_id[org_id]

            if org.usage and org.usage.get("period"):
                if org_id in refresh_candidates:
                    # Refresh just before the decision so `org_quota_limited_until`
                    # below reads fresh `usage` / `customer_trust_scores` /`never_drop_data`.
                    refresh_call_start = time()
                    org.refresh_from_db(fields=["usage", "customer_trust_scores", "never_drop_data"])
                    refresh_total_seconds += time() - refresh_call_start
                    refresh_count += 1

                _patch_todays_usage(org, todays_report)

                org_is_limited = False
                org_is_suspended = False
                for resource in QuotaResource:
                    field = resource.value
                    # for each organization, we check if the current usage + today's unreported usage is over the limit
                    result = org_quota_limited_until(org, resource, previously_quota_limited_team_tokens[field])
                    if result:
                        quota_limited_until = result.get("quota_limited_until")
                        limiting_suspended_until = result.get("quota_limiting_suspended_until")
                        if limiting_suspended_until:
                            quota_limiting_suspended_orgs[field][org_id] = limiting_suspended_until
                            org_is_suspended = True
                        elif quota_limited_until:
                            quota_limited_orgs[field][org_id] = quota_limited_until
                            org_is_limited = True
                if org_is_suspended:
                    orgs_suspended_count += 1
                if org_is_limited:
                    orgs_limited_count += 1

            orgs_processed += 1
            if orgs_processed % 1000 == 0:
                logger.info(
                    "quota_limiting_run",
                    phase="org_loop",
                    status="progress",
                    orgs_processed=orgs_processed,
                    org_count=total_orgs,
                    elapsed_ms=round((time() - org_loop_start) * 1000, 1),
                )
                if progress_callback:
                    progress_callback(
                        "org_processing",
                        f"{orgs_processed}/{total_orgs}",
                        f"limited={orgs_limited_count},suspended={orgs_suspended_count}",
                    )
        except Exception as e:
            # TODO: revisit this swallow. Failures here mean the org never lands in
            # `quota_limited_orgs` / `quota_limiting_suspended_orgs`, so the wholesale
            # `replace_limited_team_tokens` calls below silently drop any prior Redis
            # entries for the org's teams — effectively unblocking a previously
            # limited/suspended org on a transient error. Pick an explicit policy
            # (e.g. preserve prior Redis state on error, or intentionally fail-open
            # for customer-favorable behavior) rather than letting the outcome fall
            # out of the catch.
            orgs_processed += 1
            capture_exception(e, {"organization_id": org_id})

    logger.info(
        "quota_limiting_run",
        phase="org_loop",
        status="done",
        duration_ms=round((time() - org_loop_start) * 1000, 1),
        orgs_processed=orgs_processed,
        orgs_limited=orgs_limited_count,
        orgs_suspended=orgs_suspended_count,
        refresh_count=refresh_count,
        refresh_total_ms=round(refresh_total_seconds * 1000, 1),
    )
    if progress_callback:
        progress_callback(
            "org_loop_done",
            f"{orgs_processed}/{total_orgs}",
            f"limited={orgs_limited_count},suspended={orgs_suspended_count}",
        )

    # Now we have the teams that are currently under quota limits
    # quota_limited_orgs is a dict of resources to org ids (e.g. {"events": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "exceptions": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "recordings": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "rows_synced": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "feature_flag_requests": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "api_queries_read_bytes": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "survey_responses": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}})
    # quota_limiting_suspended_orgs is a dict of resources to org ids (e.g. {"events": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "exceptions": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "recordings": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "rows_synced": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "feature_flag_requests": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "api_queries_read_bytes": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}, "survey_responses": {"018e9acf-b488-0000-259c-534bcef40359": 1737867600}})

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
    # quota_limited_teams is a dict of resources to team tokens (e.g. {"events": {"phc_123": 1737867600}, "exceptions": {"phc_123": 1737867600}, "recordings": {"phc_123": 1737867600}, "rows_synced": {"phc_123": 1737867600}, "feature_flag_requests": {"phc_123": 1737867600}, "api_queries_read_bytes": {"phc_123": 1737867600}, "survey_responses": {"phc_123": 1737867600}})
    # quota_limiting_suspended_teams is a dict of resources to team tokens (e.g. {"events": {"phc_123": 1737867600}, "exceptions": {"phc_123": 1737867600}, "recordings": {"phc_123": 1737867600}, "rows_synced": {"phc_123": 1737867600}, "feature_flag_requests": {"phc_123": 1737867600}, "api_queries_read_bytes": {"phc_123": 1737867600}, "survey_responses": {"phc_123": 1737867600}})

    for org_id in orgs_with_changes:
        properties = {
            "quota_limited_events": quota_limited_orgs["events"].get(org_id, None),
            "quota_limited_exceptions": quota_limited_orgs["exceptions"].get(org_id, None),
            "quota_limited_recordings": quota_limited_orgs["recordings"].get(org_id, None),
            "quota_limited_rows_synced": quota_limited_orgs["rows_synced"].get(org_id, None),
            "quota_limited_feature_flags": quota_limited_orgs["feature_flag_requests"].get(org_id, None),
            "quota_limited_api_queries": quota_limited_orgs["api_queries_read_bytes"].get(org_id, None),
            "quota_limited_survey_responses": quota_limited_orgs["survey_responses"].get(org_id, None),
            "quota_limited_llm_events": quota_limited_orgs["llm_events"].get(org_id, None),
            "quota_limited_cdp_trigger_events": quota_limited_orgs["cdp_trigger_events"].get(org_id, None),
            "quota_limited_rows_exported": quota_limited_orgs["rows_exported"].get(org_id, None),
        }

        report_organization_action(
            orgs_by_id[org_id],
            "organization quota limits changed",
            properties=properties,
            group_properties=properties,
        )

    if not dry_run:
        redis_start = time()
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
        redis_duration_s = round((time() - redis_start), 1)
        logger.info("quota_limiting_run", phase="redis", status="done", duration_ms=round(redis_duration_s * 1000, 1))
        if progress_callback:
            progress_callback("redis_done", f"duration={redis_duration_s}s", "")

    total_duration_s = time() - total_start
    logger.info(
        "quota_limiting_run",
        phase="total",
        status="done",
        duration_ms=round(total_duration_s * 1000, 1),
        orgs_processed=orgs_processed,
        orgs_limited=orgs_limited_count,
        orgs_suspended=orgs_suspended_count,
    )

    return (
        quota_limited_orgs,
        quota_limiting_suspended_orgs,
        {
            "duration_s": round(total_duration_s, 1),
            "orgs_total": total_orgs,
            "orgs_processed": orgs_processed,
            "orgs_limited": orgs_limited_count,
            "orgs_suspended": orgs_suspended_count,
        },
    )


# -------------------------------------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------------------------------------


def get_team_attribute_by_quota_resource(organization: Organization) -> list[str]:
    team_tokens: list[str] = [x for x in list(organization.teams.values_list("api_token", flat=True)) if x]

    if not team_tokens:
        capture_exception(
            Exception(f"quota_limiting: No team tokens found for organization"), {"organization_id": organization.id}
        )

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
    Patches specific keys inside organization.usage[resource] using a partial-write
    SQL UPDATE so concurrent billing-owned fields (`usage`, `limit`, `period`) are not
    clobbered by stale snapshots loaded earlier in the cron run.

    `None` deletes the key, anything else sets it. Mirrors the in-memory state on
    `organization` so subsequent reads in the same cron iteration see the new values.
    Matches the prior `save(update_fields=["usage"])` behavior of leaving `updated_at`
    untouched. The raw-SQL UPDATE also bypasses Django model signals, so this
    intentionally does not emit an `Organization` activity-log entry.
    """
    if not fields:
        return
    if not organization.usage:
        capture_exception(
            Exception("quota_limiting: No usage found for organization"), {"organization_id": organization.id}
        )
        return
    if resource.value not in organization.usage:
        capture_exception(
            Exception("quota_limiting: No usage found for resource for organization"),
            {"organization_id": organization.id, "resource": resource.value},
        )
        return

    for key, value in fields.items():
        if value is None:
            organization.usage[resource.value].pop(key, None)
        else:
            organization.usage[resource.value][key] = value

    _patch_organization_usage_jsonb(
        organization,
        [([resource.value, key], value) for key, value in fields.items()],
    )
