import os
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from uuid import UUID, uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

import pyarrow as pa
import pyarrow.parquet as pq
from rest_framework.exceptions import PermissionDenied, ValidationError
from temporalio.testing import ActivityEnvironment

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models.scoping import team_scope

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.api import require_notebook_node_edit_access, sync_saved_query_to_dag
from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataWarehouseSavedQuery,
    Edge,
    Node,
    NodeType,
)
from products.data_modeling.backend.graph import Graph
from products.data_modeling.backend.logic.node_frequency import build_frequency_graph, scheduled_cadences
from products.data_modeling.backend.temporal.activities.notebook_model import (
    ModelFailure,
    ModelRun,
    RetiredNotebookUpload,
    fail_notebook_model,
    prepare_notebook_model,
    publish_frame,
    publish_notebook_model,
    remove_retired_notebook_upload,
)
from products.data_warehouse.backend.facade.api import get_s3_client
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun, NotebookRun
from products.notebooks.backend.notebook_run import node_run_request_for
from products.notebooks.backend.sandbox.kernel import server
from products.notebooks.backend.sandbox.kernel.bootstrap import KernelSession
from products.notebooks.backend.sandbox.kernel.result_store import (
    ModelOutputTooLarge,
    parquet_result,
    retire_model_session,
)
from products.notebooks.backend.sql_v2 import kernel_server_secret
from products.notebooks.backend.sql_v2_dispatch import _build_plan, resolve_refs
from products.notebooks.backend.test.test_notebook_run import markdown_content
from products.notebooks.backend.warehouse_model import prepare_model_run
from products.warehouse_sources.backend.facade.contracts import UploadedFileRef
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def test_retiring_a_kernel_releases_inputs_and_keeps_recent_results(tmp_path: Path) -> None:
    recent = tmp_path / str(uuid4())
    for name in ("frames", "duck", "runs", "results"):
        (recent / name).mkdir(parents=True)
        (recent / name / "data").write_bytes(b"sample")
    expired = tmp_path / str(uuid4())
    expired.mkdir()
    os.utime(expired, (0, 0))
    retire_model_session(str(recent))
    assert list(recent.iterdir()) == [recent / "results"]
    assert (recent / "results" / "data").read_bytes() == b"sample"
    assert not expired.exists()


@pytest.mark.parametrize(("row_limit", "byte_limit"), [(3, 100_000), (100, 256)])
def test_oversized_output_is_rejected_before_upload(tmp_path: Path, row_limit: int, byte_limit: int) -> None:
    frame_id = str(uuid4())
    batch = pa.record_batch([list(range(20))], names=["quantity"])
    with pa.OSFile(str(tmp_path / f"{frame_id}.arrow"), "wb") as file, pa.ipc.new_file(file, batch.schema) as writer:
        writer.write_batch(batch)
    with (
        pytest.raises(ModelOutputTooLarge),
        parquet_result(frame_id, str(tmp_path), max_rows=row_limit, max_bytes=byte_limit),
    ):
        pytest.fail("An oversized publication returned an upload stream.")


def test_bulk_output_preserves_batches_types_and_empty_tables(tmp_path: Path) -> None:
    schema = pa.schema([("score", pa.int64())])
    for size in (0, 14_000):
        result_id = str(uuid4())
        with pa.OSFile(str(tmp_path / f"{result_id}.arrow"), "wb") as source, pa.ipc.new_file(source, schema) as writer:
            for offset in range(0, size, 1000):
                writer.write_batch(pa.record_batch([range(offset, offset + 1000)], schema=schema))
        with parquet_result(result_id, str(tmp_path), max_rows=14_000, max_bytes=1_000_000) as exported:
            exported.seek(0)
            result = pq.read_table(exported)
        assert result.schema == schema
        assert result["score"].to_pylist() == list(range(size))


