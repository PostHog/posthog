from __future__ import annotations

import logging
from typing import Any, cast

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import DateRange, ErrorTrackingIssueAssignee, ErrorTrackingQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widgets.config import (
    merge_base_widget_config_fields,
    resolve_filter_test_accounts,
    validate_widget_list_date_range_if_present,
    validate_widget_list_limit,
    validate_widget_list_order_by,
    validate_widget_list_order_direction,
)
from products.dashboards.backend.widgets.widget_config_types import (
    ErrorTrackingListWidgetConfig,
    ErrorTrackingListWidgetConfigInput,
    ErrorTrackingWidgetAssigneeInput,
)
from products.dashboards.backend.widgets.widget_filters import (
    build_property_group_filter_from_widget_filters,
    validate_widget_filters,
)
from products.error_tracking.backend.api.query import is_error_tracking_query_v3_enabled, query_v3_volume_resolution
from products.error_tracking.backend.api.query_serializers import ErrorTrackingAssigneeSerializer
from products.error_tracking.backend.api.query_utils import (
    ERROR_TRACKING_LISTING_VOLUME_RESOLUTION,
    LIST_ISSUE_FIELDS,
    build_date_range,
    get_page_info,
    pick_fields,
)
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

logger = logging.getLogger(__name__)

# Validate/run for one widget_type — register in widget_registry.py. See products/dashboards/CONTRIBUTING.md.
ERROR_TRACKING_ORDER_BY = frozenset({"last_seen", "first_seen", "occurrences", "users", "sessions"})

ERROR_TRACKING_WIDGET_STATUS_CHOICES = frozenset(
    {"archived", "active", "resolved", "pending_release", "suppressed", "all"}
)


def _parse_error_tracking_widget_assignee(assignee: ErrorTrackingWidgetAssigneeInput) -> ErrorTrackingIssueAssignee:
    serializer = ErrorTrackingAssigneeSerializer(data=assignee)
    serializer.is_valid(raise_exception=True)
    return ErrorTrackingIssueAssignee.model_validate(serializer.validated_data)


def validate_error_tracking_list_config(config: ErrorTrackingListWidgetConfigInput) -> ErrorTrackingListWidgetConfig:
    limit = validate_widget_list_limit(config)
    order_by = validate_widget_list_order_by(config, allowed=ERROR_TRACKING_ORDER_BY, default="occurrences")
    order_direction = validate_widget_list_order_direction(config)

    status_value = config.get("status", "active")
    if status_value not in ERROR_TRACKING_WIDGET_STATUS_CHOICES:
        raise DRFValidationError({"config": "status is invalid for error tracking widget config."})

    validated_date_range = validate_widget_list_date_range_if_present(config)
    assignee_raw = config.get("assignee")
    validated_assignee: ErrorTrackingIssueAssignee | None = None
    if assignee_raw is not None:
        if not isinstance(assignee_raw, dict):
            raise DRFValidationError({"config": "assignee must be an object."})
        validated_assignee = _parse_error_tracking_widget_assignee(cast(ErrorTrackingWidgetAssigneeInput, assignee_raw))
    validated_widget_filters = validate_widget_filters(config)

    validated: ErrorTrackingListWidgetConfig = {
        "limit": limit,
        "orderBy": order_by,
        "orderDirection": order_direction,
        "status": status_value,
        **({"dateRange": validated_date_range} if validated_date_range is not None else {}),
        **({"assignee": validated_assignee} if validated_assignee is not None else {}),
        **({"widgetFilters": validated_widget_filters} if validated_widget_filters is not None else {}),
        **merge_base_widget_config_fields(config),
    }
    return validated


def _build_error_tracking_list_query(
    *,
    team: Team,
    config: ErrorTrackingListWidgetConfig,
    user: User | None,
    limit: int,
    offset: int,
    with_aggregations: bool,
) -> ErrorTrackingQuery:
    date_range_raw = config.get("dateRange")
    use_query_v3 = is_error_tracking_query_v3_enabled(user, team) if user is not None else False
    volume_resolution = ERROR_TRACKING_LISTING_VOLUME_RESOLUTION
    filter_group = build_property_group_filter_from_widget_filters(config.get("widgetFilters"))
    return ErrorTrackingQuery(
        kind="ErrorTrackingQuery",
        dateRange=DateRange(**build_date_range(date_range_raw)),
        status=config["status"],
        assignee=config.get("assignee"),
        filterGroup=filter_group,
        filterTestAccounts=resolve_filter_test_accounts(config, team),
        orderBy=config["orderBy"],
        orderDirection=config["orderDirection"],
        limit=limit,
        offset=offset,
        volumeResolution=query_v3_volume_resolution(volume_resolution) if use_query_v3 else volume_resolution,
        useQueryV3=use_query_v3 or None,
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
    config: ErrorTrackingListWidgetConfig,
    user: User | None,
    *,
    cap: int = MAX_WIDGET_RESULT_LIMIT,
) -> tuple[int, bool]:
    """Return how many issues match the widget filters, and whether the count hit the cap."""
    count_query = _build_error_tracking_list_query(
        team=team,
        config=config,
        user=user,
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
    config: ErrorTrackingListWidgetConfigInput,
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_error_tracking_list_config(config)
    limit = typed_config["limit"]
    offset = 0
    data = _run_error_tracking_list_query(
        team,
        _build_error_tracking_list_query(
            team=team,
            config=typed_config,
            user=user,
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
                # Count is best-effort — never fail the tile when the listing query succeeded.
                logger.exception("error_tracking_widget_total_count_failed")
    else:
        payload["totalCount"] = shown
        payload["totalCountCapped"] = False
    if next_offset is not None:
        payload["nextOffset"] = next_offset
    return payload
