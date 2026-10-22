from datetime import UTC, datetime

import pytest
from unittest.mock import Mock

import dagster
from parameterized import parameterized

from posthog.dags.common.deletion_run_log import reconcile_running_logs
from posthog.models.async_deletion import DeletionRunJob, DeletionRunLog, DeletionRunStatus

WATERMARK = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)


@pytest.mark.django_db
def test_a_reexecution_keeps_what_the_parent_run_recorded_in_the_steps_it_skips() -> None:
    DeletionRunLog.record(
        "parent",
        DeletionRunJob.DELETES,
        None,
        watermark=WATERMARK,
        skipped_person_deletions=7,
        loaded_counts={"Team": 1},
    )
    DeletionRunLog.record("parent", DeletionRunJob.DELETES, None, status=DeletionRunStatus.FAILED)

    DeletionRunLog.record("child", DeletionRunJob.DELETES, "parent", status=DeletionRunStatus.SUCCEEDED)

    child = DeletionRunLog.objects.get(dagster_run_id="child")
    assert (child.parent_run_id, child.status) == ("parent", DeletionRunStatus.SUCCEEDED)
    assert (child.watermark, child.skipped_person_deletions, child.loaded_counts) == (WATERMARK, 7, {"Team": 1})
    assert DeletionRunLog.objects.get(dagster_run_id="parent").status == DeletionRunStatus.FAILED


@parameterized.expand(
    [
        ("succeeded", dagster.DagsterRunStatus.SUCCESS, DeletionRunStatus.SUCCEEDED),
        ("failed", dagster.DagsterRunStatus.FAILURE, DeletionRunStatus.FAILED),
        ("canceled", dagster.DagsterRunStatus.CANCELED, DeletionRunStatus.CANCELED),
        ("missing", None, DeletionRunStatus.FAILED),
        ("still_running", dagster.DagsterRunStatus.STARTED, DeletionRunStatus.RUNNING),
    ]
)
@pytest.mark.django_db
def test_reconcile_closes_rows_whose_run_ended(
    _name: str, run_status: dagster.DagsterRunStatus | None, expected: DeletionRunStatus
) -> None:
    DeletionRunLog.record("run", DeletionRunJob.SQUASH_PERSON_OVERRIDES, None)
    instance = Mock()
    instance.get_run_by_id.return_value = None if run_status is None else Mock(status=run_status)

    reconcile_running_logs(instance)

    log = DeletionRunLog.objects.get(dagster_run_id="run")
    assert log.status == expected
    assert (log.finished_at is None) == (expected == DeletionRunStatus.RUNNING)
