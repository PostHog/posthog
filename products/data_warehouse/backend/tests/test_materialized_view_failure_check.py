import datetime as dt

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
    DataWarehouseSavedQuery,
)
from products.data_warehouse.backend.temporal.health_checks.materialized_view_failure import (
    MaterializedViewFailureCheck,
)

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.UTC)


class TestMaterializedViewFailureCheck(BaseTest):
    def _view(
        self,
        name: str = "daily_revenue",
        *,
        status: str | None = None,
        latest_error: str | None = None,
        deleted: bool | None = False,
    ) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
            is_materialized=True,
            status=status,
            latest_error=latest_error,
            deleted=deleted,
        )

    def _job(
        self,
        view: DataWarehouseSavedQuery,
        status: str,
        *,
        ran_at: dt.datetime = NOW,
        engine: str = DataModelingJobEngine.CLICKHOUSE,
        error: str | None = None,
    ) -> DataModelingJob:
        return DataModelingJob.objects.create(
            team=self.team,
            saved_query=view,
            status=status,
            engine=engine,
            error=error,
            last_run_at=ran_at,
        )

    def _detected_ids(self) -> set[str]:
        issues = MaterializedViewFailureCheck().detect([self.team.id])
        return {result.payload["pipeline_id"] for result in issues.get(self.team.id, [])}

    def _payload(self, view: DataWarehouseSavedQuery) -> dict:
        issues = MaterializedViewFailureCheck().detect([self.team.id])
        return next(r.payload for r in issues[self.team.id] if r.payload["pipeline_id"] == str(view.id))

    @parameterized.expand(
        [
            (DataModelingJobStatus.FAILED, True),
            (DataModelingJobStatus.COMPLETED, False),
            (DataModelingJobStatus.RUNNING, False),
            (DataModelingJobStatus.CANCELLED, False),
            (DataModelingJobStatus.SKIPPED, False),
        ]
    )
    def test_the_newest_run_decides_whether_a_view_is_failing(self, job_status: str, expected: bool) -> None:
        view = self._view()
        self._job(view, job_status)
        assert self._detected_ids() == ({str(view.id)} if expected else set())

    def test_a_view_that_recovered_is_not_reported_from_its_frozen_columns(self) -> None:
        view = self._view(
            status=DataWarehouseSavedQuery.Status.FAILED,
            latest_error="Query exceeded timeout limit",
        )
        self._job(view, DataModelingJobStatus.FAILED, ran_at=NOW - dt.timedelta(days=120))
        self._job(view, DataModelingJobStatus.COMPLETED, ran_at=NOW)
        assert self._detected_ids() == set()

    def test_a_duckgres_shadow_success_does_not_stand_in_for_the_serving_run(self) -> None:
        view = self._view()
        self._job(view, DataModelingJobStatus.FAILED, ran_at=NOW - dt.timedelta(minutes=1))
        self._job(view, DataModelingJobStatus.COMPLETED, ran_at=NOW, engine=DataModelingJobEngine.DUCKGRES)
        assert self._detected_ids() == {str(view.id)}

    def test_a_view_whose_deleted_flag_was_never_written_is_still_visible(self) -> None:
        view = self._view(deleted=None)
        self._job(view, DataModelingJobStatus.FAILED)
        assert self._detected_ids() == {str(view.id)}

    def test_a_deleted_view_is_not_reported(self) -> None:
        view = self._view(deleted=True)
        self._job(view, DataModelingJobStatus.FAILED)
        assert self._detected_ids() == set()

    def test_the_reported_error_comes_from_the_failing_run(self) -> None:
        view = self._view(latest_error="Unknown table 'old_name'")
        self._job(view, DataModelingJobStatus.FAILED, error="Memory limit exceeded")
        assert self._payload(view)["error"] == "Memory limit exceeded"

    def test_a_view_that_has_never_run_is_not_reported(self) -> None:
        # A model that never ran is dark, not failing. That gap needs its own assertion,
        # and firing here would bury real failures under every never-materialized managed view.
        self._view()
        assert self._detected_ids() == set()
