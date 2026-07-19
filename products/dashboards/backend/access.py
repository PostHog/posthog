from datetime import datetime
from enum import StrEnum
from typing import cast

from django.core.cache import cache
from django.db.models import DateTimeField
from django.db.models.expressions import RawSQL
from django.utils.timezone import now

import structlog
from prometheus_client import Counter
from rest_framework.request import Request

from posthog.event_usage import EventSource, get_event_source
from posthog.hogql_queries.query_runner import ExecutionMode

from products.dashboards.backend.models.dashboard import Dashboard

logger = structlog.get_logger(__name__)


class DashboardAccessMethod(StrEnum):
    HUMAN = "human"
    SHARED = "shared"
    EMBEDDED = "embedded"
    API = "api"


DASHBOARD_ACCESS_COUNTER = Counter(
    "posthog_dashboard_access_total",
    "Dashboard accesses recorded for cache warming prioritization",
    ["access_method"],
)
DASHBOARD_CACHE_OUTCOME_COUNTER = Counter(
    "posthog_dashboard_cache_outcome_total",
    "Dashboard insight cache outcomes recorded from views",
    ["access_method", "result"],
)
DASHBOARD_CACHE_MISS_CLAIM_TTL_SECONDS = 60


def dashboard_access_method(
    request: Request, *, is_shared: bool = False, is_embedded: bool = False
) -> DashboardAccessMethod:
    if is_embedded:
        return DashboardAccessMethod.EMBEDDED
    if is_shared:
        return DashboardAccessMethod.SHARED
    if get_event_source(request) == EventSource.WEB:
        return DashboardAccessMethod.HUMAN
    return DashboardAccessMethod.API


def claim_dashboard_cache_miss_persistence(
    request: Request,
    dashboard: Dashboard,
    access_method: DashboardAccessMethod,
    execution_mode: ExecutionMode,
    *,
    is_cached: bool,
) -> bool:
    if is_cached or execution_mode in (
        ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        ExecutionMode.CALCULATE_ASYNC_ALWAYS,
    ):
        return False

    claimed_dashboard_ids = cast(
        set[int],
        request.__dict__.setdefault("_cache_warming_miss_dashboard_ids", set()),
    )
    if dashboard.id in claimed_dashboard_ids:
        return False
    claimed_dashboard_ids.add(dashboard.id)

    cache_key = f"dashboard_cache_miss:{dashboard.team_id}:{dashboard.id}:{access_method.value}"
    try:
        return cache.add(cache_key, True, timeout=DASHBOARD_CACHE_MISS_CLAIM_TTL_SECONDS)
    except Exception:
        logger.exception(
            "dashboard_cache_miss_claim_failed",
            team_id=dashboard.team_id,
            dashboard_id=dashboard.id,
            access_method=access_method.value,
        )
        return False


def record_dashboard_access(
    dashboard: Dashboard,
    access_method: DashboardAccessMethod,
    *,
    accessed_at: datetime | None = None,
) -> None:
    access_timestamp = accessed_at or now()
    access_key = access_method.value
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via params tuple)
    updated_access = RawSQL(
        """
        jsonb_set(
            COALESCE(most_recent_access, '{}'::jsonb),
            ARRAY[%s]::text[],
            COALESCE(most_recent_access -> %s, '{}'::jsonb) || jsonb_build_object(
                'timestamp', to_jsonb(GREATEST(
                    COALESCE((most_recent_access -> %s ->> 'timestamp')::timestamptz, '-infinity'::timestamptz),
                    %s::timestamptz
                )),
                'count', COALESCE((most_recent_access -> %s ->> 'count')::bigint, 0) + 1
            ),
            true
        )
        """,
        (
            access_key,
            access_key,
            access_key,
            access_timestamp,
            access_key,
        ),
    )
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via params tuple)
    updated_last_accessed_at = RawSQL(
        "GREATEST(COALESCE(last_accessed_at, %s), %s)",
        (access_timestamp, access_timestamp),
        output_field=DateTimeField(),
    )

    Dashboard.objects.filter(team_id=dashboard.team_id, pk=dashboard.pk).update(
        last_accessed_at=updated_last_accessed_at,
        most_recent_access=updated_access,
    )
    if dashboard.last_accessed_at is None or access_timestamp > dashboard.last_accessed_at:
        dashboard.last_accessed_at = access_timestamp
    DASHBOARD_ACCESS_COUNTER.labels(access_method=access_key).inc()


def record_dashboard_cache_outcome(
    dashboard: Dashboard,
    access_method: DashboardAccessMethod,
    *,
    is_cached: bool,
    persist_miss: bool = True,
    observed_at: datetime | None = None,
) -> None:
    outcome = "hit" if is_cached else "miss"
    DASHBOARD_CACHE_OUTCOME_COUNTER.labels(access_method=access_method.value, result=outcome).inc()
    if is_cached or not persist_miss:
        return

    observation_timestamp = observed_at or now()
    access_key = access_method.value
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via params tuple)
    updated_access = RawSQL(
        """
        jsonb_set(
            COALESCE(most_recent_access, '{}'::jsonb),
            ARRAY[%s]::text[],
            COALESCE(most_recent_access -> %s, '{}'::jsonb) || jsonb_build_object(
                'last_cache_miss_at', to_jsonb(GREATEST(
                    COALESCE(
                        (most_recent_access -> %s ->> 'last_cache_miss_at')::timestamptz,
                        '-infinity'::timestamptz
                    ),
                    %s::timestamptz
                ))
            ),
            true
        )
        """,
        (
            access_key,
            access_key,
            access_key,
            observation_timestamp,
        ),
    )
    Dashboard.objects.filter(team_id=dashboard.team_id, pk=dashboard.pk).update(most_recent_access=updated_access)
