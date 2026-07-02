import pytest

from django.core.management import call_command

from posthog.management.commands.start_temporal_worker import DATA_SYNC_WORKFLOWS, workflows_include_data_import_syncs


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


# WORKFLOWS_DICT/ACTIVITIES_DICT are defaultdicts, so an unregistered queue no longer raises
# KeyError — it silently yields empty sets that crash create_worker with Temporal's opaque "At
# least one activity, Nexus service, or workflow must be specified". Guard that the command fails
# early with a message naming the offending queue instead.
def test_unregistered_task_queue_raises_descriptive_error() -> None:
    with pytest.raises(ValueError, match="this-queue-does-not-exist"):
        call_command("start_temporal_worker", "--task-queue", "this-queue-does-not-exist")
