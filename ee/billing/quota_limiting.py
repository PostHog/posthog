import copy
import json
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import Enum
from functools import lru_cache, partial
from itertools import batched, groupby
from time import time
from typing import Any, Optional, TypedDict, cast

from django.conf import settings
from django.db import DatabaseError, InterfaceError, close_old_connections, transaction
from django.db.models import TextField
from django.db.models.expressions import RawSQL
from django.db.models.functions import MD5, Cast
from django.utils import timezone

import structlog
import dateutil.parser
import posthoganalytics

from posthog.cache_utils import cache_for
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.event_usage import report_organization_action
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization, OrganizationUsageInfo
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.tasks.usage_report import (
    combine_posthog_code_credits,
    convert_team_usage_rows_to_dict,
    get_self_driving_credits_used_in_period_for_org,
    get_self_driving_credits_used_in_period_for_orgs,
    get_signals_credited_refund_credits_for_org,
    get_teams_with_api_queries_metrics,
    get_teams_with_apm_tracing_usage_in_period,
    iter_billable_teams,
)
from posthog.usage_counters import UsageCounter, UsageCounterService, log_usage_counter_comparisons
from posthog.utils import get_current_day

from ee.billing.quota_usage import QuotaUsageBatch, retry_quota_database_operation

logger = structlog.get_logger(__name__)

QUOTA_ORGANIZATION_BATCH_SIZE = 1_000

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
    SIGNALS_CREDITS = "signals_credits"
    POSTHOG_CODE_CREDITS = "posthog_code_credits"
    WORKFLOW_EMAILS = "workflow_emails"
    WORKFLOW_PUSH = "workflow_push"
    WORKFLOW_DESTINATIONS = "workflow_destinations_dispatched"
    # Covers logs and traces together: they are one product with one free tier and one price.
    LOGS_MB_INGESTED = "logs_mb_ingested"
    REPLAY_VISION_CREDITS = "replay_vision_credits"


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
    QuotaResource.SIGNALS_CREDITS: 0,
    QuotaResource.POSTHOG_CODE_CREDITS: 0,
    QuotaResource.WORKFLOW_EMAILS: 0,
    QuotaResource.WORKFLOW_PUSH: 0,
    QuotaResource.WORKFLOW_DESTINATIONS: 0,
    QuotaResource.LOGS_MB_INGESTED: 0,
    QuotaResource.REPLAY_VISION_CREDITS: 0,
}

# These resources are exempt from any grace periods, whether trust-based or never_drop_data
GRACE_PERIOD_EXEMPT_RESOURCES: set[QuotaResource] = {
    QuotaResource.AI_CREDITS,
    QuotaResource.SIGNALS_CREDITS,
    QuotaResource.REPLAY_VISION_CREDITS,
    QuotaResource.POSTHOG_CODE_CREDITS,
}


# These should be kept in sync with OrganizationUsageInfo.
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
    signals_credits: int
    posthog_code_credits: int
    posthog_code_token_credits: int
    sandbox_compute_credits: int
    sandbox_compute_cpu_millicore_seconds: int
    sandbox_compute_memory_mib_seconds: int
    workflow_emails: int
    workflow_push: int
    workflow_destinations_dispatched: int
    logs_mb_ingested: int
    replay_vision_credits: int


INFORMATIONAL_USAGE_RESOURCES = (
    "posthog_code_token_credits",
    "sandbox_compute_credits",
    "sandbox_compute_cpu_millicore_seconds",
    "sandbox_compute_memory_mib_seconds",
)
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


def reconcile_limited_team_tokens(
    resource: QuotaResource,
    snapshot_tokens: Iterable[str],
    tokens: Mapping[str, int],
    cache_key: QuotaLimitingCaches,
) -> None:
    """
    Writes one quota run's verdict into the cache without discarding entries the run never saw.

    `snapshot_tokens` is what the run read at its start. A snapshot token the run no longer lists
    is removed. A listed token is added or has its score refreshed. A token in neither set was
    added after the snapshot, by `refresh_org_self_driving_quota` when a PR landed or by
    `update_org_billing_quotas` on a billing sync, while this run was in flight. The run judged
    that org from state that predates the write, so its verdict is stale for that org and the
    entry is kept; the next run reads the persisted `quota_limited_until` marker and settles it.
    A wholesale replace would drop that entry and unblock the org until the next run.
    Expired scores are purged so entries that lapsed on their own do not accumulate.
    """
    key = f"{cache_key.value}{resource.value}"
    stale_tokens = [token for token in snapshot_tokens if token not in tokens]
    pipe = get_client().pipeline()
    pipe.zremrangebyscore(key, "-inf", timezone.now().timestamp())
    if stale_tokens:
        pipe.zrem(key, *stale_tokens)
    if tokens:
        pipe.zadd(key, tokens)  # type: ignore # (zadd takes a Mapping[str, int] but the derived Union type is wrong)
    pipe.execute()


def add_limited_team_tokens(resource: QuotaResource, tokens: Mapping[str, int], cache_key: QuotaLimitingCaches) -> None:
    if not tokens:
        return
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


def list_team_attributes_in_zset(resource: QuotaResource, cache_key: QuotaLimitingCaches) -> list[str]:
    """
    Returns every team attribute currently present in the Redis zset for `resource`,
    INCLUDING members whose scores have already expired. Reads Redis directly (uncached) so
    callers see same-tick mutations.
    """
    redis_client = get_client()
    results = redis_client.zrange(f"{cache_key.value}{resource.value}", 0, -1)
    return [x.decode("utf-8") for x in results]


def _get_previous_recordings_zset_tokens() -> set[str]:
    """Shared accessor for the raw recordings quota-limiter zset; see `list_team_attributes_in_zset`."""
    return set(list_team_attributes_in_zset(QuotaResource.RECORDINGS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY))


def is_team_limited(team_api_token: str, resource: QuotaResource, cache_key: QuotaLimitingCaches) -> bool:
    limited_team_attributes = list_limited_team_attributes(resource, cache_key)
    return team_api_token in limited_team_attributes


