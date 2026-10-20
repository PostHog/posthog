from collections.abc import Callable, Sequence

import pytest

from django.conf import settings

from posthog.management.commands.start_temporal_worker import (
    ACTIVITIES_DICT,
    ACTIVITY_WORKER_CONFIGS,
    AI_WORKFLOWS,
    ALERT_AI_QUEUE_ACTIVITIES,
    DATA_SYNC_WORKFLOWS,
    DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES,
    WA_DIGEST_ACTIVITIES,
    WA_DIGEST_WORKFLOWS,
    WEEKLY_DIGEST_WORKFLOWS,
    WORKFLOWS_DICT,
    _task_queue_specs,
    workflows_include_data_import_syncs,
)
from posthog.temporal.usage_report.activities import aggregate_and_chunk_org_reports

from products.alerts_platform.backend.facade.temporal import (
    DELIVERY_ACTIVITIES,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    SHARED_ORCHESTRATION_ACTIVITIES,
    SHARED_ORCHESTRATION_WORKFLOWS,
)
from products.metrics.backend.facade.temporal import (
    ACTIVITIES as METRICS_ACTIVITIES,
    WORKFLOWS as METRICS_WORKFLOWS,
)
from products.signals.backend.temporal import InboxRankingScoringWorkflow, score_inbox_reports_activity
from products.wizard.backend.facade.temporal import (
    ACTIVITIES as WIZARD_ACTIVITIES,
    WORKFLOWS as WIZARD_WORKFLOWS,
)


class _NotADataSyncWorkflow:
    pass


def _not_a_data_sync_activity() -> None:
    pass


def test_billing_registers_aggregation_with_separate_capacity() -> None:
    (aggregation_worker,) = ACTIVITY_WORKER_CONFIGS[settings.BILLING_TASK_QUEUE]
    assert aggregation_worker.task_queue == settings.USAGE_REPORT_AGGREGATION_TASK_QUEUE
    assert aggregation_worker.task_queue != settings.BILLING_TASK_QUEUE
    assert aggregation_worker.max_concurrent_activities == 1
    assert aggregation_worker.activities == [aggregate_and_chunk_org_reports]
    # A workflow may have scheduled aggregation before the queue change deployed.
    assert aggregate_and_chunk_org_reports in ACTIVITIES_DICT[settings.BILLING_TASK_QUEUE]


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
        (settings.GENERAL_PURPOSE_TASK_QUEUE, METRICS_WORKFLOWS, METRICS_ACTIVITIES),
    ],
)
def test_queue_registers_workflows_and_activities(
    task_queue: str, expected_workflows: Sequence[type], expected_activities: Sequence[Callable[..., object]]
) -> None:
    assert expected_workflows
    assert set(expected_workflows) <= WORKFLOWS_DICT[task_queue]
    assert expected_activities
    assert set(expected_activities) <= ACTIVITIES_DICT[task_queue]
    if task_queue == settings.ALERTS_PLATFORM_SHARED_ORCHESTRATION_TASK_QUEUE:
        assert WORKFLOWS_DICT[task_queue] == set(expected_workflows)
        assert ACTIVITIES_DICT[task_queue] == set(expected_activities)


# Data-import sources import vendor SDKs (google-ads, etc.) that register protobuf descriptors into a
# process-global pool exactly once. The worker eagerly loads them at boot only for queues that run
# data syncs; everything else stays lazy to keep startup fast. Queue settings collapse to a single
# dev queue under DEBUG, so assert the gating predicate directly against workflow sets.
@pytest.mark.parametrize(
    "workflows,activities,expected",
    [
        (list(DATA_SYNC_WORKFLOWS), [], True),
        ([DATA_SYNC_WORKFLOWS[0]], [], True),
        ([DATA_SYNC_WORKFLOWS[0], _NotADataSyncWorkflow], [], True),
        ([_NotADataSyncWorkflow], [], False),
        ([], [], False),
        # The control-plane queue has no workflow, but its job-status activity looks up source classes.
        ([], list(DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES), True),
        ([], [DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES[0], _not_a_data_sync_activity], True),
        ([_NotADataSyncWorkflow], [_not_a_data_sync_activity], False),
    ],
)
def test_only_data_import_queues_warm_sources(
    workflows: list[type], activities: list[Callable[..., object]], expected: bool
) -> None:
    assert workflows_include_data_import_syncs(workflows, activities) is expected


# The import workflows route these activities to the control-plane queue when a setting is on. The
# import queue must keep them too: with the setting off, or while routed tasks drain after a rollback,
# the import worker is their only poller. Queue settings collapse to a single dev queue under DEBUG,
# so match on the spec entries rather than on queue names.
def test_control_plane_activities_are_registered_on_both_warehouse_queues() -> None:
    assert DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES
    control_plane_entries = [
        (workflows, activities)
        for queue, workflows, activities in _task_queue_specs
        if queue == settings.DATA_WAREHOUSE_CONTROL_PLANE_TASK_QUEUE
        and activities is DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES
    ]
    assert control_plane_entries == [([], DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES)]

    import_entries = [
        activities for _, workflows, activities in _task_queue_specs if DATA_SYNC_WORKFLOWS[0] in workflows
    ]
    assert import_entries
    for activities in import_entries:
        assert set(DATA_WAREHOUSE_CONTROL_PLANE_ACTIVITIES) <= set(activities)


# The WA digest schedules name their task queue explicitly, so if these workflows stop being
# registered alongside the queue that serves it, the schedules still fire and nothing polls them,
# which stays invisible for a week because both digests are weekly. Registration has two halves, and
# a workflow registered without its activities fails at runtime the moment it dispatches one, so both
# are asserted. Queue settings collapse to a single dev queue under DEBUG, so match on the spec entry
# that carries the weekly digest rather than on a queue name.
def test_wa_digests_are_registered_with_the_weekly_digest() -> None:
    entries = [
        (workflows, activities)
        for _, workflows, activities in _task_queue_specs
        if WEEKLY_DIGEST_WORKFLOWS[0] in workflows
    ]
    assert len(entries) == 1
    workflows, activities = entries[0]
    assert set(WA_DIGEST_WORKFLOWS) <= set(workflows)
    assert set(WA_DIGEST_ACTIVITIES) <= set(activities)


# CheckAlertWorkflow routes an AI detector's evaluation to the AI queue, because only that worker
# holds the model provider credentials. Routed there without the activity registered, every AI
# alert check would sit unpolled until it timed out. Queue settings collapse to a single dev queue
# under DEBUG, so match on the spec entry that carries the AI workflows rather than on a queue name.
def test_ai_queue_registers_the_alert_evaluate_activity() -> None:
    entries = [activities for _, workflows, activities in _task_queue_specs if AI_WORKFLOWS[0] in workflows]

    assert len(entries) == 1
    assert ALERT_AI_QUEUE_ACTIVITIES
    assert set(ALERT_AI_QUEUE_ACTIVITIES) <= set(entries[0])
