import pytest

from posthog.management.commands.start_temporal_worker import WORKFLOWS_DICT
from posthog.temporal.workflow_catalog import CATALOG_PATH, UNKNOWN_PRODUCT, render_catalog, workflow_product

REGISTERED_WORKFLOWS = sorted(
    {workflow for workflows in WORKFLOWS_DICT.values() for workflow in workflows},
    key=lambda workflow: f"{workflow.__module__}.{workflow.__qualname__}",
)


@pytest.mark.parametrize("workflow", REGISTERED_WORKFLOWS, ids=lambda workflow: workflow.__qualname__)
def test_every_registered_workflow_has_a_product(workflow: type) -> None:
    assert workflow_product(workflow) != UNKNOWN_PRODUCT, (
        f"{workflow.__module__} is outside products/ and posthog/temporal/: teach workflow_product where it lives"
    )


def test_committed_catalog_is_current() -> None:
    assert CATALOG_PATH.read_text() == render_catalog(), (
        "Run `python manage.py export_temporal_workflow_catalog` and commit posthog/temporal/workflow_catalog.json"
    )
