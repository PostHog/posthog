import pytest

from posthog.management.commands.start_temporal_worker import (
    DATA_SYNC_WORKFLOWS,
    WA_DIGEST_ACTIVITIES,
    WA_DIGEST_WORKFLOWS,
    WEEKLY_DIGEST_WORKFLOWS,
    _task_queue_specs,
    workflows_include_data_import_syncs,
)

from products.metrics.backend.facade.temporal import (
    ACTIVITIES as METRICS_ALERTING_ACTIVITIES,
    WORKFLOWS as METRICS_ALERTING_WORKFLOWS,
)


class _NotADataSyncWorkflow:
    pass


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


# The metrics alerting schedule names its task queue explicitly, so if the queue has no
# deployed poller the recurring checks fire onto a queue nothing drains — silent, since the
# workflow only times out after its (long) execution timeout. Until a dedicated worker fleet
# is deployed, METRICS_ALERTING_TASK_QUEUE must default to the general-purpose fleet so the
# defaultdict merge folds these workflows/activities into a queue with live pollers.
def test_metrics_alerting_defaults_to_a_polled_queue(monkeypatch) -> None:
    # pytest.ini forces DEBUG=1, which collapses every queue to development-task-queue, so
    # the production default can only be observed by re-evaluating the settings module with
    # DEBUG off and no METRICS_ALERTING_TASK_QUEUE env override.
    monkeypatch.delenv("METRICS_ALERTING_TASK_QUEUE", raising=False)
    try:
        reloaded = _reload_temporal_settings(debug=False)
        assert reloaded.METRICS_ALERTING_TASK_QUEUE == "general-purpose-task-queue"
        assert reloaded.METRICS_ALERTING_TASK_QUEUE == reloaded.GENERAL_PURPOSE_TASK_QUEUE
    finally:
        # importlib.reload mutates the shared module object; restore the DEBUG=1 evaluation
        # so later tests in the process see the collapsed dev queue they expect.
        _reload_temporal_settings(debug=True)

    entries = [
        (queue, workflows, activities)
        for queue, workflows, activities in _task_queue_specs
        if METRICS_ALERTING_WORKFLOWS[0] in workflows
    ]
    assert len(entries) == 1
    _, workflows, activities = entries[0]
    assert set(METRICS_ALERTING_WORKFLOWS) <= set(workflows)
    assert set(METRICS_ALERTING_ACTIVITIES) <= set(activities)


def _reload_temporal_settings(*, debug: bool):
    import importlib

    from unittest.mock import patch

    import posthog.settings.temporal as temporal_settings

    # temporal.py binds `from ...base_variables import DEBUG`, so patching the name on the
    # temporal module is undone by the reload's re-import; patch it at the source instead.
    with patch("posthog.settings.base_variables.DEBUG", debug):
        return importlib.reload(temporal_settings)
