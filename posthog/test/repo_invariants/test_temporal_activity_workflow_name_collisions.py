"""Guard against two Temporal activities/workflows across products sharing a registered name.

`DEBUG=True` collapses every task queue onto one `development-task-queue` worker
(posthog/settings/temporal.py), and `start_temporal_worker.py` registers every queue's
workflows and activities on it. Two different callables registered under the same
Temporal name then make the SDK raise `ValueError: More than one activity/workflow
named ...` and the dev worker never starts. This check ignores queue names on purpose,
since DEBUG can put any two queues on the same worker.
"""

from collections import defaultdict
from typing import Any

import pytest

from temporalio.activity import _Definition as ActivityDefinition
from temporalio.workflow import _Definition as WorkflowDefinition

from posthog.management.commands.start_temporal_worker import _task_queue_specs


def _qualified_name(obj: object) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "kind,spec_index,definition_of",
    [
        ("workflow", 1, WorkflowDefinition.must_from_class),
        ("activity", 2, ActivityDefinition.must_from_callable),
    ],
)
def test_no_duplicate_temporal_names_across_task_queues(kind: str, spec_index: int, definition_of: Any) -> None:
    owners_by_name: dict[str, set[str]] = defaultdict(set)
    for spec in _task_queue_specs:
        for registered in spec[spec_index]:
            name = definition_of(registered).name
            if name is not None:
                owners_by_name[name].add(_qualified_name(registered))

    duplicates = {name: sorted(owners) for name, owners in owners_by_name.items() if len(owners) > 1}
    assert not duplicates, (
        f"Temporal {kind} name(s) registered by more than one definition: {duplicates}. "
        "The DEBUG dev worker collapses every task queue onto one worker, so this crashes "
        f"it at startup. Rename one of the {kind}s."
    )
