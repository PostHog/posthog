from __future__ import annotations

from typing import Any

from posthog.schema import DashboardFilter, MetricsDisplayType, MetricsQuery, MetricsQueryLanguage

from posthog.hogql.errors import ExposedHogQLError

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


def run_metrics_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
    dashboard_id: int | None = None,
    dashboard_filters: DashboardFilter | None = None,
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

    try:
        with tags_context(product=Product.METRICS, feature=Feature.QUERY, team_id=team.pk):
            response = runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=user,
                dashboard_id=dashboard_id,
            )
    except UserAccessControlError as error:
        raise WidgetQueryError("You do not have access to metrics.") from error
    except (ExposedHogQLError, ExposedCHQueryError) as error:
        raise WidgetQueryError(str(error)) from error

    result = response.model_dump(mode="json", exclude_none=True)
    for key in _DROPPED_RESPONSE_KEYS:
        result.pop(key, None)
    return result
