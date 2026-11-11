from pathlib import Path

import pytest

from posthog.management.commands.start_temporal_worker import _task_queue_specs
from posthog.temporal.workflow_catalog import (
    CATALOG_PATH,
    TEMPORAL_AREA_PRODUCTS,
    build_catalog,
    render_catalog,
    workflow_product,
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
    assert workflow_product(workflow) in PRODUCT_DIRS, (
        f"{workflow.__module__} has no product: add its package to TEMPORAL_AREA_PRODUCTS "
        "or move the workflow under products/<name>/"
    )


def test_area_products_name_real_areas_and_products() -> None:
    assert set(TEMPORAL_AREA_PRODUCTS) <= TEMPORAL_AREAS
    assert set(TEMPORAL_AREA_PRODUCTS.values()) <= PRODUCT_DIRS


def test_each_workflow_type_belongs_to_one_product() -> None:
    assert [entry for entry in build_catalog() if "," in entry["product"]] == []


def test_committed_catalog_is_current() -> None:
    assert CATALOG_PATH.read_text() == render_catalog(), (
        "Run `python manage.py export_temporal_workflow_catalog` and commit posthog/temporal/generated/workflow_catalog.json"
    )