def get_fresh_team_limited_resources(team_api_token: str) -> dict[QuotaResource, bool]:
    """Uncached limited-state for one team across every resource, one Redis round trip.

    `is_team_limited` reads a fleet-wide list memoized per worker for 30 seconds, which
    is fine for callers that re-check constantly — but consumers that cache the answer
    downstream for minutes (the LLM gateway) would re-cache a just-lifted limit as still
    limited. This reads the zset scores directly instead.
    """
    now_ts = timezone.now().timestamp()
    pipe = get_client().pipeline()
    for resource in QuotaResource:
        pipe.zscore(f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}{resource.value}", team_api_token)
    scores = pipe.execute()
    return {resource: score is not None and score >= now_ts for resource, score in zip(QuotaResource, scores)}


def _resource_usage(summary: dict[str, Any]) -> float | None:
    """None when billing never synced the resource, so clients read unknown usage. Gate on
    `limited`: grace periods and refund offsets apply only there."""
    if not summary:
        return None
    usage = summary.get("usage")
    todays_usage = summary.get("todays_usage")
    if usage is None and todays_usage is None:
        return None
    return (usage or 0) + (todays_usage or 0)


def team_quota_snapshot(team: Team) -> dict[str, Any]:
    """Reads Redis fresh because the legacy gateway re-caches this for minutes, and the 30s memo would
    re-poison a just-invalidated entry. A deactivated org is limited only on the gateway credit buckets,
    which blocks AI spend without dropping events."""
    organization = team.organization
    org_usage = organization.usage or {}
    org_deactivated = organization.is_active is False
    if org_deactivated:
        limited_resources = dict.fromkeys(QuotaResource, False)
        limited_resources[QuotaResource.AI_CREDITS] = True
        limited_resources[QuotaResource.POSTHOG_CODE_CREDITS] = True
    else:
        limited_resources = get_fresh_team_limited_resources(team.api_token)
    limited: dict[str, dict[str, Any]] = {}
    for resource in QuotaResource:
        summary = org_usage.get(resource.value) or {}
        limited[resource.value] = {
            "limited": limited_resources[resource],
            "usage": _resource_usage(summary),
            "limit": summary.get("limit"),
        }
    for field in INFORMATIONAL_USAGE_RESOURCES:
        limited[field] = {"limited": False, "usage": _resource_usage(org_usage.get(field) or {}), "limit": None}
    return {
        "limited": limited,
        "code_usage_billing_active": not org_deactivated
        and organization.is_feature_available(AvailableFeature.POSTHOG_CODE_USAGE),
    }


def dispatch_recordings_remote_config_sync(team_ids: Iterable[int]) -> None:
    """
    Triggers a `RemoteConfig` rebuild for each team after its recordings quota-limit state
    transitions on `QUOTA_LIMITER_CACHE_KEY`. Passes `bypass_recordings_quota_cache=True` so
    the rebuild sees the just-mutated Redis state — see `list_team_attributes_in_zset`.
    """
    from posthog.tasks.remote_config import update_team_remote_config

    for team_id in team_ids:
        try:
            update_team_remote_config.apply_async(
                args=[team_id],
                kwargs={"bypass_recordings_quota_cache": True},
                countdown=35,
            )
        except Exception as e:
            capture_exception(e, {"team_id": team_id})


