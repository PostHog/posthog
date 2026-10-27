from datetime import UTC, datetime

import pytest
from unittest.mock import Mock

import dagster
from parameterized import parameterized

from posthog.dags.common.deletion_run_log import reconcile_running_logs, record_run, record_run_succeeded
from posthog.models.async_deletion import DeletionRunJob, DeletionRunLog, DeletionRunStatus

WATERMARK = datetime(2026, 10, 15, 22, 0, tzinfo=UTC)
RUN_STARTED = datetime(2026, 10, 17, 22, 0, tzinfo=UTC)


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


def _op_context(run_id: str) -> Mock:
    context = Mock(run_id=run_id)
    context.instance.get_run_record_by_id.return_value = Mock(
        start_time=RUN_STARTED.timestamp(), dagster_run=Mock(parent_run_id=None)
    )
    return context


@pytest.mark.django_db
def test_a_row_first_written_by_the_last_step_starts_when_the_dagster_run_started() -> None:
    record_run_succeeded(_op_context("ends_only"), DeletionRunJob.DELETES)

    log = DeletionRunLog.objects.get(dagster_run_id="ends_only")
    assert (log.started_at, log.status) == (RUN_STARTED, DeletionRunStatus.SUCCEEDED)
    assert log.finished_at is not None and log.finished_at > RUN_STARTED


@pytest.mark.django_db
def test_a_later_write_keeps_the_start_time_of_the_row() -> None:
    DeletionRunLog.record("run", DeletionRunJob.DELETES, None, started_at=WATERMARK)

    record_run(_op_context("run"), DeletionRunJob.DELETES, watermark=WATERMARK)

    assert DeletionRunLog.objects.get(dagster_run_id="run").started_at == WATERMARK