class TestNotebookWarehouseModel(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.notebook = Notebook.objects.create(
            team=self.team,
            created_by=self.user,
            content=markdown_content('<SQLV2 nodeId="rows" code="select 1 as score" returnVariable="scores" />'),
        )
        self.url = f"/api/projects/{self.team.id}/notebooks/{self.notebook.short_id}/warehouse_model/"
        self.body: dict[str, str | bool | list[str]] = {
            "table_name": "account_scores",
            "output_cell": "rows",
            "upstream_node_ids": [],
        }

    def declare(self) -> UUID:
        response = self.client.post(self.url, self.body, format="json")
        assert response.status_code == 200, response.content
        return UUID(response.json()["node_id"])

    def test_declaration_wires_dependencies_and_pins_the_program(self) -> None:
        dag = DAG.get_or_create_default(self.team)
        source = Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)
        self.body["upstream_node_ids"] = [str(source.id)]
        node_id = self.declare()
        assert self.declare() == node_id
        target = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="daily_scores", query={"query": "select 1"}
        )
        target_node = Node.objects.create(team=self.team, dag=dag, saved_query=target, type=NodeType.MAT_VIEW)
        node = Node.objects.get(pk=node_id)
        Edge.objects.create(team=self.team, dag=dag, source=node, target=target_node)
        assert str(node_id) in Graph(team_id=self.team.pk, dag_id=dag.pk).get_upstream(target_node.id)
        assert (str(node_id), str(target_node.id)) in build_frequency_graph(dag).edges
        with team_scope(self.team.pk):
            binding = node.notebookmodel
            run_id = uuid4()
            plan = prepare_model_run(
                self.team.pk, self.notebook.id, "rows", binding.definition_hash, self.user.pk, run_id
            )
            assert plan is not None and plan[0] == "rows"
            assert NotebookRun.objects.get(pk=run_id).cell_plan[-1]["code"] == "scores"
            self.notebook.content = markdown_content('<SQLV2 nodeId="rows" code="select 2" returnVariable="scores" />')
            self.notebook.save()
            with self.assertRaises(ValidationError):
                prepare_model_run(
                    self.team.pk, self.notebook.id, "rows", binding.definition_hash, self.user.pk, uuid4()
                )

    def test_model_cadence_and_cycle_validation(self) -> None:
        dag = DAG.get_or_create_default(self.team)
        model = self.declare()
        assert scheduled_cadences(build_frequency_graph(dag))[0][str(model)] == timedelta(days=1)
        self.body["daily_refresh"] = False
        self.declare()
        assert scheduled_cadences(build_frequency_graph(dag))[0][str(model)] is None
        self.body["upstream_node_ids"] = [str(model)]
        result = self.client.post(self.url, self.body, format="json")
        assert result.status_code == 400
        assert not Edge.objects.filter(source_id=model, target_id=model).exists()

    def test_failed_preparation_is_visible_and_overlapping_run_cannot_replace_it(self) -> None:
        node = Node.objects.get(pk=self.declare())

        def attempt() -> ModelRun:
            return ModelRun(
                team_id=self.team.pk,
                node_id=str(node.pk),
                dag_id=str(node.dag_id),
                run_id=uuid4(),
                triggered_by_id=self.user.pk,
            )

        first, second = attempt(), attempt()
        env = ActivityEnvironment()
        env.run(prepare_notebook_model, first)
        with self.assertRaisesRegex(ValueError, "Another run"):
            env.run(prepare_notebook_model, second)
        self.notebook.content = markdown_content('<SQLV2 nodeId="rows" code="select 9" returnVariable="scores" />')
        self.notebook.save()
        changed = self.client.post(self.url, self.body, format="json")
        assert changed.status_code == 400
        assert self.client.get(f"{self.url}{node.id}/").json()["latest_run_id"] == str(first.run_id)
        env.run(fail_notebook_model, ModelFailure(run=first, error="Stopped"))
        with self.assertRaises(ValidationError):
            env.run(prepare_notebook_model, second)
        env.run(fail_notebook_model, ModelFailure(run=second, error="The declared cells changed."))
        status = self.client.get(f"{self.url}{node.id}/").json()
        assert (status["status"], status["latest_run_id"], status["published_run_id"]) == (
            "Failed",
            str(second.run_id),
            None,
        )

    def _execute_cells(self, execution: NotebookRun, runtime: KernelRuntime, directory: Path) -> None:
        session = KernelSession(str(directory))
        for index, cell in enumerate(execution.cell_plan):
            request = node_run_request_for(execution, index)
            plan = _build_plan(request, resolve_refs(self.team.pk, self.notebook, request))
            envelope = {}
            if plan.node_type == "hogql":
                self._query(plan.code)
            else:
                inputs = []
                for spec in plan.inputs:
                    if spec["kind"] == "local":
                        inputs.append(spec)
                        continue
                    query = self._query(spec["query"])
                    frame = pa.Table.from_arrays([pa.array(col) for col in zip(*query.results)], names=query.columns)
                    path = directory / "frames" / f"{spec['run_id']}.arrow"
                    with pa.OSFile(str(path), "wb") as file, pa.ipc.new_file(file, frame.schema) as writer:
                        writer.write_table(frame)
                    inputs.append({**spec, "path": str(path)})
                envelope = session.run_node(
                    {
                        "node": {"type": plan.node_type, "code": plan.code, "output_name": cell["dataframe_name"]},
                        "inputs": inputs,
                    }
                )
                assert envelope["status"] == "ok", envelope.get("error")
            NotebookNodeRun.objects.create(
                team=self.team,
                user=self.user,
                notebook=self.notebook,
                notebook_run=execution,
                node_id=cell["node_id"],
                node_type=plan.node_type,
                code=plan.code,
                kernel_runtime_id=runtime.pk,
                result_id=envelope.get("result_id"),
                status=NotebookNodeRun.Status.DONE,
                envelope=envelope,
            )
        execution.status = NotebookRun.Status.DONE
        execution.save(update_fields=["status"])

    def _query(self, query: str):
        return execute_hogql_query(query, team=self.team, user=self.user, workload=Workload.OFFLINE)

    def test_only_the_model_owner_can_edit_its_dependencies(self) -> None:
        dag = DAG.get_or_create_default(self.team)
        parent = Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)
        self.body["upstream_node_ids"] = [str(parent.pk)]
        node = Node.objects.get(pk=self.declare())
        access = UserAccessControl(user=self.user, team=self.team)
        with team_scope(self.team.pk):
            require_notebook_node_edit_access(self.team.pk, access, [node.pk])
            model = node.notebookmodel
            model.owner_id = self.user.pk + 1
            model.save(update_fields=["owner_id"])
            with self.assertRaises(PermissionDenied):
                require_notebook_node_edit_access(self.team.pk, access, [parent.pk, node.pk])
            with self.assertRaises(PermissionDenied):
                require_notebook_node_edit_access(self.team.pk, access, [parent.pk], deleting_nodes=True)

    def test_model_waits_when_another_run_owns_the_notebook(self) -> None:
        node = Node.objects.get(pk=self.declare())
        with team_scope(self.team.pk):
            interactive = NotebookRun.objects.create(team=self.team, notebook=self.notebook, user=self.user)
            run = ModelRun(
                team_id=self.team.pk,
                node_id=str(node.pk),
                dag_id=str(node.dag_id),
                run_id=uuid4(),
                triggered_by_id=None,
            )
            env = ActivityEnvironment()
            assert env.run(prepare_notebook_model, run) is None
            interactive.status = NotebookRun.Status.DONE
            interactive.save(update_fields=["status"])
            assert env.run(prepare_notebook_model, run)
            assert NotebookRun.objects.get(pk=run.run_id).trigger == NotebookRun.Trigger.WAREHOUSE

    def test_manual_notebook_runs_observe_running_and_recent_jobs(self) -> None:
        from products.data_modeling.backend.logic.node_materialization import (
            MaterializationAlreadyRunningError,
            MaterializationRanRecentlyError,
            run_related_node_materializations,
        )

        node = Node.objects.get(pk=self.declare())
        with team_scope(self.team.pk):
            binding = node.notebookmodel
            job = DataModelingJob.objects.create(team=self.team)
            binding.latest_run_id = job.pk
            binding.save(update_fields=["latest_run_id"])
            with self.assertRaises(MaterializationAlreadyRunningError):
                run_related_node_materializations(
                    self.team.pk, node.pk, direction="upstream", user=self.user, from_browser_session=True
                )
            job.status = DataModelingJob.Status.COMPLETED
            job.save(update_fields=["status"])
            with self.assertRaises(MaterializationRanRecentlyError):
                run_related_node_materializations(
                    self.team.pk, node.pk, direction="upstream", user=self.user, from_browser_session=False
                )

    def test_model_rechecks_an_enforced_account_rule(self) -> None:
        node = Node.objects.get(pk=self.declare())
        run = ModelRun(
            team_id=self.team.pk, node_id=str(node.pk), dag_id=str(node.dag_id), run_id=uuid4(), triggered_by_id=None
        )
        with (
            patch("products.notebooks.backend.warehouse_model.access_refused", return_value=True),
            self.assertRaises(PermissionDenied),
        ):
            ActivityEnvironment().run(prepare_notebook_model, run)
        assert not NotebookRun.objects.for_team(self.team.pk).filter(id=run.run_id).exists()

    def test_model_rechecks_the_authors_project_membership_before_running(self) -> None:
        node = Node.objects.get(pk=self.declare())
        self.organization.memberships.filter(user=self.user).delete()
        run = ModelRun(
            team_id=self.team.pk, node_id=str(node.pk), dag_id=str(node.dag_id), run_id=uuid4(), triggered_by_id=None
        )
        with self.assertRaises(PermissionDenied):
            ActivityEnvironment().run(prepare_notebook_model, run)
        assert not NotebookRun.objects.for_team(self.team.pk).filter(id=run.run_id).exists()

    def test_warehouse_reads_two_complete_generations_and_keeps_the_last_good_one(self) -> None:
        self.notebook.content = markdown_content(
            '<SQLV2 nodeId="inventory" code="select arrayJoin(range(14000)) as item limit 14000" returnVariable="items" />\n'
            '<PythonV2 nodeId="rank" code="items.assign(priority=items.item * 2, stamp=__import__(\'time\').time_ns())" returnVariable="ranked" />\n'
            '<SQLV2 nodeId="selected" code="select item, priority, stamp from ranked" returnVariable="selection" />\n'
            '<SQLV2 nodeId="report" code="select count() from account_scores" />'
        )
        self.notebook.save()
        self.body["output_cell"] = "selected"
        node = Node.objects.get(pk=self.declare())
        env = ActivityEnvironment()
        bucket = f"model-test-{uuid4().hex}"
        previous_stamp = 0
        table_ids = set()
        with team_scope(self.team.pk), override_settings(DATAWAREHOUSE_BUCKET=bucket):
            storage = get_s3_client()
            storage.mkdir(bucket)
            self.addCleanup(storage.rm, bucket, recursive=True)
            with ThreadingHTTPServer(("127.0.0.1", 0), server.KernelServerHandler) as kernel:
                runtime = KernelRuntime.objects.create(
                    team=self.team,
                    notebook=self.notebook,
                    notebook_short_id=self.notebook.short_id,
                    user=self.user,
                    status=KernelRuntime.Status.RUNNING,
                    server_url=f"http://127.0.0.1:{kernel.server_port}",
                )
                thread = Thread(target=kernel.serve_forever, daemon=True)
                thread.start()
                try:
                    previous_table = None
                    for _ in range(2):
                        run = ModelRun(
                            team_id=self.team.pk,
                            node_id=str(node.pk),
                            dag_id=str(node.dag_id),
                            run_id=uuid4(),
                            triggered_by_id=self.user.pk,
                        )
                        prepared = env.run(prepare_notebook_model, run)
                        assert prepared is not None
                        execution = NotebookRun.objects.get(pk=run.run_id)
                        assert "report" not in [cell["node_id"] for cell in execution.cell_plan]
                        with (
                            TemporaryDirectory() as directory,
                            patch.dict(server._config, secret=kernel_server_secret(str(runtime.pk))),
                            patch(
                                "products.notebooks.backend.sandbox.kernel.result_store.model_directory",
                                return_value=directory,
                            ),
                        ):
                            self._execute_cells(execution, runtime, Path(directory))
                            assert env.run(publish_notebook_model, run) == 14000
                            assert env.run(publish_notebook_model, run) == 14000
                        count, unique, total, versions, stamp = self._query(
                            "select count(), uniqExact(item), sum(priority), uniqExact(stamp), max(stamp) from account_scores"
                        ).results[0]
                        assert (count, unique, total, versions) == (14000, 14000, 14000 * 13999, 1)
                        assert stamp > previous_stamp
                        previous_stamp = stamp
                        if previous_table is not None:
                            assert previous_table.get_count() == 14000
                            assert prepared.previous_generation is not None
                            retired = RetiredNotebookUpload(
                                team_id=self.team.pk, generation=prepared.previous_generation
                            )
                            env.run(remove_retired_notebook_upload, retired)
                            retired_key = previous_table.url_pattern.split(f"/{bucket}/", maxsplit=1)[1]
                            assert not storage.exists(f"{bucket}/{retired_key}")
                        previous_table = DataWarehouseTable.objects.get(team=self.team, name="account_scores")
                        table_ids.add(previous_table.pk)
                    assert len(table_ids) == 1
                    consumer = DataWarehouseSavedQuery.objects.create(
                        team=self.team,
                        name="priority_totals",
                        query={"kind": "HogQLQuery", "query": "SELECT sum(priority) FROM account_scores"},
                    )
                    consumer_node = sync_saved_query_to_dag(consumer, reconcile=False)
                    assert Edge.objects.filter(team=self.team, source=node, target=consumer_node).exists()
                    failed = ModelRun(
                        team_id=self.team.pk,
                        node_id=str(node.pk),
                        dag_id=str(node.dag_id),
                        run_id=uuid4(),
                        triggered_by_id=self.user.pk,
                    )
                    env.run(prepare_notebook_model, failed)
                    env.run(fail_notebook_model, ModelFailure(run=failed, error="The transform failed."))
                    assert self._query("select count(), min(stamp) from account_scores").results[0] == (
                        14000,
                        previous_stamp,
                    )
                finally:
                    kernel.shutdown()
                    thread.join()

    def test_run_returns_a_specific_dag_to_poll(self) -> None:
        node = self.declare()
        with patch("posthog.api.notebook_warehouse_model.run_related_node_materializations") as start:
            response = self.client.post(f"{self.url}{node}/run/")
        assert response.status_code == 202, response.content
        ticket = response.json()["dag_run_id"]
        assert start.call_args.kwargs["workflow_id"] == f"notebook-model-dag-{self.team.pk}-{node}-{ticket}"
        with patch(
            "posthog.api.notebook_warehouse_model.notebook_dag_status",
            return_value={"status": "skipped", "reason": "An upstream query failed."},
        ) as status:
            result = self.client.get(f"{self.url}{node}/", {"dag_run_id": ticket})
        status.assert_called_once_with(self.team.pk, node, UUID(ticket))
        assert result.json()["dag"]["status"] == "skipped"

    def test_publication_retry_and_stale_run_leave_last_success_readable(self) -> None:
        node = Node.objects.get(pk=self.declare())
        with team_scope(self.team.pk):
            binding = node.notebookmodel
            run = ModelRun(
                team_id=self.team.pk,
                node_id=str(node.pk),
                dag_id=str(node.dag_id),
                run_id=uuid4(),
                triggered_by_id=None,
            )
            binding.latest_run_id = run.run_id
            binding.save()
            DataModelingJob.objects.create(id=run.run_id, team=self.team)
            upload = UploadedFileRef(upload_id=str(uuid4()), filename="output.parquet", file_format="parquet")
            columns = {"score": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}}
            with (
                patch.object(DataWarehouseTable, "get_columns", return_value=columns),
                patch.object(DataWarehouseTable, "get_count", return_value=14000),
            ):
                publish_frame(run, upload, 14000)
                publish_frame(run, upload, 14000)
                binding.refresh_from_db()
                assert binding.table_id is not None
                table = DataWarehouseTable.objects.get(team=self.team, id=binding.table_id)
                original_url = table.url_pattern
                assert table.row_count == 14000
                assert binding.published_run_id == run.run_id
                binding.latest_run_id = uuid4()
                binding.save()
                with self.assertRaisesRegex(ValueError, "changed"):
                    publish_frame(run, upload, 14000)
                stopped = ModelRun(
                    team_id=self.team.pk,
                    node_id=str(node.pk),
                    dag_id=str(node.dag_id),
                    run_id=binding.latest_run_id,
                    triggered_by_id=None,
                )
                DataModelingJob.objects.create(id=stopped.run_id, team=self.team, status=DataModelingJob.Status.FAILED)
                with self.assertRaisesRegex(ValueError, "already closed"):
                    publish_frame(stopped, upload, 14000)
            table.refresh_from_db()
            assert (table.url_pattern, table.row_count) == (original_url, 14000)
            response = self.client.get(f"{self.url}{node.id}/")
            assert response.status_code == 200
            assert response.json()["published_run_id"] == str(run.run_id)
