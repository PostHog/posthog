from collections.abc import Callable, Sequence

import pytest

from django.conf import settings

from posthog.hogql import parser as hogql_parser

from posthog.management.commands.start_temporal_worker import (
    ACTIVITIES_DICT,
    AI_WORKFLOWS,
    ALERT_AI_QUEUE_ACTIVITIES,
    DATA_SYNC_WORKFLOWS,
    WORKFLOWS_DICT,
    _task_queue_specs,
    apply_hogql_shadow_sample_rate_override,
    workflows_include_data_import_syncs,
)
from posthog.temporal.ai_observability import BatchTraceSummarizationWorkflow
from posthog.temporal.common.registration import QueueBinding, combined_registration, load_registrations
from posthog.temporal.usage_report.activities import aggregate_and_chunk_org_reports
from posthog.temporal.usage_report.workflow import RunUsageReportsWorkflow

from products.ai_observability.backend.facade.temporal import (
    ACTIVITIES as AI_OBSERVABILITY_ACTIVITIES,
    WORKFLOWS as AI_OBSERVABILITY_WORKFLOWS,
)
from products.alerts.backend.facade.temporal import PLATFORM_AI_QUEUE_ACTIVITIES as ALERTS_AI_QUEUE_ACTIVITIES
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
from products.warehouse_sources.backend.facade.temporal import (
    WAREHOUSE_ALERT_EVALUATION_ACTIVITIES,
    WAREHOUSE_ALERT_EVALUATION_WORKFLOWS,
)
from products.web_analytics.backend.facade.temporal import WA_DIGEST_ACTIVITIES, WA_DIGEST_WORKFLOWS
from products.wizard.backend.facade.temporal import (
    ACTIVITIES as WIZARD_ACTIVITIES,
    WORKFLOWS as WIZARD_WORKFLOWS,
)


class _NotADataSyncWorkflow:
    pass


# Queue settings collapse to a single dev queue under DEBUG, so match on the spec entries rather than on queue names.
def test_aggregation_runs_on_its_own_queue_and_the_billing_queue() -> None:
    aggregation_entries = [
        activities
        for task_queue, workflows, activities in _task_queue_specs
        if task_queue == settings.USAGE_REPORT_AGGREGATION_TASK_QUEUE and not workflows
    ]
    assert any(aggregate_and_chunk_org_reports in activities for activities in aggregation_entries)
    # A workflow may have scheduled aggregation on the billing queue before the queue change deployed.
    (billing_activities,) = [
        activities for _, workflows, activities in _task_queue_specs if RunUsageReportsWorkflow in workflows
    ]
    assert aggregate_and_chunk_org_reports in billing_activities


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
        (
            "alerts-platform-evaluation-task-queue",
            WAREHOUSE_ALERT_EVALUATION_WORKFLOWS,
            WAREHOUSE_ALERT_EVALUATION_ACTIVITIES,
        ),
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
# are asserted. Queue values collapse to a single dev queue under DEBUG, so match on the queue setting
# that the web_analytics declaration names.
def test_wa_digests_are_registered_with_the_weekly_digest() -> None:
    (digests,) = [
        binding
        for binding in load_registrations()["web_analytics"].queues
        if binding.queue_setting == "WEEKLY_DIGEST_TASK_QUEUE"
    ]
    assert set(WA_DIGEST_WORKFLOWS) <= set(digests.workflows)
    assert set(WA_DIGEST_ACTIVITIES) <= set(digests.activities)


# CheckAlertWorkflow routes an AI detector's evaluation to the AI queue, because only that worker
# holds the model provider credentials. Routed there without the activity registered, every AI
# alert check would sit unpolled until it timed out. Queue values collapse to a single dev queue
# under DEBUG, so match on the spec entry that carries the AI workflows, and on the queue setting that
# the alerts declaration names.
def test_ai_queue_registers_the_alert_evaluate_activity() -> None:
    entries = [activities for _, workflows, activities in _task_queue_specs if AI_WORKFLOWS[0] in workflows]

    assert len(entries) == 1
    assert ALERT_AI_QUEUE_ACTIVITIES
    assert set(ALERT_AI_QUEUE_ACTIVITIES) <= set(entries[0])
    assert ALERTS_AI_QUEUE_ACTIVITIES
    assert QueueBinding(queue_setting="MAX_AI_TASK_QUEUE", activities=tuple(ALERTS_AI_QUEUE_ACTIVITIES)) in (
        load_registrations()["alerts"].queues
    )


# The facade starts the trace summary on the LLMA queue by name. Registered elsewhere, every request would stay
# pending until its entry expired.
def test_trace_summary_runs_on_the_llma_queue() -> None:
    (llma,) = [
        binding
        for binding in load_registrations()["ai_observability"].queues
        if set(AI_OBSERVABILITY_WORKFLOWS) <= set(binding.workflows)
    ]
    assert llma.queue_setting == "LLMA_TASK_QUEUE"
    assert set(AI_OBSERVABILITY_ACTIVITIES) <= set(llma.activities)
    assert any(
        queue == settings.LLMA_TASK_QUEUE and BatchTraceSummarizationWorkflow in workflows
        for queue, workflows, _ in _task_queue_specs
    )


@pytest.mark.parametrize(
    "env_value, expected",
    [
        (None, 0.001),
        ("0", 0.0),
        ("0.25", 0.25),
        ("off", 0.001),
        ("2", 0.001),
    ],
)
def test_hogql_shadow_sample_rate_override(
    monkeypatch: pytest.MonkeyPatch, env_value: str | None, expected: float
) -> None:
    monkeypatch.delenv("HOGQL_PARSER_SHADOW_SAMPLE_RATE", raising=False)
    if env_value is not None:
        monkeypatch.setenv("HOGQL_PARSER_SHADOW_SAMPLE_RATE", env_value)
    monkeypatch.setattr(hogql_parser, "_SHADOW_SAMPLE_RATE", 0.001)
    apply_hogql_shadow_sample_rate_override()
    assert hogql_parser._SHADOW_SAMPLE_RATE == expected


def test_the_worker_hosts_every_binding_that_a_product_declares() -> None:
    for binding in combined_registration().queues:
        assert set(binding.workflows) <= WORKFLOWS_DICT[binding.task_queue]
        assert set(binding.activities) <= ACTIVITIES_DICT[binding.task_queue]
