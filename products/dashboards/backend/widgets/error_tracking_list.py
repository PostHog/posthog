from __future__ import annotations

from typing import Any, cast

from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.schema import DateRange, ErrorTrackingQuery

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.widgets.config import (
    merge_base_widget_config_fields,
    resolve_filter_test_accounts,
    validate_widget_list_date_range_if_present,
    validate_widget_list_limit,
    validate_widget_list_order_by,
    validate_widget_list_order_direction,
)
from products.error_tracking.backend.api.query import is_error_tracking_query_v3_enabled, query_v3_volume_resolution
from products.error_tracking.backend.api.query_utils import (
    ERROR_TRACKING_LISTING_VOLUME_RESOLUTION,
    LIST_ISSUE_FIELDS,
    build_date_range,
    get_page_info,
    pick_fields,
)
from products.error_tracking.backend.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner

# Validate/run for one widget_type — register in widget_registry.py. See products/dashboards/CONTRIBUTING.md.
ERROR_TRACKING_ORDER_BY = frozenset({"last_seen", "first_seen", "occurrences", "users", "sessions"})


def validate_error_tracking_list_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise DRFValidationError({"config": "Config must be an object."})

    limit = validate_widget_list_limit(config)
    order_by = validate_widget_list_order_by(config, allowed=ERROR_TRACKING_ORDER_BY, default="occurrences")
    order_direction = validate_widget_list_order_direction(config)

    status_value = config.get("status", "active")
    if status_value not in {"archived", "active", "resolved", "pending_release", "suppressed", "all"}:
        raise DRFValidationError({"config": "status is invalid for error tracking widget config."})

    validated_date_range = validate_widget_list_date_range_if_present(config)

    return {
        "limit": limit,
        "orderBy": order_by,
        "orderDirection": order_direction,
        "status": status_value,
        **({"dateRange": validated_date_range} if validated_date_range is not None else {}),
        **merge_base_widget_config_fields(config),
    }


def run_error_tracking_list_widget(team: Team, config: dict[str, Any], user: User | None = None) -> dict[str, Any]:
    limit = cast(int, config["limit"])
    offset = 0
    date_range_raw = config.get("dateRange")
    use_query_v3 = is_error_tracking_query_v3_enabled(user, team) if user is not None else False
    volume_resolution = ERROR_TRACKING_LISTING_VOLUME_RESOLUTION
    query = ErrorTrackingQuery(
        kind="ErrorTrackingQuery",
        dateRange=DateRange(**build_date_range(date_range_raw)),
        status=cast(str, config.get("status", "active")),
        filterTestAccounts=resolve_filter_test_accounts(config, team),
        orderBy=cast(str, config.get("orderBy", "occurrences")),
        orderDirection=cast(str, config.get("orderDirection", "DESC")),
        limit=limit,
        offset=offset,
        volumeResolution=query_v3_volume_resolution(volume_resolution) if use_query_v3 else volume_resolution,
        useQueryV3=use_query_v3 or None,
        withAggregations=True,
        withFirstEvent=False,
        withLastEvent=False,
        tags={"productKey": "error_tracking"},
    )
    with tags_context(product=Product.ERROR_TRACKING, feature=Feature.QUERY):
        data = ErrorTrackingQueryRunner(team=team, query=query, user=user).calculate().model_dump(mode="json")
    raw_results_value = data.get("results")
    raw_results: list[object] = raw_results_value if isinstance(raw_results_value, list) else []
    results = [pick_fields(cast(dict[str, object], issue), LIST_ISSUE_FIELDS) for issue in raw_results[:limit]]
    has_more, next_offset = get_page_info(data, limit, offset)
    payload: dict[str, Any] = {"results": results, "hasMore": has_more, "limit": limit, "offset": offset}
    if next_offset is not None:
        payload["nextOffset"] = next_offset
    return payload