def is_team_over_credit_budget(team_api_token: str, resource: QuotaResource) -> bool:
    """Quota signal for an LLM-spending path billed into `resource` (an AI credit bucket). On a
    cache miss this issues a synchronous Redis read, so async callers must wrap it in
    sync_to_async."""
    return is_team_limited(team_api_token, resource, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


def is_team_over_ai_credit_budget(team_api_token: str) -> bool:
    return is_team_over_credit_budget(team_api_token, QuotaResource.AI_CREDITS)


def get_teams_limited_until(team_api_tokens: Iterable[str], resources: Iterable[str]) -> dict[str, dict[str, float]]:
    tokens = list(team_api_tokens)
    names = list(resources)
    now_ts = timezone.now().timestamp()
    pipe = get_client().pipeline()
    for token in tokens:
        for name in names:
            pipe.zscore(f"{QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY.value}{name}", token)
    scores = iter(pipe.execute())
    return {
        token: {
            name: float(score)
            for name, score in ((name, next(scores)) for name in names)
            if score is not None and score >= now_ts
        }
        for token in tokens
    }


def get_team_limited_until(team_api_token: str, resources: Iterable[str]) -> dict[str, float]:
    return get_teams_limited_until([team_api_token], resources)[team_api_token]


_LLM_GATEWAY_PROJECTION_BATCH = 500


def _project_llm_gateway_quota_for_org(organization: Organization) -> None:
    """Best-effort because the billing GET reaches this: an enqueue failure must not fail the update."""
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    try:
        from posthog.tasks.team_llm_gateway_quota import project_org_llm_gateway_quota_task  # noqa: PLC0415

        project_org_llm_gateway_quota_task.delay(str(organization.id))
    except Exception as e:
        capture_exception(e)


def _project_llm_gateway_quota_for_tokens(tokens: Iterable[str]) -> None:
    """Enqueued so the all-orgs run never waits on the ai-gateway Redis; the reconcile heals a lost batch."""
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    from posthog.tasks.team_llm_gateway_quota import project_teams_llm_gateway_quota_task  # noqa: PLC0415

    token_list = sorted({token for token in tokens if token})
    for start in range(0, len(token_list), _LLM_GATEWAY_PROJECTION_BATCH):
        try:
            project_teams_llm_gateway_quota_task.delay(token_list[start : start + _LLM_GATEWAY_PROJECTION_BATCH])
        except Exception as e:
            capture_exception(e)


# -------------------------------------------------------------------------------------------------
# MAIN FUNCTIONS
# -------------------------------------------------------------------------------------------------


def _signals_credited_refund_offset(organization: Organization, resource: QuotaResource, over_limit: bool) -> int:
    """Quota offset for credited-path signals PR refunds, in signals credits.

    A credited refund fixes the money (a Stripe balance credit) but not the free-tier slot:
    billing's stored usage — what `usage_summary.signals_credits.usage` syncs from — still
    contains the refunded units, and signals has no grace period, so an over-limit org silently
    stops self-driving. This offset frees the slot posthog-side. Excluded-path refunds need
    nothing here: the same billing query drives `todays_usage`, so they drop out at the source.

    Only consulted when the org is at/over the limit before the offset, so the DB query fires for
    the handful of orgs that would otherwise be limited — not once per org in the all-orgs cron.
    The offset lives ONLY in the boolean limiting decision; the `todays_usage` written back into
    `organization.usage` stays truthful.
    """
    if resource != QuotaResource.SIGNALS_CREDITS or not over_limit:
        return 0
    period = (organization.usage or {}).get("period")
    if not period or len(period) < 2:
        return 0
    period_start = dateutil.parser.isoparse(period[0])
    period_end = dateutil.parser.isoparse(period[1])
    return get_signals_credited_refund_credits_for_org(organization.id, period_start, period_end)


@lru_cache(maxsize=8192)
def _period_timestamp(value: str) -> int:
    return round(dateutil.parser.isoparse(value).timestamp())


def org_quota_limited_until(
    organization: Organization,
    resource: QuotaResource,
    previously_quota_limited_team_tokens: Collection[str],
    team_tokens: Sequence[str] | None = None,
    *,
    batch: QuotaUsageBatch | None = None,
) -> Optional[OrgQuotaLimitingInformation]:
    report_action = batch.report_action if batch is not None else report_organization_action
    if not organization.usage:
        return None

    summary = organization.usage.get(resource.value, {})
    if not summary:
        return None
    usage = summary.get("usage") or 0
    todays_usage = summary.get("todays_usage") or 0
    current_usage = usage + todays_usage
    limit = summary.get("limit")
    quota_limited_until = summary.get("quota_limited_until", None)
    quota_limiting_suspended_until = summary.get("quota_limiting_suspended_until", None)

    if limit is None:
        if quota_limiting_suspended_until is not None or quota_limited_until is not None:
            report_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "limit removed",
                    "current_usage": current_usage,
                    "resource": resource.value,
                    "quota_limited_until": quota_limited_until,
                    "quota_limiting_suspended_until": quota_limiting_suspended_until,
                },
            )
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": None, "quota_limiting_suspended_until": None},
                batch=batch,
            )
        return None

    # Credited-path signals PR refunds free the org's quota slot posthog-side (billing's stored
    # usage still contains the refunded units). Consulted only when the raw comparison is already
    # at/over the limit, so the DB query fires for the handful of orgs that would otherwise be
    # limited. Surfaced on every quota event below for debuggability of refund-affected decisions.
    refund_offset = _signals_credited_refund_offset(
        organization,
        resource,
        limit is not None and current_usage >= limit + OVERAGE_BUFFER[resource],
    )
    if resource == QuotaResource.SIGNALS_CREDITS and current_usage - refund_offset < limit:
        active_persisted_limit = quota_limited_until is not None and quota_limited_until > timezone.now().timestamp()
        if team_tokens is None and previously_quota_limited_team_tokens and not active_persisted_limit:
            team_tokens = get_team_attribute_by_quota_resource(organization)
        was_limited = active_persisted_limit or any(
            token in previously_quota_limited_team_tokens for token in (team_tokens or [])
        )
        if was_limited:
            # Midnight resets today's count before billing necessarily includes yesterday's PRs.
            # Verify the whole period before releasing a block; keep billing-owned counters intact.
            period_start = dateutil.parser.isoparse(organization.usage["period"][0])
            period_end = dateutil.parser.isoparse(organization.usage["period"][1])
            try:
                period_usage = get_self_driving_credits_used_in_period_for_org(
                    organization.id, period_start, period_end
                )
            except Exception as error:
                capture_exception(error, {"organization_id": str(organization.id)})
                return {
                    "quota_limited_until": (
                        quota_limited_until if active_persisted_limit else round(period_end.timestamp())
                    ),
                    "quota_limiting_suspended_until": None,
                }
            current_usage = max(current_usage, period_usage)

            refund_offset = _signals_credited_refund_offset(organization, resource, current_usage >= limit)

    refund_offset_properties = {"signals_refund_offset": refund_offset} if refund_offset else {}

    is_over_limit = current_usage - refund_offset >= limit + OVERAGE_BUFFER[resource]
    billing_period_start = _period_timestamp(organization.usage["period"][0])
    billing_period_end = _period_timestamp(organization.usage["period"][1])

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
            report_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspension removed",
                    "current_usage": current_usage,
                    **refund_offset_properties,
                    "resource": resource.value,
                    "quota_limiting_suspended_until": quota_limiting_suspended_until,
                },
            )
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": None, "quota_limiting_suspended_until": None},
                batch=batch,
            )
        return None

    # 1b. never drop
    if resource not in GRACE_PERIOD_EXEMPT_RESOURCES and organization.never_drop_data:
        report_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "ignored",
                "current_usage": current_usage,
                **refund_offset_properties,
                "resource": resource.value,
                "never_drop_data": organization.never_drop_data,
                "trust_score": trust_score,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": None, "quota_limiting_suspended_until": None}, batch=batch
        )
        return None

    if team_tokens is None:
        team_tokens = get_team_attribute_by_quota_resource(organization)
    team_being_limited = any(x in previously_quota_limited_team_tokens for x in team_tokens)

    # 2a. already being limited
    if team_being_limited or quota_limited_until:
        # They are already being limited, do not update their status.
        report_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "already limited",
                "current_usage": current_usage,
                **refund_offset_properties,
                "resource": resource.value,
                "quota_limited_until": billing_period_end,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            },
        )
        update_organization_usage_fields(
            organization,
            resource,
            {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None},
            batch=batch,
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
        report_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "ignored",
                "current_usage": current_usage,
                **refund_offset_properties,
                "resource": resource.value,
                "feature_flag": QUOTA_LIMIT_DATA_RETENTION_FLAG,
            },
        )
        update_organization_usage_fields(
            organization, resource, {"quota_limited_until": None, "quota_limiting_suspended_until": None}, batch=batch
        )
        return None

    today_end = get_current_day().end

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

        report_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "suspended",
                "current_usage": current_usage,
                **refund_offset_properties,
                "resource": resource.value,
                "trust_score": trust_score,
            },
        )
        update_organization_usage_fields(
            organization,
            resource,
            {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None},
            batch=batch,
        )
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }

    # 2c. low trust
    elif trust_score == 3 and minimum_grace_period == 0:
        # Low trust, immediately limit
        report_action(
            organization,
            "org_quota_limited_until",
            properties={
                "event": "suspended",
                "current_usage": current_usage,
                **refund_offset_properties,
                "resource": resource.value,
                "trust_score": trust_score,
            },
        )
        update_organization_usage_fields(
            organization,
            resource,
            {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None},
            batch=batch,
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
            report_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspended",
                    "current_usage": current_usage,
                    **refund_offset_properties,
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
                batch=batch,
            )
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }

        elif today_end.timestamp() <= quota_limiting_suspended_until:
            # If the suspension is still active (after today's end), we want to return the existing suspension date
            report_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspension not expired",
                    "current_usage": current_usage,
                    **refund_offset_properties,
                    "resource": resource.value,
                    "quota_limiting_suspended_until": quota_limiting_suspended_until,
                },
            )
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": None, "quota_limiting_suspended_until": quota_limiting_suspended_until},
                batch=batch,
            )
            return {
                "quota_limited_until": None,
                "quota_limiting_suspended_until": quota_limiting_suspended_until,
            }
        else:
            # If the suspension is expired, we want to limit the org
            report_action(
                organization,
                "org_quota_limited_until",
                properties={
                    "event": "suspended expired",
                    "current_usage": current_usage,
                    **refund_offset_properties,
                    "resource": resource.value,
                },
            )
            update_organization_usage_fields(
                organization,
                resource,
                {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None},
                batch=batch,
            )
            return {
                "quota_limited_until": billing_period_end,
                "quota_limiting_suspended_until": None,
            }
    else:
        # Should never reach here - return the default behavior just to be safe
        update_organization_usage_fields(
            organization,
            resource,
            {"quota_limited_until": billing_period_end, "quota_limiting_suspended_until": None},
            batch=batch,
        )
        return {
            "quota_limited_until": billing_period_end,
            "quota_limiting_suspended_until": None,
        }


