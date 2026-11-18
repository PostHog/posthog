"""Map each Temporal workflow type to the product whose code defines it.

Temporal Cloud bills actions per workflow type, so this turns the namespace-level invoice into a
per-product cost. Regenerate `workflow_catalog.json` with `python manage.py export_temporal_workflow_catalog`.
"""

import ast
import json
import inspect
import collections
from pathlib import Path

from temporalio.workflow import _Definition

CATALOG_PATH = Path(__file__).with_name("workflow_catalog.json")

UNKNOWN_PRODUCT = "unknown"


def workflow_type(workflow: type) -> str:
    # A dynamic workflow has no fixed name; it runs whatever type it is started with.
    return _Definition.must_from_class(workflow).name or "dynamic"


def workflow_product(workflow: type) -> str:
    """`products/<name>/` gives the product; code still under `posthog/temporal/<area>/` reports its area."""
    parts = workflow.__module__.split(".")
    if len(parts) > 1 and parts[0] == "products":
        return parts[1]
    if len(parts) > 2 and parts[:2] == ["posthog", "temporal"]:
        return f"temporal/{parts[2]}"
    return UNKNOWN_PRODUCT


def task_queue_setting_names() -> list[str]:
    """Return the settings name of each `_task_queue_specs` entry, in order.

    Every queue setting resolves to one development queue under DEBUG, so the names come from source.
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

    classes: dict[str, type] = {}
    queues: dict[str, set[str]] = collections.defaultdict(set)
    for queue_name, spec in zip(queue_names, _task_queue_specs):
        for workflow in spec[1]:
            name = workflow_type(workflow)
            if classes.setdefault(name, workflow) is not workflow:
                raise ValueError(f"workflow type {name!r} is defined by more than one class")
            queues[name].add(queue_name)

    return [
        {
            "temporal_workflow_type": name,
            "product": workflow_product(classes[name]),
            "task_queues": ",".join(sorted(queues[name])),
        }
        for name in sorted(classes)
    ]


def render_catalog() -> str:
    return json.dumps(build_catalog(), indent=2) + "\n"
