from io import StringIO
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from django.core.management import call_command

from products.data_modeling.backend.logic.node_suspension import (
    is_node_suspended,
    mark_node_suspended,
    suspension_reset_at,
)
from products.data_modeling.backend.logic.saved_query_dag_sync import sync_saved_query_to_dag
from products.data_modeling.backend.management.commands import clear_unearned_node_suspensions as command_module
from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node

CUSTOMER_ERROR = "Code: 47. DB::Exception: Unknown expression identifier 'foo'"
ABORT_ERROR = "Preempted: a new DAG run started before this job completed"


@pytest.mark.django_db
class TestClearUnearnedNodeSuspensions(BaseTest):
    def _suspended_node(self, *, errors: list[str], engine: str = DataModelingJobEngine.CLICKHOUSE) -> Node:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=f"model_{uuid4().hex[:8]}",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        self._record_failures(saved_query, errors, engine=engine)
        mark_node_suspended(node, engine=engine, reason=errors[-1], job_id=str(uuid4()))
        node.save()
        return node

    def _record_failures(
        self,
        saved_query: DataWarehouseSavedQuery,
        errors: list[str],
        *,
        engine: str = DataModelingJobEngine.CLICKHOUSE,
    ) -> None:
        # oldest first, so the last error given is the newest job the counter reads
        for error in errors:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=saved_query,
                engine=engine,
                status=DataModelingJobStatus.FAILED,
                error=error,
            )

    def test_clears_a_marker_the_counter_no_longer_reaches(self):
        # an aborted run sits inside the window, so only three failures are the query's own
        node = self._suspended_node(
            errors=[CUSTOMER_ERROR, ABORT_ERROR, CUSTOMER_ERROR, CUSTOMER_ERROR, CUSTOMER_ERROR]
        )

        call_command("clear_unearned_node_suspensions", "--apply", stdout=StringIO())

        node.refresh_from_db()
        assert not is_node_suspended(node, DataModelingJobEngine.CLICKHOUSE)
        # without the watermark the same old failures re-suspend it on the next run
        assert suspension_reset_at(node, DataModelingJobEngine.CLICKHOUSE) is not None

    def test_keeps_a_marker_five_genuine_failures_still_earn(self):
        node = self._suspended_node(errors=[CUSTOMER_ERROR] * 5)

        call_command("clear_unearned_node_suspensions", "--apply", stdout=StringIO())

        node.refresh_from_db()
        assert is_node_suspended(node, DataModelingJobEngine.CLICKHOUSE)

    def test_dry_run_leaves_the_marker_alone(self):
        node = self._suspended_node(errors=[CUSTOMER_ERROR, ABORT_ERROR, CUSTOMER_ERROR])

        call_command("clear_unearned_node_suspensions", stdout=StringIO())

        node.refresh_from_db()
        assert is_node_suspended(node, DataModelingJobEngine.CLICKHOUSE)

    def test_clears_only_the_engine_that_no_longer_earns_it(self):
        node = self._suspended_node(errors=[CUSTOMER_ERROR] * 5)
        saved_query = node.saved_query
        assert saved_query is not None
        self._record_failures(
            saved_query, [CUSTOMER_ERROR, ABORT_ERROR, CUSTOMER_ERROR], engine=DataModelingJobEngine.DUCKGRES
        )
        mark_node_suspended(node, engine=DataModelingJobEngine.DUCKGRES, reason=CUSTOMER_ERROR, job_id=str(uuid4()))
        node.save()

        call_command("clear_unearned_node_suspensions", "--apply", stdout=StringIO())

        node.refresh_from_db()
        assert is_node_suspended(node, DataModelingJobEngine.CLICKHOUSE)
        assert not is_node_suspended(node, DataModelingJobEngine.DUCKGRES)

    def test_keeps_a_marker_the_model_earns_while_the_sweep_runs(self):
        node = self._suspended_node(
            errors=[CUSTOMER_ERROR, ABORT_ERROR, CUSTOMER_ERROR, CUSTOMER_ERROR, CUSTOMER_ERROR]
        )
        saved_query = node.saved_query
        assert saved_query is not None
        resume = command_module.resume_nodes

        def fail_twice_more_then_resume(*args, **kwargs):
            # stands in for the materializations that keep running while a whole-region sweep walks
            # its list: by the time this marker comes up for clearing, the streak is genuine
            self._record_failures(saved_query, [CUSTOMER_ERROR, CUSTOMER_ERROR])
            return resume(*args, **kwargs)

        with mock.patch.object(command_module, "resume_nodes", fail_twice_more_then_resume):
            call_command("clear_unearned_node_suspensions", "--apply", stdout=StringIO())

        node.refresh_from_db()
        assert is_node_suspended(node, DataModelingJobEngine.CLICKHOUSE)
