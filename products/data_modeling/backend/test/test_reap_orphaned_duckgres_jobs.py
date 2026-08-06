import datetime as dt
from io import StringIO

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.utils import timezone

from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)


@pytest.mark.django_db
class TestReapOrphanedDuckgresJobs(BaseTest):
    def _make_job(self, *, engine: str, status: str, age_minutes: int) -> DataModelingJob:
        job = DataModelingJob.objects.create(team=self.team, engine=engine, status=status)
        # created_at is auto_now_add, so backdate it through the queryset to simulate age
        DataModelingJob.objects.filter(id=job.id).update(created_at=timezone.now() - dt.timedelta(minutes=age_minutes))
        return job

    def test_reaps_only_stale_running_duckgres_jobs(self):
        stale = self._make_job(
            engine=DataModelingJobEngine.DUCKGRES, status=DataModelingJobStatus.RUNNING, age_minutes=8 * 60
        )
        # 2h old: past a single 20-min attempt but well within the worst-case retry window
        # (duckgres_only retries 3 × 20min ≈ 65min) — a still-in-flight job that must NOT be reaped
        within_retry_window = self._make_job(
            engine=DataModelingJobEngine.DUCKGRES, status=DataModelingJobStatus.RUNNING, age_minutes=2 * 60
        )
        clickhouse = self._make_job(
            engine=DataModelingJobEngine.CLICKHOUSE, status=DataModelingJobStatus.RUNNING, age_minutes=8 * 60
        )
        completed = self._make_job(
            engine=DataModelingJobEngine.DUCKGRES, status=DataModelingJobStatus.COMPLETED, age_minutes=8 * 60
        )

        call_command("reap_orphaned_duckgres_jobs", stdout=StringIO())

        stale.refresh_from_db()
        within_retry_window.refresh_from_db()
        clickhouse.refresh_from_db()
        completed.refresh_from_db()

        assert stale.status == DataModelingJobStatus.FAILED
        assert stale.error is not None and "Reaped" in stale.error
        # a possibly-retrying duckgres job, the clickhouse path, and terminal jobs are untouched
        assert within_retry_window.status == DataModelingJobStatus.RUNNING
        assert clickhouse.status == DataModelingJobStatus.RUNNING
        assert completed.status == DataModelingJobStatus.COMPLETED

    def test_dry_run_does_not_modify(self):
        stale = self._make_job(
            engine=DataModelingJobEngine.DUCKGRES, status=DataModelingJobStatus.RUNNING, age_minutes=8 * 60
        )

        call_command("reap_orphaned_duckgres_jobs", "--dry-run", stdout=StringIO())

        stale.refresh_from_db()
        assert stale.status == DataModelingJobStatus.RUNNING
