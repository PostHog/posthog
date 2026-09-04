"""Guard against two Temporal activities/workflows across products sharing a registered name.

`DEBUG=True` collapses every task queue onto one `development-task-queue` worker
(posthog/settings/temporal.py), and `start_temporal_worker.py` registers every queue's
workflows and activities on it. Two different callables registered under the same
Temporal name then make the SDK raise `ValueError: More than one activity/workflow
named ...` and the dev worker never starts. This check ignores queue names on purpose,
since DEBUG can put any two queues on the same worker.
"""

from collections import defaultdict

from temporalio.activity import _Definition as ActivityDefinition
from temporalio.workflow import _Definition as WorkflowDefinition

from posthog.management.commands.start_temporal_worker import _task_queue_specs


def _qualified_name(obj: object) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"  # type: ignore[attr-defined]


def _duplicate_owners_by_registered_name(owners_by_name: dict[str, set[str]]) -> dict[str, list[str]]:
    return {name: sorted(owners) for name, owners in owners_by_name.items() if len(owners) > 1}


def test_no_duplicate_activity_names_across_task_queues() -> None:
    owners_by_name: dict[str, set[str]] = defaultdict(set)
    for _, _, activities in _task_queue_specs:
        for fn in activities:
            definition = ActivityDefinition.must_from_callable(fn)
            if definition.name is not None:
                owners_by_name[definition.name].add(_qualified_name(fn))

    duplicates = _duplicate_owners_by_registered_name(owners_by_name)
    assert not duplicates, (
        f"Temporal activity name(s) registered by more than one function: {duplicates}. "
        "The DEBUG dev worker collapses every task queue onto one worker, so this crashes "
        "it at startup. Rename one of the activities."
    )


def test_no_duplicate_workflow_names_across_task_queues() -> None:
    owners_by_name: dict[str, set[str]] = defaultdict(set)
    for _, workflows, _ in _task_queue_specs:
        for cls in workflows:
            definition = WorkflowDefinition.must_from_class(cls)
            if definition.name is not None:
                owners_by_name[definition.name].add(_qualified_name(cls))

    duplicates = _duplicate_owners_by_registered_name(owners_by_name)
    assert not duplicates, (
        f"Temporal workflow name(s) registered by more than one class: {duplicates}. "
        "The DEBUG dev worker collapses every task queue onto one worker, so this crashes "
        "it at startup. Rename one of the workflows."
    )