def invalidate_llm_gateway_quota_cache(team_ids: Iterable[int]) -> None:
    """Evict the LLM gateway's per-team quota entries so a raised billing limit
    takes effect immediately instead of after the gateway's five-minute cache TTL.

    The gateway caches in its own Redis (`settings.LLM_GATEWAY_REDIS_URL`, not the
    central instance) and key shapes mirror `llm_gateway/services/quota_resolver.py`.
    Best-effort by design: the gateway TTL already bounds staleness, so a failure
    here must not fail the billing update that just committed.
    """
    id_set = {int(team_id) for team_id in team_ids}
    if not id_set:
        return
    try:
        pipeline = get_client(settings.LLM_GATEWAY_REDIS_URL).pipeline(transaction=False)
        for team_id in id_set:
            pipeline.incr(f"quota:generation:team:{team_id}")
            pipeline.delete(f"quota:code_usage_billing:team:{team_id}")
        pipeline.execute()
    except Exception as e:
        capture_exception(e)


def update_org_billing_quotas(organization: Organization):
    """
    This method is basically update_all_orgs_billing_quotas but for a single org. It's called more often
    when the user loads the billing page and when usage reports are run.
    """
    today_end = get_current_day().end
    if not organization.usage:
        return None

    teams_by_token: dict[str, int] = {
        api_token: team_id for team_id, api_token in organization.teams.values_list("id", "api_token") if api_token
    }
    team_attributes: list[str] = list(teams_by_token.keys())
    if not team_attributes:
        logger.debug("quota_limiting_no_team_tokens", organization_id=str(organization.id))
    team_attributes_set: set[str] = set(team_attributes)
    prev_recordings_zset_tokens: set[str] = _get_previous_recordings_zset_tokens() & team_attributes_set
    recordings_transitioned_team_ids: set[int] = set()

    for resource in QuotaResource:
        previously_quota_limited_team_tokens = list_limited_team_attributes(
            resource,
            QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            # Get the teams tokens (e.g. ["phc_123", "phc_456"])
        )

        # Get the quota limiting information (e.g. {"quota_limited_until": 1737867600, "quota_limiting_suspended_until": 1737867600})
        result = org_quota_limited_until(organization, resource, previously_quota_limited_team_tokens, team_attributes)

        if resource == QuotaResource.RECORDINGS:
            now_limited_for_recordings = bool(result and result.get("quota_limited_until"))
            now_limited_tokens: set[str] = team_attributes_set if now_limited_for_recordings else set()
            for token in prev_recordings_zset_tokens ^ now_limited_tokens:
                team_id = teams_by_token.get(token)
                if team_id is not None:
                    recordings_transitioned_team_ids.add(team_id)

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

    if recordings_transitioned_team_ids:
        dispatch_recordings_remote_config_sync(recordings_transitioned_team_ids)

    invalidate_llm_gateway_quota_cache(teams_by_token.values())
    _project_llm_gateway_quota_for_org(organization)


def refresh_org_self_driving_quota(organization_id: str) -> None:
    """Recompute one org's live `signals_credits` usage for today and re-evaluate its quota limits.

    Dispatched when a self-driving implementation run records its first PR URL (the billable moment), so
    the Redis limited flag can flip within seconds of the PR that crosses the limit. Without this,
    `update_org_billing_quotas` reads the `todays_usage` value patched by the last quota cron tick,
    which by definition predates the PR that just landed — the cron (every 15 minutes) remains the
    backstop for orgs that cross the limit without a PR event.

    Concurrent refreshes for one org (two PRs landing close together) are serialized on the org
    row, and this path only ever raises `todays_usage`: it fires exclusively because a PR landed,
    so a slower refresh that counted usage before a newer PR must not overwrite the fresher value
    and momentarily unpause the org. Decreases (refunds, cron corrections) stay the cron's job.

    Scope caveat: the recount covers today's UTC window keyed on the implementation run's
    `created_at`, so a PR recorded after midnight by a run created before midnight falls in
    yesterday's window and is invisible to this refresh and to the cron. It reaches enforcement
    hours later, when the previous day's usage report lands in `organization.usage`; billing
    itself stays correct because that report queries yesterday's window with the PR present.
    """
    organization = Organization.objects.filter(id=organization_id).first()
    if organization is None or not organization.usage:
        return
    if not organization.usage.get(QuotaResource.SIGNALS_CREDITS.value):
        return

    # The billing count runs outside the lock so the hot organization row is locked only for
    # the compare-and-patch; the monotonic guard below makes a stale count harmless.
    period = get_current_day()
    todays_credits = get_self_driving_credits_used_in_period_for_org(organization.id, period.start, period.end)

    with transaction.atomic():
        # filter().first() like the precheck above: the org can be deleted between the two
        # reads, and a deleted org needs no refresh rather than a DoesNotExist from the task.
        organization = Organization.objects.select_for_update().filter(id=organization_id).first()
        if organization is None:
            return
        resource_usage = (organization.usage or {}).get(QuotaResource.SIGNALS_CREDITS.value)
        if not resource_usage:
            return
        if todays_credits > (resource_usage.get("todays_usage") or 0):
            resource_usage["todays_usage"] = todays_credits
            _patch_organization_usage_jsonb(
                organization, [([QuotaResource.SIGNALS_CREDITS.value, "todays_usage"], todays_credits)]
            )
    # Evaluate from the freshest committed usage, not this task's snapshot: a newer concurrent
    # refresh may have written a higher value while we held or waited on the lock.
    organization.refresh_from_db(fields=["usage"])
    update_org_billing_quotas(organization)


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

    _merge_informational_usage_summary(cast(dict, new_usage), original_usage, todays_usage)

    has_changed = new_usage != organization.usage
    organization.usage = new_usage

    return has_changed


