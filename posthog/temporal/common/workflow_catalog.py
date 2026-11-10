"""Map each Temporal workflow type to the product that owns its code.

Temporal Cloud bills actions per workflow type (`temporal_cloud_v1_billable_action_count`).
Workers publish `posthog_temporal_workflow_info` so that metric can be joined to a product
and a task queue, which turns the namespace-level invoice into a per-product cost.
"""

import collections.abc

from prometheus_client import Gauge
from temporalio.workflow import _Definition

# `posthog/temporal/<area>/` package -> `products/` directory. Code under `products/<name>/` needs no entry.
TEMPORAL_AREA_PRODUCTS: dict[str, str] = {
    "ai": "posthog_ai",
    "ai_observability": "ai_observability",
    "alerts": "alerts",
    "backfill_group_type_created_at": "groups",
    "backfill_materialized_property": "product_analytics",
    "billing_active_sync": "billing",
    "cleanup_property_definitions": "event_definitions",
    "data_modeling": "data_modeling",
    "delete_persons": "persons",
    "delete_teams": "platform_features",
    "dlq_replay": "ingestion",
    "event_screenshots": "product_analytics",
    "experiments": "experiments",
    "exports": "exports",
    "health_checks": "platform_features",
    "ingestion_acceptance_test": "ingestion",
    "logs_alerting": "logs",
    "mcp_analytics": "mcp_analytics",
    "proxy_service": "platform_features",
    "quota_limiting": "billing",
    "salesforce_enrichment": "growth",
    "session_replay": "session_replay",
    "sync_events_retention": "product_analytics",
    "tests": "platform_features",
    "usage_report": "billing",
    "warehouse_sources_queue_partition_management": "warehouse_sources_queue",
    "weekly_digest": "growth",
}

UNKNOWN_PRODUCT = "unknown"


def workflow_type(workflow: type) -> str:
    # A dynamic workflow has no fixed name; it runs whatever type it is started with.
    return _Definition.must_from_class(workflow).name or "dynamic"


def workflow_product(workflow: type) -> str:
    parts = workflow.__module__.split(".")
    if len(parts) > 1 and parts[0] == "products":
        return parts[1]
    if len(parts) > 2 and parts[:2] == ["posthog", "temporal"]:
        return TEMPORAL_AREA_PRODUCTS.get(parts[2], UNKNOWN_PRODUCT)
    return UNKNOWN_PRODUCT


WORKFLOW_INFO = Gauge(
    "posthog_temporal_workflow_info",
    "Always 1. Labels map a workflow type to its product and the task queue that runs it.",
    ["temporal_workflow_type", "product", "task_queue"],
)


def register_workflow_info(task_queue: str, workflows: collections.abc.Sequence[type]) -> None:
    for workflow in workflows:
        WORKFLOW_INFO.labels(
            temporal_workflow_type=workflow_type(workflow),
            product=workflow_product(workflow),
            task_queue=task_queue,
        ).set(1)
