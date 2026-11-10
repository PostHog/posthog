from pathlib import Path

import pytest

from prometheus_client import REGISTRY

from posthog.management.commands.start_temporal_worker import _task_queue_specs
from posthog.temporal.common.workflow_catalog import (
    TEMPORAL_AREA_PRODUCTS,
    register_workflow_info,
    workflow_product,
    workflow_type,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_DIRS = {path.name for path in (REPO_ROOT / "products").iterdir() if path.is_dir()}
TEMPORAL_AREAS = {path.name for path in (REPO_ROOT / "posthog" / "temporal").iterdir() if path.is_dir()}
REGISTERED_WORKFLOWS = sorted(
    {workflow for spec in _task_queue_specs for workflow in spec[1]},
    key=lambda workflow: f"{workflow.__module__}.{workflow.__qualname__}",
)


@pytest.mark.parametrize("workflow", REGISTERED_WORKFLOWS, ids=lambda workflow: workflow.__qualname__)
def test_every_registered_workflow_has_a_product(workflow: type) -> None:
    # Add the package to TEMPORAL_AREA_PRODUCTS, or move the workflow under products/<name>/.
    assert workflow_product(workflow) in PRODUCT_DIRS


def test_area_products_name_real_areas_and_products() -> None:
    assert set(TEMPORAL_AREA_PRODUCTS) <= TEMPORAL_AREAS
    assert set(TEMPORAL_AREA_PRODUCTS.values()) <= PRODUCT_DIRS


def test_register_workflow_info_sets_one_series_per_workflow() -> None:
    workflow = REGISTERED_WORKFLOWS[0]
    register_workflow_info("catalog-test-queue", [workflow])

    labels = {
        "temporal_workflow_type": workflow_type(workflow),
        "product": workflow_product(workflow),
        "task_queue": "catalog-test-queue",
    }
    assert REGISTRY.get_sample_value("posthog_temporal_workflow_info", labels) == 1
