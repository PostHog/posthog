from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from rest_framework.exceptions import APIException

from posthog.schema import DashboardFilter, MetricsDisplayType, MetricsQuery, MetricsQueryLanguage

from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.dashboards.backend.widget_specs.configs import METRICS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.errors import WidgetQueryError
from products.metrics.backend.facade.api import metrics_histogram_query_for
from products.metrics.backend.facade.contracts import MetricsHeatmapIneligibleError
from products.metrics.backend.facade.queries import MetricsHistogramQueryRunner, MetricsQueryRunner

# Debug and runtime fields the tile never reads.
_DROPPED_RESPONSE_KEYS = ("hogql", "modifiers", "query_status", "timings")

# A dashboard can hold more metric tiles than the per-org dashboard query limiter admits at once, and the
# limiter does not wait. A tile that misses a slot tries again after these delays before it gives up.
_CAPACITY_RETRY_DELAYS_SECONDS = (0.25, 0.5, 1.0, 2.0)


def _needs_configuration(query: MetricsQuery) -> bool:
    if query.language == MetricsQueryLanguage.PROMQL:
        return not (query.promql or "").strip()
    if query.language == MetricsQueryLanguage.SQL:
        return not (query.sql or "").strip()
    return not query.clauses or not all(clause.metricName.strip() for clause in query.clauses)


def _build_runner(team: Team, query: MetricsQuery) -> MetricsQueryRunner | MetricsHistogramQueryRunner:
    # The heatmap reads a different response shape, so it gets its own query node and cache entry rather
    # than a display branch inside the time-series runner (whose cache key ignores `display`).
    if query.display and query.display.type == MetricsDisplayType.HEATMAP:
        try:
            return MetricsHistogramQueryRunner(query=metrics_histogram_query_for(query), team=team)
        except MetricsHeatmapIneligibleError as error:
            raise WidgetQueryError(str(error)) from error
    return MetricsQueryRunner(query=query, team=team)


def _run_with_capacity_retries(run: Callable[[], Any]) -> Any:
    for delay in _CAPACITY_RETRY_DELAYS_SECONDS:
        try:
            return run()
        except ConcurrencyLimitExceeded:
            time.sleep(delay)
    try:
        return run()
    except ConcurrencyLimitExceeded as error:
        raise WidgetQueryError(
            "Too many queries are running on this dashboard. Refresh the tile in a moment.", operational=True
        ) from error


def run_metrics_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
    dashboard_id: int | None = None,
    dashboard_filters: DashboardFilter | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    typed_config = validate_widget_config(METRICS_WIDGET_TYPE, config)
    query = MetricsQuery.model_validate(typed_config["query"])
    if _needs_configuration(query):
        return {"needsConfiguration": True}
    # The metrics runner enforces RBAC and the alpha flags per viewer. A run without a viewer would skip
    # those checks, so a widget never runs one.
    if user is None:
        raise WidgetQueryError("Sign in to PostHog to see this metric.")

    runner = _build_runner(team, query)
    if dashboard_filters is not None:
        runner.apply_dashboard_filters(dashboard_filters)

    # A refresh the viewer asks for skips the cache, as the refresh of an insight tile does.
    execution_mode = (
        ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        if force_refresh
        else ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
    )
    try:
        with tags_context(product=Product.METRICS, feature=Feature.QUERY, team_id=team.pk):
            response = _run_with_capacity_retries(
                lambda: runner.run(execution_mode=execution_mode, user=user, dashboard_id=dashboard_id)
            )
    except UserAccessControlError as error:
        raise WidgetQueryError("You do not have access to metrics.") from error
    except (ExposedHogQLError, ExposedCHQueryError) as error:
        raise WidgetQueryError(str(error)) from error
    except APIException as error:
        # The runner's typed refusals (a timeout, a memory or size limit) explain themselves to the viewer.
        raise WidgetQueryError(str(error.detail), operational=True) from error

    # A gap point's `value` is required and null, so None stays in the payload.
    result = response.model_dump(mode="json")
    for key in _DROPPED_RESPONSE_KEYS:
        result.pop(key, None)
    return result
