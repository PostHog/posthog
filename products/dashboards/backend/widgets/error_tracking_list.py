from __future__ import annotations

import logging
from typing import Any, cast

from posthog.schema import DateRange, ErrorTrackingIssueAssignee, ErrorTrackingQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import ERROR_TRACKING_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.widget_filters import build_property_group_filter_from_widget_filters
from products.error_tracking.backend.api.query import normalize_volume_resolution
from products.error_tracking.backend.api.query_utils import (
    ERROR_TRACKING_LISTING_VOLUME_RESOLUTION,
    LIST_ISSUE_FIELDS,
    build_date_range,
    get_page_info,
    pick_fields,
)
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

logger = logging.getLogger(__name__)

ValidatedErrorTrackingListWidgetConfig = dict[str, Any]


def _coerce_assignee(assignee: object) -> ErrorTrackingIssueAssignee | None:
    if assignee is None:
        return None
    if isinstance(assignee, ErrorTrackingIssueAssignee):
        return assignee
    if isinstance(assignee, dict):
        return ErrorTrackingIssueAssignee.model_validate(assignee)
    return None


def _build_error_tracking_list_query(
    *,
    team: Team,
    config: ValidatedErrorTrackingListWidgetConfig,
    limit: int,
    offset: int,
    with_aggregations: bool,
) -> ErrorTrackingQuery:
    date_range_raw = config.get("dateRange")
    filter_group = build_property_group_filter_from_widget_filters(config.get("widgetFilters"))
    return ErrorTrackingQuery(
        kind="ErrorTrackingQuery",
        dateRange=DateRange(**build_date_range(date_range_raw)),
        status=config["status"],
        assignee=_coerce_assignee(config.get("assignee")),
        filterGroup=filter_group,
        filterTestAccounts=resolve_filter_test_accounts(config, team),
        orderBy=config["orderBy"],
        orderDirection=config["orderDirection"],
        limit=limit,
        offset=offset,
        volumeResolution=normalize_volume_resolution(ERROR_TRACKING_LISTING_VOLUME_RESOLUTION),
        withAggregations=with_aggregations,
        withFirstEvent=False,
        withLastEvent=False,
        tags={"productKey": "error_tracking"},
    )


def _run_error_tracking_list_query(team: Team, query: ErrorTrackingQuery, user: User | None) -> dict[str, object]:
    with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
        return ErrorTrackingQueryRunner(team=team, query=query, user=user).calculate().model_dump(mode="json")


def _count_matching_error_tracking_issues(
    team: Team,
    config: ValidatedErrorTrackingListWidgetConfig,
    user: User | None,
    *,
    cap: int = MAX_WIDGET_RESULT_LIMIT,
) -> tuple[int, bool]:
    count_query = _build_error_tracking_list_query(
        team=team,
        config=config,
        limit=cap,
        offset=0,
        with_aggregations=True,
    )
    data = _run_error_tracking_list_query(team, count_query, user)
    raw_results_value = data.get("results")
    raw_results = raw_results_value if isinstance(raw_results_value, list) else []
    count_has_more, _ = get_page_info(data, cap, 0)
    return len(raw_results), count_has_more


def run_error_tracking_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(ERROR_TRACKING_LIST_WIDGET_TYPE, config)
    limit = typed_config["limit"]
    offset = 0
    data = _run_error_tracking_list_query(
        team,
        _build_error_tracking_list_query(
            team=team,
            config=typed_config,
            limit=limit,
            offset=offset,
            with_aggregations=True,
        ),
        user,
    )
    raw_results_value = data.get("results")
    raw_results = cast(list[object], raw_results_value) if isinstance(raw_results_value, list) else []
    results = [pick_fields(cast(dict[str, object], issue), LIST_ISSUE_FIELDS) for issue in raw_results[:limit]]
    has_more, next_offset = get_page_info(data, limit, offset)
    shown = len(results)

    payload: dict[str, Any] = {
        "results": results,
        "hasMore": has_more,
        "limit": limit,
        "offset": offset,
    }

    if has_more:
        if include_total_count:
            try:
                total_count, total_count_capped = _count_matching_error_tracking_issues(team, typed_config, user)
                payload["totalCount"] = total_count
                payload["totalCountCapped"] = total_count_capped
            except Exception:
                logger.exception("error_tracking_widget_total_count_failed")
                payload["totalCount"] = shown
                payload["totalCountCapped"] = True
    else:
        payload["totalCount"] = shown
        payload["totalCountCapped"] = False
    if next_offset is not None:
        payload["nextOffset"] = next_offset
    return payload
