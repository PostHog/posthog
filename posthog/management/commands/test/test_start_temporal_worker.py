import importlib
from collections.abc import Callable, Iterable, Sequence

import pytest

from django.conf import settings
from django.test import override_settings

from temporalio import activity, workflow

from posthog.management.commands.start_temporal_worker import DATA_SYNC_WORKFLOWS, workflows_include_data_import_syncs
from posthog.temporal.alerts import AI_QUEUE_ACTIVITIES as ALERT_AI_QUEUE_ACTIVITIES
from posthog.temporal.registry import create_worker_bag_collector
from posthog.temporal.weekly_digest import WORKFLOWS as WEEKLY_DIGEST_WORKFLOWS

from products.alerts.backend.facade.temporal import (
    DELIVERY_ACTIVITIES,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    SHARED_ORCHESTRATION_ACTIVITIES,
    SHARED_ORCHESTRATION_WORKFLOWS,
)
from products.signals.backend.temporal import InboxRankingScoringWorkflow, score_inbox_reports_activity
from products.web_analytics.backend.temporal import (
    ACTIVITIES as WA_DIGEST_ACTIVITIES,
    WORKFLOWS as WA_DIGEST_WORKFLOWS,
)
from products.wizard.backend.facade.temporal import (
    ACTIVITIES as WIZARD_ACTIVITIES,
    WORKFLOWS as WIZARD_WORKFLOWS,
)


class _NotADataSyncWorkflow:
    pass


def test_worker_source_catalog_is_valid() -> None:
    collector = create_worker_bag_collector()
    task_queues: set[str] = set()

    for source in collector._sources:
        assert source.modules, f"Source has no modules: {source}"
        assert source.task_queues, f"Source has no task queues: {source}"
        task_queues.update(source.task_queues)
        modules = [importlib.import_module(name) for name in source.modules]

        for name in source.names:
            assert any(hasattr(module, name) for module in modules), f"{name} missing from {source.modules}"
            for module in modules:
                if not hasattr(module, name):
                    continue
                members = getattr(module, name)
                assert isinstance(members, Iterable) and not isinstance(members, (str, bytes)), (
                    f"{module.__name__}.{name} must contain workflow or activity definitions"
                )
                for member in members:
                    is_workflow = isinstance(member, type) and workflow._Definition.from_class(member) is not None
                    is_activity = callable(member) and activity._Definition.from_callable(member) is not None
                    assert is_workflow or is_activity, f"Invalid definition in {module.__name__}.{name}: {member!r}"

    assert task_queues
    for task_queue in sorted(task_queues):
        bag = collector.collect(task_queue)
        workflow_names = [workflow._Definition.must_from_class(item).name for item in bag.workflows]
        activity_names = [activity._Definition.must_from_callable(item).name for item in bag.activities]
        assert len(workflow_names) == len(set(workflow_names)), (
            f"Duplicate workflow names on {task_queue}: {workflow_names}"
        )
        assert len(activity_names) == len(set(activity_names)), (
            f"Duplicate activity names on {task_queue}: {activity_names}"
        )


@pytest.mark.parametrize(
    "task_queue,expected_workflows,expected_activities",
    [
        (settings.WIZARD_TASK_QUEUE, WIZARD_WORKFLOWS, WIZARD_ACTIVITIES),
        (
            "alerts-platform-shared-orchestration-task-queue",
            SHARED_ORCHESTRATION_WORKFLOWS,
            SHARED_ORCHESTRATION_ACTIVITIES,
        ),
        ("alerts-platform-evaluation-task-queue", EVALUATION_WORKFLOWS, EVALUATION_ACTIVITIES),
        ("alerts-platform-delivery-task-queue", DELIVERY_WORKFLOWS, DELIVERY_ACTIVITIES),
        (settings.SELF_DRIVING_TASK_QUEUE, [InboxRankingScoringWorkflow], [score_inbox_reports_activity]),
    ],
)
def test_queue_registers_workflows_and_activities(
    task_queue: str, expected_workflows: Sequence[type], expected_activities: Sequence[Callable[..., object]]
) -> None:
    bag = create_worker_bag_collector().collect(task_queue)
    assert expected_workflows
    assert set(expected_workflows) <= set(bag.workflows)
    assert expected_activities
    assert set(expected_activities) <= set(bag.activities)
    if task_queue == settings.ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE:
        assert set(bag.workflows) == set(expected_workflows)
        assert set(bag.activities) == set(expected_activities)


# Data-import sources import vendor SDKs (google-ads, etc.) that register protobuf descriptors into a
# process-global pool exactly once. The worker eagerly loads them at boot only for queues that run
# data syncs; everything else stays lazy to keep startup fast. Queue settings collapse to a single
# dev queue under DEBUG, so assert the gating predicate directly against workflow sets.
@pytest.mark.parametrize(
    "workflows,expected",
    [
        (list(DATA_SYNC_WORKFLOWS), True),
        ([DATA_SYNC_WORKFLOWS[0]], True),
        ([DATA_SYNC_WORKFLOWS[0], _NotADataSyncWorkflow], True),
        ([_NotADataSyncWorkflow], False),
        ([], False),
    ],
)
def test_only_data_import_queues_warm_sources(workflows: list[type], expected: bool) -> None:
    assert workflows_include_data_import_syncs(workflows) is expected


# The WA digest schedules name their task queue explicitly, so if these workflows stop being
# registered alongside the queue that serves it, the schedules still fire and nothing polls them,
# which stays invisible for a week because both digests are weekly. Registration has two halves, and
# a workflow registered without its activities fails at runtime the moment it dispatches one, so both
# are asserted. Queue settings collapse to a single dev queue under DEBUG, so give the weekly digest
# a separate queue to verify its registrations independently.
def test_wa_digests_are_registered_with_the_weekly_digest() -> None:
    with override_settings(WEEKLY_DIGEST_TASK_QUEUE="weekly-digest-registration-test"):
        bag = create_worker_bag_collector().collect(settings.WEEKLY_DIGEST_TASK_QUEUE)

    assert set(WEEKLY_DIGEST_WORKFLOWS) <= set(bag.workflows)
    assert set(WA_DIGEST_WORKFLOWS) <= set(bag.workflows)
    assert set(WA_DIGEST_ACTIVITIES) <= set(bag.activities)


# CheckAlertWorkflow routes an AI detector's evaluation to the AI queue, because only that worker
# holds the model provider credentials. Routed there without the activity registered, every AI
# alert check would sit unpolled until it timed out. Queue settings collapse to a single dev queue
# under DEBUG, so give the AI queue a separate name to verify its registrations independently.
def test_ai_queue_registers_the_alert_evaluate_activity() -> None:
    with override_settings(MAX_AI_TASK_QUEUE="ai-registration-test"):
        bag = create_worker_bag_collector().collect(settings.MAX_AI_TASK_QUEUE)

    assert ALERT_AI_QUEUE_ACTIVITIES
    assert set(ALERT_AI_QUEUE_ACTIVITIES) <= set(bag.activities)