def _merge_informational_usage_summary(
    new_usage: dict[str, Any], original_usage: dict[str, Any], todays_usage: Optional[UsageCounters]
) -> None:
    for field in INFORMATIONAL_USAGE_RESOURCES:
        original_field_usage = original_usage.get(field, {})
        resource_usage = new_usage.get(field)

        if not resource_usage:
            if original_field_usage:
                new_usage[field] = original_field_usage
            else:
                # Billing omitted the component and there's no last-known value: drop the
                # empty placeholder OrganizationUsageInfo construction left behind rather
                # than writing `{}` into every org's usage dict.
                new_usage.pop(field, None)
            continue

        if todays_usage:
            resource_usage["todays_usage"] = todays_usage.get(field, 0)
        elif original_field_usage.get("usage") != resource_usage.get("usage"):
            resource_usage["todays_usage"] = 0
        else:
            resource_usage["todays_usage"] = original_field_usage.get("todays_usage", 0)


def _patch_organization_usage_jsonb(
    organization: Organization, ops: Sequence[tuple[list[str], Any]], *, batch: QuotaUsageBatch | None = None
) -> None:
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

    if batch is not None:
        batch.patch(organization, ops)
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


def _patch_todays_usage(
    organization: Organization, todays_report: "UsageCounters", *, batch: QuotaUsageBatch | None = None
) -> bool:
    """
    Cron-only: patches `usage[resource].todays_usage` for each current usage resource where the
    org has a non-empty resource dict. Mutates `organization.usage` in-memory and emits a
    single targeted UPDATE via `_patch_organization_usage_jsonb` so billing-owned fields
    (`usage`, `limit`, `period`) are not clobbered by stale snapshots. Returns True if
    any value changed.
    """
    if not organization.usage:
        return False

    ops: list[tuple[list[str], Any]] = []

    for resource in QuotaResource:
        _append_todays_usage_patch(organization, todays_report, resource.value, ops)
    for field in INFORMATIONAL_USAGE_RESOURCES:
        _append_todays_usage_patch(organization, todays_report, field, ops)

    if not ops:
        return False

    _patch_organization_usage_jsonb(organization, ops, batch=batch)
    return True


def _append_todays_usage_patch(
    organization: Organization,
    todays_report: UsageCounters,
    field: str,
    ops: list[tuple[list[str], Any]],
) -> None:
    existing_resource = organization.usage.get(field) if organization.usage else None
    if not existing_resource:
        return

    new_todays_usage = cast(dict[str, int], todays_report)[field]
    if existing_resource.get("todays_usage") == new_todays_usage:
        return

    existing_resource["todays_usage"] = new_todays_usage
    ops.append(([field, "todays_usage"], new_todays_usage))


