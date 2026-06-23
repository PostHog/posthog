from __future__ import annotations

from typing import Any, cast

from posthog.schema import DateRange, ErrorTrackingIssueAssignee, ErrorTrackingQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import ERROR_TRACKING_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.config import resolve_filter_test_accounts
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.dashboards.backend.widgets.widget_filters import build_property_group_filter_from_widget_filters
from products.error_tracking.backend.facade.queries import ErrorTrackingQueryRunner
from products.error_tracking.backend.facade.query_utils import (
    ERROR_TRACKING_LISTING_VOLUME_RESOLUTION,
    LIST_ISSUE_FIELDS,
    build_date_range,
    get_page_info,
    normalize_volume_resolution,
    pick_fields,
)

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


def run_error_tracking_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(ERROR_TRACKING_LIST_WIDGET_TYPE, config)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        query = _build_error_tracking_list_query(
            team=team,
            config=typed_config,
            limit=page_limit,
            offset=0,
            with_aggregations=True,
        )
        data = _run_error_tracking_list_query(team, query, user)
        raw_results = data.get("results")
        has_more, next_offset = get_page_info(data, page_limit, 0)
        return ListWidgetPage(
            results=raw_results if isinstance(raw_results, list) else [],
            has_more=has_more,
            next_offset=next_offset,
        )

    return run_list_widget(
        limit=typed_config["limit"],
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=lambda issue: pick_fields(cast(dict[str, object], issue), LIST_ISSUE_FIELDS),
        log_key="error_tracking_widget_total_count_failed",
    )
