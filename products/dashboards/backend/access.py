import json
from datetime import datetime
from enum import StrEnum

from django.db.models.expressions import RawSQL
from django.utils.timezone import now

from prometheus_client import Counter
from rest_framework.request import Request

from posthog.event_usage import EventSource, get_event_source

from products.dashboards.backend.models.dashboard import Dashboard


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


def record_dashboard_access(
    dashboard: Dashboard,
    access_method: DashboardAccessMethod,
    *,
    accessed_at: datetime | None = None,
) -> None:
    access_timestamp = accessed_at or now()
    access_key = access_method.value
    updated_access = RawSQL(
        """
        jsonb_set(
            COALESCE(most_recent_access, '{}'::jsonb),
            ARRAY[%s]::text[],
            COALESCE(most_recent_access -> %s, '{}'::jsonb) || jsonb_build_object(
                'timestamp', %s::jsonb,
                'count', COALESCE((most_recent_access -> %s ->> 'count')::bigint, 0) + 1
            ),
            true
        )
        """,
        (
            access_key,
            access_key,
            json.dumps(access_timestamp.isoformat()),
            access_key,
        ),
    )

    Dashboard.objects.for_team(dashboard.team_id).filter(pk=dashboard.pk).update(
        last_accessed_at=access_timestamp,
        most_recent_access=updated_access,
    )
    dashboard.last_accessed_at = access_timestamp
    DASHBOARD_ACCESS_COUNTER.labels(access_method=access_key).inc()


def record_dashboard_cache_outcome(
    dashboard: Dashboard,
    access_method: DashboardAccessMethod,
    *,
    is_cached: bool,
    observed_at: datetime | None = None,
) -> None:
    outcome = "hit" if is_cached else "miss"
    DASHBOARD_CACHE_OUTCOME_COUNTER.labels(access_method=access_method.value, result=outcome).inc()
    if is_cached:
        return

    observation_timestamp = observed_at or now()
    access_key = access_method.value
    updated_access = RawSQL(
        """
        jsonb_set(
            COALESCE(most_recent_access, '{}'::jsonb),
            ARRAY[%s]::text[],
            COALESCE(most_recent_access -> %s, '{}'::jsonb) || jsonb_build_object(
                'last_cache_miss_at', %s::jsonb,
                'cache_miss_count', COALESCE((most_recent_access -> %s ->> 'cache_miss_count')::bigint, 0) + 1
            ),
            true
        )
        """,
        (
            access_key,
            access_key,
            json.dumps(observation_timestamp.isoformat()),
            access_key,
        ),
    )
    Dashboard.objects.for_team(dashboard.team_id).filter(pk=dashboard.pk).update(most_recent_access=updated_access)
