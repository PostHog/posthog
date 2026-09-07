import pytest

from django.core.management.base import CommandError

from posthog.management.commands.start_temporal_worker import (
    DATA_SYNC_WORKFLOWS,
    WA_DIGEST_ACTIVITIES,
    WA_DIGEST_WORKFLOWS,
    WEEKLY_DIGEST_WORKFLOWS,
    _task_queue_specs,
    resolve_task_queue_registrations,
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
# registered alongside the queue that serves it, the schedules still fire and nothing polls them,
# which stays invisible for a week because both digests are weekly. Registration has two halves, and
# a workflow registered without its activities fails at runtime the moment it dispatches one, so both
# are asserted. Queue settings collapse to a single dev queue under DEBUG, so match on the spec entry
# that carries the weekly digest rather than on a queue name.
# WORKFLOWS_DICT/ACTIVITIES_DICT are defaultdict(set), so a lookup for a queue with no spec entry
# used to return an empty set. The worker then started with zero workflows and zero activities, and
# Temporal failed with the opaque "At least one activity ... must be specified" and crash-looped.
# Fail fast with a clear message that names the queue instead.
def test_unknown_task_queue_fails_fast() -> None:
    with pytest.raises(CommandError, match="no registered workflows or activities"):
        resolve_task_queue_registrations("this-queue-has-no-spec")


def test_known_task_queue_resolves_to_registered_work() -> None:
    known_queue = _task_queue_specs[0][0]
    workflows, activities = resolve_task_queue_registrations(known_queue)
    assert workflows or activities


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
