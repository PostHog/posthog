from enum import StrEnum

from django.utils.timezone import now

from prometheus_client import Counter
from rest_framework.request import Request

from posthog.event_usage import EventSource, get_event_source
from posthog.otel_metrics import OtelInstrumentFactory

from products.dashboards.backend.models.dashboard import Dashboard

_otel = OtelInstrumentFactory("dashboards")


class DashboardAccessMethod(StrEnum):
    HUMAN = "human"
    SHARED = "shared"
    EMBEDDED = "embedded"
    API = "api"


DASHBOARD_ACCESS_COUNTER = Counter(
    "posthog_dashboard_access_total",
    "Dashboard accesses by source",
    ["access_method"],
)
DASHBOARD_CACHE_OUTCOME_COUNTER = Counter(
    "posthog_dashboard_cache_outcome_total",
    "Dashboard insight cache outcomes by access source",
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


def record_dashboard_access(access_method: DashboardAccessMethod) -> None:
    DASHBOARD_ACCESS_COUNTER.labels(access_method=access_method.value).inc()
    _otel.record_counter_twin(DASHBOARD_ACCESS_COUNTER, 1, {"access_method": access_method.value})


def record_dashboard_view(dashboard: Dashboard, access_method: DashboardAccessMethod) -> None:
    dashboard.last_accessed_at = now()
    dashboard.save(update_fields=["last_accessed_at"])
    record_dashboard_access(access_method)


def record_dashboard_cache_outcome(access_method: DashboardAccessMethod, *, is_cached: bool) -> None:
    result = "hit" if is_cached else "miss"
    DASHBOARD_CACHE_OUTCOME_COUNTER.labels(access_method=access_method.value, result=result).inc()
    _otel.record_counter_twin(
        DASHBOARD_CACHE_OUTCOME_COUNTER, 1, {"access_method": access_method.value, "result": result}
    )
