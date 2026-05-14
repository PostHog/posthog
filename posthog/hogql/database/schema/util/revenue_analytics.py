from typing import Literal

from posthog.schema import DatabaseSchemaManagedViewTableKind

from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS


def get_table_kind(
    view_name: str,
) -> (
    Literal[
        DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER,
        DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR,
        DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM,
    ]
    | None
):
    if _is_customer_schema(view_name=view_name):
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER

    if _is_mrr_schema(view_name=view_name):
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR

    if _is_revenue_item_schema(view_name=view_name):
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM

    return None


def _is_customer_schema(view_name: str) -> bool:
    customer_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CUSTOMER]
    return view_name.endswith(customer_schema.source_suffix) or view_name.endswith(customer_schema.events_suffix)


def _is_mrr_schema(view_name: str) -> bool:
    mrr_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_MRR]
    return view_name.endswith(mrr_schema.source_suffix) or view_name.endswith(mrr_schema.events_suffix)


def _is_revenue_item_schema(view_name: str) -> bool:
    revenue_item_schema = VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_REVENUE_ITEM]
    return view_name.endswith(revenue_item_schema.source_suffix) or view_name.endswith(
        revenue_item_schema.events_suffix
    )


def is_event_view(view_name: str) -> bool:
    return _get_event_name(view_name) is not None


def _get_event_name(view_name: str) -> str | None:
    return view_name.split(".")[2] if "revenue_analytics.events" in view_name else None