def _identify_refresh_candidates(
    orgs_by_id: dict[str, Organization],
    todays_usage_report: dict[str, "UsageCounters"],
    teams_by_org: dict[str, list[str]],
    previously_quota_limited_team_tokens: dict[str, list[str]],
    previously_quota_limiting_suspended_team_tokens: dict[str, list[str]],
    *,
    redis_indicator_lookup: dict[str, set[str]] | None = None,
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

    A resource with a zero limit and no overage buffer never makes an org a candidate. That
    limit blocks the resource at any usage, so the cached state gives the same decision.
    Signals credits are the exception, because a refund offset can lift a signals block.
    """
    # Either Redis set is reason enough to refresh, so union them once up front and
    # do a single membership check per resource below.
    if redis_indicator_lookup is None:
        redis_indicator_lookup = {
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
            usage_for_resource = org.usage.get(field)
            limit = usage_for_resource.get("limit") if usage_for_resource else None
            if limit == 0 and OVERAGE_BUFFER[resource] == 0 and resource != QuotaResource.SIGNALS_CREDITS:
                continue

            # Redis check first: an org with a stale entry in either Redis set must be
            # refreshed and re-evaluated even when its `usage[resource]` is empty or
            # missing — otherwise we'd never get the chance to clear that stale entry.
            redis_tokens = redis_indicator_lookup.get(field)
            if team_token_set and redis_tokens and not team_token_set.isdisjoint(redis_tokens):
                is_candidate = True
                break

            if not usage_for_resource:
                continue

            if usage_for_resource.get("quota_limited_until") or usage_for_resource.get(
                "quota_limiting_suspended_until"
            ):
                is_candidate = True
                break

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


@frozen
class QuotaLimitingRunResult:
    quota_limited_orgs: dict[str, dict[str, int]]
    quota_limiting_suspended_orgs: dict[str, dict[str, int]]
    stats: dict[str, float | int]


@frozen
class _QuotaUsageReports:
    usage: dict[str, UsageCounters]
    organizations: dict[str, Organization]
    team_tokens: dict[str, list[str]]


def _aggregate_quota_usage(teams: Sequence[Team], all_data: dict[str, dict[int, int]]) -> _QuotaUsageReports:
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
            signals_credits=all_data["teams_with_signals_credits_used_in_period"].get(team.id, 0),
            posthog_code_credits=all_data["teams_with_posthog_code_credits_used_in_period"].get(team.id, 0),
            posthog_code_token_credits=all_data["teams_with_posthog_code_token_credits_used_in_period"].get(team.id, 0),
            sandbox_compute_credits=all_data["teams_with_sandbox_compute_credits_used_in_period"].get(team.id, 0),
            sandbox_compute_cpu_millicore_seconds=all_data[
                "teams_with_sandbox_compute_cpu_millicore_seconds_in_period"
            ].get(team.id, 0),
            sandbox_compute_memory_mib_seconds=all_data["teams_with_sandbox_compute_memory_mib_seconds_in_period"].get(
                team.id, 0
            ),
            cdp_trigger_events=all_data["teams_with_cdp_trigger_events_metrics"].get(team.id, 0),
            rows_exported=all_data["teams_with_rows_exported_in_period"].get(team.id, 0),
            workflow_emails=all_data["teams_with_workflow_emails_sent_in_period"].get(team.id, 0),
            workflow_push=all_data["teams_with_workflow_push_sent_in_period"].get(team.id, 0),
            workflow_destinations_dispatched=all_data["teams_with_workflow_destinations_in_period"].get(team.id, 0),
            logs_mb_ingested=all_data["teams_with_logs_mb_in_period"].get(team.id, 0),
            replay_vision_credits=all_data["teams_with_replay_vision_credits_used_in_period"].get(team.id, 0),
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

    return _QuotaUsageReports(usage=todays_usage_report, organizations=orgs_by_id, team_tokens=teams_by_org)


def update_all_orgs_billing_quotas(
    dry_run: bool = False,
    progress_callback: Callable[[str, str, str], None] | None = None,
) -> QuotaLimitingRunResult:
    """
    This is called on a cron job every 30 minutes to update all orgs with their quotas.
    Specifically it's update quota_limited_until and quota_limiting_suspended_until in their usage
    field on the Organization model.

    # Start and end of the current day
    """
    total_start = time()
    period = get_current_day()
    service = UsageCounterService()
    plan = service.resolve_plan(
        period,
        caller="quota_limiting",
        complete=False,
        counters=(
            UsageCounter.EVENTS,
            UsageCounter.EXCEPTIONS,
            UsageCounter.RECORDINGS,
            UsageCounter.FEATURE_FLAG_REQUESTS,
            UsageCounter.FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS,
            UsageCounter.CDP_INVOCATIONS,
            UsageCounter.SURVEY_RESPONSES,
            UsageCounter.AI_EVENTS,
            UsageCounter.WORKFLOW_EMAILS,
            UsageCounter.WORKFLOW_PUSH,
            UsageCounter.WORKFLOW_INVOCATIONS,
            UsageCounter.ROWS_SYNCED,
            UsageCounter.ROWS_EXPORTED,
            UsageCounter.LOGS_BYTES,
            UsageCounter.AI_CREDITS,
            UsageCounter.SIGNALS_CREDITS,
            UsageCounter.POSTHOG_CODE_CREDITS,
            UsageCounter.SANDBOX_COMPUTE_CREDITS,
            UsageCounter.REPLAY_VISION_CREDITS,
        ),
    )

    tag_queries(product=Product.BILLING, feature=Feature.QUOTA_LIMITING)
    logger.info("quota_limiting_run", phase="queries", status="start")
    queries_start = time()
    counter_report = _timed_query("usage_counters", service.fetch_report, period, plan=plan)
    log_usage_counter_comparisons(counter_report, caller="quota_limiting", date=period.start.date().isoformat())

    api_queries_usage = _timed_query(
        "api_queries_metrics", get_teams_with_api_queries_metrics, period.start, period.end
    )
    token_credits = dict(counter_report.counts[UsageCounter.POSTHOG_CODE_CREDITS])
    compute_credits = dict(counter_report.counts[UsageCounter.SANDBOX_COMPUTE_CREDITS])
    logs_bytes = dict(counter_report.counts[UsageCounter.LOGS_BYTES])
    apm_tracing_bytes = convert_team_usage_rows_to_dict(
        _timed_query("apm_tracing_usage", get_teams_with_apm_tracing_usage_in_period, period.start, period.end)["bytes"]
    )

    # Clickhouse is good at counting things so we count across all teams rather than doing it one by one
    all_data = {
        "teams_with_event_count_in_period": dict(counter_report.counts[UsageCounter.EVENTS]),
        "teams_with_exceptions_captured_in_period": dict(counter_report.counts[UsageCounter.EXCEPTIONS]),
        "teams_with_recording_count_in_period": dict(counter_report.counts[UsageCounter.RECORDINGS]),
        "teams_with_rows_synced_in_period": dict(counter_report.counts[UsageCounter.ROWS_SYNCED]),
        "teams_with_decide_requests_count": dict(counter_report.counts[UsageCounter.FEATURE_FLAG_REQUESTS]),
        "teams_with_local_evaluation_requests_count": dict(
            counter_report.counts[UsageCounter.FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS]
        ),
        "teams_with_api_queries_read_bytes": convert_team_usage_rows_to_dict(api_queries_usage["read_bytes"]),
        "teams_with_cdp_trigger_events_metrics": dict(counter_report.counts[UsageCounter.CDP_INVOCATIONS]),
        "teams_with_rows_exported_in_period": dict(counter_report.counts[UsageCounter.ROWS_EXPORTED]),
        "teams_with_survey_responses_count_in_period": dict(counter_report.counts[UsageCounter.SURVEY_RESPONSES]),
        "teams_with_ai_event_count_in_period": dict(counter_report.counts[UsageCounter.AI_EVENTS]),
        "teams_with_ai_credits_used_in_period": dict(counter_report.counts[UsageCounter.AI_CREDITS]),
        "teams_with_signals_credits_used_in_period": dict(counter_report.counts[UsageCounter.SIGNALS_CREDITS]),
        "teams_with_posthog_code_credits_used_in_period": {
            team_id: combine_posthog_code_credits(token_credits.get(team_id, 0), compute_credits.get(team_id, 0))
            for team_id in token_credits.keys() | compute_credits.keys()
        },
        "teams_with_posthog_code_token_credits_used_in_period": token_credits,
        "teams_with_sandbox_compute_credits_used_in_period": compute_credits,
        "teams_with_sandbox_compute_cpu_millicore_seconds_in_period": dict(
            counter_report.counts["teams_with_sandbox_compute_cpu_millicore_seconds_in_period"]
        ),
        "teams_with_sandbox_compute_memory_mib_seconds_in_period": dict(
            counter_report.counts["teams_with_sandbox_compute_memory_mib_seconds_in_period"]
        ),
        "teams_with_workflow_emails_sent_in_period": dict(counter_report.counts[UsageCounter.WORKFLOW_EMAILS]),
        "teams_with_workflow_push_sent_in_period": dict(counter_report.counts[UsageCounter.WORKFLOW_PUSH]),
        "teams_with_workflow_destinations_in_period": dict(counter_report.counts[UsageCounter.WORKFLOW_INVOCATIONS]),
        "teams_with_replay_vision_credits_used_in_period": dict(
            counter_report.counts[UsageCounter.REPLAY_VISION_CREDITS]
        ),
        # Logs and traces share one bucket, so a team that stays under the limit on each signal alone
        # but exceeds it combined has to be limited on both.
        "teams_with_logs_mb_in_period": {
            team_id: int((logs_bytes.get(team_id, 0) + apm_tracing_bytes.get(team_id, 0)) // 1_000_000)
            for team_id in logs_bytes.keys() | apm_tracing_bytes.keys()
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

    teams_iterator = iter_billable_teams(
        team_fields=("id", "api_token"),
        organization_fields=("id", "usage", "created_at", "never_drop_data", "customer_trust_scores", "customer_id"),
        buffer_teams=True,
    )
    total_orgs = (
        Team.objects.filter(is_demo=False, organization__for_internal_metrics=False)
        .values("organization_id")
        .distinct()
        .count()
    )
    quota_limited_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limiting_suspended_orgs: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limited_teams: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    quota_limiting_suspended_teams: dict[str, dict[str, int]] = {x.value: {} for x in QuotaResource}
    recordings_transitioned_team_ids: set[int] = set()
    recordings_field = QuotaResource.RECORDINGS.value
    failed_org_ids: set[str] = set()
    failed_team_tokens: set[str] = set()

    # Reconciliation must use this run's own snapshot, not the asynchronous 30-second cache.
    previously_quota_limited_team_tokens = {
        resource.value: list_limited_team_attributes(
            resource, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY, use_cache=False
        )
        for resource in QuotaResource
    }
    previously_quota_limiting_suspended_team_tokens = {
        resource.value: list_limited_team_attributes(
            resource, QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY, use_cache=False
        )
        for resource in QuotaResource
    }
    previously_quota_limited_team_token_sets = {
        field: set(tokens) for field, tokens in previously_quota_limited_team_tokens.items()
    }
    redis_indicator_lookup = {
        field: tokens | set(previously_quota_limiting_suspended_team_tokens[field])
        for field, tokens in previously_quota_limited_team_token_sets.items()
    }
    previously_recordings_zset_tokens = _get_previous_recordings_zset_tokens()

    logger.info("quota_limiting_run", phase="org_loop", status="start", org_count=total_orgs)
    org_loop_start = time()
    orgs_processed = orgs_limited_count = orgs_suspended_count = refresh_count = candidate_count = orgs_skipped = 0
    refresh_total_seconds = candidates_total_seconds = 0.0

    def discard_decision(org_id: str, team_tokens: list[str]) -> None:
        failed_org_ids.add(org_id)
        failed_team_tokens.update(team_tokens)
        for resource in QuotaResource:
            quota_limited_orgs[resource.value].pop(org_id, None)
            quota_limiting_suspended_orgs[resource.value].pop(org_id, None)

    # The shared iterator keeps an organization's teams contiguous, including across read pages.
    organization_teams = (list(group) for _, group in groupby(teams_iterator, key=lambda team: team.organization_id))
    for team_groups in batched(organization_teams, QUOTA_ORGANIZATION_BATCH_SIZE, strict=False):
        if not settings.TEST:
            close_old_connections()
        teams = [team for group in team_groups for team in group]
        reports = _aggregate_quota_usage(teams, all_data)
        orgs_by_id = reports.organizations
        teams_by_org = reports.team_tokens
        candidates_start = time()
        refresh_candidates = _identify_refresh_candidates(
            orgs_by_id,
            reports.usage,
            teams_by_org,
            previously_quota_limited_team_tokens,
            previously_quota_limiting_suspended_team_tokens,
            redis_indicator_lookup=redis_indicator_lookup,
        )
        candidate_count += len(refresh_candidates)
        candidates_total_seconds += time() - candidates_start
        refresh_start = time()
        fresh_orgs = {
            str(org.id): org
            for org in retry_quota_database_operation(
                Organization.objects.filter(id__in=refresh_candidates)
                .only("id", "usage", "customer_trust_scores", "never_drop_data")
                .annotate(usage_md5=MD5(Cast("usage", output_field=TextField())))
                .in_bulk
            ).values()
        }
        signals_recount_ids = [
            org_id
            for org_id, fresh in fresh_orgs.items()
            if (fresh.usage or {}).get(QuotaResource.SIGNALS_CREDITS.value)
        ]
        try:
            signals_recounts = retry_quota_database_operation(
                partial(get_self_driving_credits_used_in_period_for_orgs, signals_recount_ids, period.start, period.end)
            )
        except Exception as error:
            if isinstance(error, (DatabaseError, InterfaceError)) and not settings.TEST:
                close_old_connections()
            capture_exception(error, {"organization_ids": signals_recount_ids})
            # These organizations keep their existing limits. The loop still decides the rest of the chunk.
            for org_id in signals_recount_ids:
                discard_decision(org_id, teams_by_org.get(org_id, []))
            signals_recounts = {}
        refresh_count += len(fresh_orgs)
        refresh_total_seconds += time() - refresh_start
        usage_batch = QuotaUsageBatch()
        for org_id, todays_report in reports.usage.items():
            org = orgs_by_id[org_id]
            try:
                if org_id in failed_org_ids:
                    continue
                if org.usage and org.usage.get("period"):
                    if org_id in refresh_candidates:
                        fresh = fresh_orgs.get(org_id)
                        if fresh is None:
                            # Deletion cascades to the teams; drop their old quota entries during reconciliation.
                            continue
                        org.usage = fresh.usage
                        org.customer_trust_scores = fresh.customer_trust_scores
                        org.never_drop_data = fresh.never_drop_data
                        usage_batch.require_unchanged_usage(org, fresh.usage_md5)
                        if (org.usage or {}).get(QuotaResource.SIGNALS_CREDITS.value):
                            # Push refreshes can raise signals usage after the source snapshot. Recount before writing it.
                            todays_report["signals_credits"] = signals_recounts.get(org_id, 0)
                    _patch_todays_usage(org, todays_report, batch=usage_batch)
                    org_is_limited = org_is_suspended = False
                    for resource in QuotaResource:
                        field = resource.value
                        result = org_quota_limited_until(
                            org,
                            resource,
                            previously_quota_limited_team_token_sets[field],
                            teams_by_org.get(org_id, []),
                            batch=usage_batch,
                        )
                        if result:
                            quota_limited_until = result.get("quota_limited_until")
                            limiting_suspended_until = result.get("quota_limiting_suspended_until")
                            if limiting_suspended_until:
                                quota_limiting_suspended_orgs[field][org_id] = limiting_suspended_until
                                org_is_suspended = True
                            elif quota_limited_until:
                                quota_limited_orgs[field][org_id] = quota_limited_until
                                org_is_limited = True
                    orgs_limited_count += org_is_limited
                    orgs_suspended_count += org_is_suspended
            except Exception as error:
                if isinstance(error, (DatabaseError, InterfaceError)) and not settings.TEST:
                    close_old_connections()
                usage_batch.discard(org)
                discard_decision(org_id, teams_by_org.get(org_id, []))
                capture_exception(error, {"organization_id": org_id})
            finally:
                orgs_processed += 1

        # Do not reconcile Redis from decisions whose database writes failed.
        # A skipped organization's usage changed after this chunk read it, and that writer also updates Redis.
        for skipped_org_id in map(str, usage_batch.write()):
            orgs_limited_count -= any(skipped_org_id in orgs for orgs in quota_limited_orgs.values())
            orgs_suspended_count -= any(skipped_org_id in orgs for orgs in quota_limiting_suspended_orgs.values())
            orgs_skipped += 1
            discard_decision(skipped_org_id, teams_by_org.get(skipped_org_id, []))

        orgs_with_changes: set[str] = set()
        # Convert the org ids to team tokens
        for team in teams:
            team_was_in_recordings_zset = team.api_token in previously_recordings_zset_tokens
            if str(team.organization_id) in failed_org_ids:
                # Reconciliation still purges expired entries, and only a rebuild clears an expired recordings limit.
                if team_was_in_recordings_zset:
                    recordings_transitioned_team_ids.add(team.id)
                continue
            for field in quota_limited_orgs:
                org_id = str(team.organization.id)
                if org_id in quota_limited_orgs[field]:
                    quota_limited_teams[field][team.api_token] = quota_limited_orgs[field][org_id]

                    # If the team was not previously quota limited, we add it to the list of orgs that were added
                    if team.api_token not in previously_quota_limited_team_token_sets[field]:
                        orgs_with_changes.add(org_id)
                        if field == recordings_field and not team_was_in_recordings_zset:
                            recordings_transitioned_team_ids.add(team.id)
                elif org_id in quota_limiting_suspended_orgs[field]:
                    quota_limiting_suspended_teams[field][team.api_token] = quota_limiting_suspended_orgs[field][org_id]
                    if field == recordings_field and team_was_in_recordings_zset:
                        recordings_transitioned_team_ids.add(team.id)
                else:
                    # If the team was previously quota limited, we add it to the list of orgs that were removed
                    if team.api_token in previously_quota_limited_team_token_sets[field]:
                        orgs_with_changes.add(org_id)
                    # Decoupled from `orgs_with_changes` on purpose: the recordings RemoteConfig
                    # rebuild must also fire for tokens whose scores already expired naturally —
                    # those won't appear in the cached `previously_quota_limited_team_tokens` view,
                    # but they are still physically in the zset and the persisted config still
                    # carries `quotaLimited: ["recordings"]` until we rebuild.
                    if field == recordings_field and team_was_in_recordings_zset:
                        recordings_transitioned_team_ids.add(team.id)

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

            usage_batch.report_action(
                orgs_by_id[org_id],
                "organization quota limits changed",
                properties=properties,
                group_properties=properties,
            )

        usage_batch.publish()
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

    if not settings.TEST:
        close_old_connections()
    logger.info(
        "quota_limiting_run",
        phase="refresh_candidates",
        status="done",
        duration_ms=round(candidates_total_seconds * 1000, 1),
        candidate_count=candidate_count,
        org_count=orgs_processed,
    )
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
        orgs_failed=len(failed_org_ids),
        orgs_skipped=orgs_skipped,
    )
    if progress_callback:
        progress_callback(
            "org_loop_done",
            f"{orgs_processed}/{total_orgs}",
            f"limited={orgs_limited_count},suspended={orgs_suspended_count}",
        )

    # A failed decision must not remove that organization's existing Redis state.
    if failed_team_tokens:
        for field in previously_quota_limited_team_tokens:
            previously_quota_limited_team_tokens[field] = [
                token for token in previously_quota_limited_team_tokens[field] if token not in failed_team_tokens
            ]
            previously_quota_limiting_suspended_team_tokens[field] = [
                token
                for token in previously_quota_limiting_suspended_team_tokens[field]
                if token not in failed_team_tokens
            ]

    if not dry_run:
        redis_start = time()
        for field in quota_limited_teams:
            reconcile_limited_team_tokens(
                QuotaResource(field),
                previously_quota_limited_team_tokens[field],
                quota_limited_teams[field],
                QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
            )
        for field in quota_limiting_suspended_teams:
            reconcile_limited_team_tokens(
                QuotaResource(field),
                previously_quota_limiting_suspended_team_tokens[field],
                quota_limiting_suspended_teams[field],
                QuotaLimitingCaches.QUOTA_LIMITING_SUSPENDED_KEY,
            )
        # Re-project every team limited before or after this run: the blob TTL is the limit's end,
        # which can move for a team that stays limited.
        changed_ai_tokens: set[str] = set()
        for resource in (QuotaResource.AI_CREDITS, QuotaResource.POSTHOG_CODE_CREDITS):
            changed_ai_tokens |= set(previously_quota_limited_team_tokens[resource.value]) | set(
                quota_limited_teams[resource.value]
            )
        if changed_ai_tokens:
            _project_llm_gateway_quota_for_tokens(changed_ai_tokens)
        redis_duration_s = round((time() - redis_start), 1)
        logger.info("quota_limiting_run", phase="redis", status="done", duration_ms=round(redis_duration_s * 1000, 1))
        if progress_callback:
            progress_callback("redis_done", f"duration={redis_duration_s}s", "")

        if recordings_transitioned_team_ids:
            dispatch_recordings_remote_config_sync(recordings_transitioned_team_ids)

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

    return QuotaLimitingRunResult(
        quota_limited_orgs=quota_limited_orgs,
        quota_limiting_suspended_orgs=quota_limiting_suspended_orgs,
        stats={
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
    organization: Organization, resource: QuotaResource, fields: dict[str, Any], *, batch: QuotaUsageBatch | None = None
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
        batch=batch,
    )
