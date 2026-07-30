from typing import TYPE_CHECKING, Any, Optional, Union

import orjson
import structlog
from pydantic import BaseModel

from posthog.schema import CacheMissResponse, DashboardFilter

from posthog.hogql.constants import LimitContext

from posthog.api.services.query import ExecutionMode, RawCachedQueryResponse, process_query_dict
from posthog.clickhouse.query_tagging import get_team_query_tags, tag_queries
from posthog.event_usage import AnalyticsProps
from posthog.hogql_queries.apply_dashboard_filters import resolve_effective_dashboard_filters
from posthog.hogql_queries.query_runner import get_query_runner_or_none, response_results_contain_models
from posthog.models import Team, User
from posthog.schema_migrations.upgrade_manager import upgrade_query

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight, generate_insight_filters_hash

if TYPE_CHECKING:
    from posthog.caching.fetch_from_cache import InsightResult
    from posthog.rbac.user_access_control import UserAccessControl


logger = structlog.get_logger(__name__)


def _model_field_as_dict(model: BaseModel, field: str) -> Optional[dict]:
    value = getattr(model, field, None)
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True)
    return value


def _dump_nested_models(value: Any) -> Any:
    """Container-preserving conversion of pydantic models to dicts (lists, dicts, scalars pass through)."""
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True)
    if isinstance(value, list):
        return [_dump_nested_models(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump_nested_models(item) for key, item in value.items()}
    return value


def _model_list_field_as_dicts(model: BaseModel, field: str) -> Optional[list]:
    value = getattr(model, field, None)
    if value is None:
        return None
    return [item.model_dump(by_alias=True) if isinstance(item, BaseModel) else item for item in value]


def calculate_cache_key(target: Union[DashboardTile, Insight]) -> Optional[str]:
    insight: Optional[Insight] = target if isinstance(target, Insight) else target.insight
    dashboard: Optional[Dashboard] = target.dashboard if isinstance(target, DashboardTile) else None

    if insight is not None:
        with upgrade_query(insight):
            if insight.query:
                query_runner = get_query_runner_or_none(insight.query, insight.team)
                if query_runner is None:
                    return None  # Uncacheable query-based insight
                if dashboard is not None and dashboard.filters:
                    query_runner.apply_dashboard_filters(DashboardFilter(**dashboard.filters))
                return query_runner.get_cache_key()

            if insight.filters:
                return generate_insight_filters_hash(insight, dashboard)

    return None


def calculate_for_query_based_insight(
    insight: Insight,
    *,
    team: Team,
    dashboard: Optional[Dashboard] = None,
    execution_mode: ExecutionMode,
    user: Optional[User],
    user_access_control: Optional["UserAccessControl"] = None,
    filters_override: Optional[dict] = None,
    variables_override: Optional[dict] = None,
    tile_filters_override: Optional[dict] = None,
    query_override: Optional[dict] = None,
    cache_age_seconds: Optional[int] = None,
    analytics_props: Optional[AnalyticsProps] = None,
    allow_raw_results: bool = False,
) -> "InsightResult":
    from posthog.caching.fetch_from_cache import InsightResult, NothingInCacheResult

    tag_queries(**get_team_query_tags(team), insight_id=insight.pk)
    if dashboard:
        tag_queries(dashboard_id=dashboard.pk)

    dashboard_filters_json = (
        filters_override if filters_override is not None else dashboard.filters if dashboard is not None else None
    )

    variables_override_json = (
        variables_override if variables_override is not None else dashboard.variables if dashboard is not None else None
    )

    query_json: dict | None = query_override if query_override is not None else insight.query
    if query_json is None:
        raise ValueError("Insight has no query and no query_override was provided")

    query_json, dashboard_filters_json = resolve_effective_dashboard_filters(
        query_json, dashboard_filters_json, tile_filters_override
    )

    process_response = process_query_dict(
        team,
        query_json,
        dashboard_filters_json=dashboard_filters_json,
        variables_override_json=variables_override_json,
        execution_mode=execution_mode,
        user=user,
        user_access_control=user_access_control,
        insight_id=insight.pk,
        dashboard_id=dashboard.pk if dashboard else None,
        # QUERY_ASYNC provides extended max execution time for insight queries
        limit_context=LimitContext.QUERY_ASYNC,
        cache_age_seconds=cache_age_seconds,
        analytics_props=analytics_props,
        allow_raw_results=allow_raw_results,
    )

    raw_results: Optional[bytes] = None
    if isinstance(process_response, RawCachedQueryResponse):
        raw_results = process_response.raw_results
        process_response = process_response.response

    if isinstance(process_response, CacheMissResponse):
        return NothingInCacheResult(
            cache_key=process_response.cache_key, query_status=_model_field_as_dict(process_response, "query_status")
        )

    if isinstance(process_response, BaseModel):
        # Don't model_dump() the whole response: `results` alone can be tens of MB of plain
        # dicts, and dumping deep-copies all of it only for a handful of fields to be re-read.
        # Pull fields off the model instead, converting just the small nested models to dicts
        # (which is what model_dump produced before). The response class may not carry every
        # field (legacy insights shape), hence the getattr defaults.
        if raw_results is not None:
            # orjson.Fragment embeds the cached results bytes into the JSON response as-is,
            # skipping the parse/re-serialize round trip. Callers passing allow_raw_results
            # guarantee the result feeds an orjson renderer.
            result: Any = orjson.Fragment(raw_results)
        else:
            result = getattr(process_response, "results", None)
            if result is not None and response_results_contain_models(type(process_response)):
                # Model-typed results (e.g. RetentionResult, PathsLink) must be dumped to dicts
                # like model_dump did — DRF's JSON encoder would otherwise mangle them into
                # (field, value) tuple arrays. Results whose annotation is plain data (the huge
                # trends/funnels payloads, or scalar/dict-shaped results) pass through untouched.
                result = _dump_nested_models(result)
        return InsightResult(
            result=result,
            has_more=getattr(process_response, "hasMore", None),
            columns=getattr(process_response, "columns", None),
            last_refresh=getattr(process_response, "last_refresh", None),
            cache_key=getattr(process_response, "cache_key", None),
            is_cached=getattr(process_response, "is_cached", False),
            timezone=getattr(process_response, "timezone", None),
            next_allowed_client_refresh=getattr(process_response, "next_allowed_client_refresh", None),
            cache_target_age=getattr(process_response, "cache_target_age", None),
            timings=_model_list_field_as_dicts(process_response, "timings"),
            query_status=_model_field_as_dict(process_response, "query_status"),
            hogql=getattr(process_response, "hogql", None),
            types=getattr(process_response, "types", None),
            resolved_date_range=_model_field_as_dict(process_response, "resolved_date_range"),
        )

    response = process_response
    assert isinstance(response, dict)

    return InsightResult(
        # Translating `QueryResponse` to legacy insights shape
        # The response may not be conformant with that, hence these are all `.get()`s
        result=response.get("results"),
        has_more=response.get("hasMore"),
        columns=response.get("columns"),
        last_refresh=response.get("last_refresh"),
        cache_key=response.get("cache_key"),
        is_cached=response.get("is_cached", False),
        timezone=response.get("timezone"),
        next_allowed_client_refresh=response.get("next_allowed_client_refresh"),
        cache_target_age=response.get("cache_target_age"),
        timings=response.get("timings"),
        query_status=response.get("query_status"),
        hogql=response.get("hogql"),
        types=response.get("types"),
        resolved_date_range=response.get("resolved_date_range"),
    )
