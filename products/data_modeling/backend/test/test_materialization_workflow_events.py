from posthog.test.base import BaseTest
from unittest import mock

from products.data_modeling.backend.logic.materialization_workflow_events import emit_materialization_job_finished
from products.data_modeling.backend.models import DataModelingJob, DataModelingJobStatus, DataWarehouseSavedQuery


class TestEmitMaterializationJobFinished(BaseTest):
    def _job(self, **kwargs) -> DataModelingJob:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="daily_revenue", query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        return DataModelingJob.objects.create(
            team=self.team, saved_query=saved_query, status=DataModelingJobStatus.COMPLETED, **kwargs
        )

    def test_a_broken_producer_does_not_fail_the_materialization(self):
        job = self._job()
        with mock.patch(
            "products.data_modeling.backend.logic.materialization_workflow_events.produce_internal_event",
            side_effect=RuntimeError("kafka down"),
        ):
            emit_materialization_job_finished(job)

    def test_skips_jobs_with_no_saved_query(self):
        job = DataModelingJob.objects.create(team=self.team, saved_query=None, status=DataModelingJobStatus.COMPLETED)
        with mock.patch(
            "products.data_modeling.backend.logic.materialization_workflow_events.produce_internal_event"
        ) as produce:
            emit_materialization_job_finished(job)
        produce.assert_not_called()

    def test_retries_reuse_the_event_id(self):
        job = self._job()
        with mock.patch(
            "products.data_modeling.backend.logic.materialization_workflow_events.produce_internal_event"
        ) as produce:
            emit_materialization_job_finished(job)
            emit_materialization_job_finished(job)
        first, second = (call.args[1] for call in produce.call_args_list)
        assert first.uuid == second.uuid
