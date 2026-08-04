import pytest

from posthog.management.commands.start_temporal_worker import (
    DATA_SYNC_WORKFLOWS,
    WA_DIGEST_WORKFLOWS,
    WEEKLY_DIGEST_WORKFLOWS,
    _task_queue_specs,
    workflows_include_data_import_syncs,
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
# registered alongside the queue that serves it, the schedules still fire and nothing polls them —
# a failure that stays invisible for a week. Queue settings collapse to a single dev queue under
# DEBUG, so match on the spec entry that carries the weekly digest rather than on a queue name.
def test_wa_digests_are_registered_with_the_weekly_digest() -> None:
    entries = [workflows for _, workflows, _ in _task_queue_specs if WEEKLY_DIGEST_WORKFLOWS[0] in workflows]
    assert len(entries) == 1
    assert set(WA_DIGEST_WORKFLOWS) <= set(entries[0])
