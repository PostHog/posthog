"""Map each Temporal workflow type to the product that owns its code.

Temporal Cloud bills actions per workflow type (`temporal_cloud_v1_billable_action_count`), so
this map turns the namespace-level invoice into a per-product cost. `generated/workflow_catalog.json` is
the generated copy that the FinOps cost exporter reads; regenerate it with
`python manage.py export_temporal_workflow_catalog`.
"""

import ast
import json
import inspect
import collections
from pathlib import Path

from temporalio.workflow import _Definition

CATALOG_PATH = Path(__file__).parent / "generated" / "workflow_catalog.json"

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


def task_queue_setting_names() -> list[str]:
    """Return the settings name of each `_task_queue_specs` entry, in order.

    Every queue setting resolves to one development queue under DEBUG, so the names are read from
    the source to keep the catalog the same in every environment.
    """
    from posthog.management.commands import start_temporal_worker

    tree = ast.parse(inspect.getsource(start_temporal_worker))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_task_queue_specs" for target in node.targets
        ):
            assert isinstance(node.value, ast.List)
            return [ast.unparse(spec.elts[0]).removeprefix("settings.") for spec in node.value.elts]  # type: ignore[attr-defined]
    raise LookupError("_task_queue_specs not found in start_temporal_worker")


def build_catalog() -> list[dict[str, str]]:
    from posthog.management.commands.start_temporal_worker import _task_queue_specs

    queue_names = task_queue_setting_names()
    if len(queue_names) != len(_task_queue_specs):
        raise ValueError("_task_queue_specs must be a list literal so its queue settings can be read")

    products: dict[str, set[str]] = collections.defaultdict(set)
    queues: dict[str, set[str]] = collections.defaultdict(set)
    for queue_name, spec in zip(queue_names, _task_queue_specs):
        for workflow in spec[1]:
            products[workflow_type(workflow)].add(workflow_product(workflow))
            queues[workflow_type(workflow)].add(queue_name)

    return [
        {
            "temporal_workflow_type": name,
            "product": ",".join(sorted(products[name])),
            "task_queues": ",".join(sorted(queues[name])),
        }
        for name in sorted(products)
    ]


def render_catalog() -> str:
    return json.dumps(build_catalog(), indent=2) + "\n"
