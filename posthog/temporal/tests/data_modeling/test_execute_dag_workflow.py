import uuid
import datetime as dt

import pytest

import pytest_asyncio
import temporalio.worker
import temporalio.exceptions
from temporalio import (
    activity as temporal_activity,
    workflow as temporal_workflow,
)
from temporalio.testing import WorkflowEnvironment

from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling.activities import GetDAGStructureInputs, get_dag_structure_activity
from posthog.temporal.data_modeling.activities.get_dag_structure import DAG
from posthog.temporal.data_modeling.workflows.execute_dag import (
    EmptyDAGOrCycleError,
    ExecuteDAGInputs,
    ExecuteDAGResult,
    ExecuteDAGWorkflow,
    _dag_execution_levels,
    _get_dependent_lookup,
    _get_downstream_lookup,
    _get_edge_lookup,
)
from posthog.temporal.data_modeling.workflows.materialize_view import (
    MaterializeViewWorkflowInputs,
    MaterializeViewWorkflowResult,
)

from products.data_modeling.backend.models import Edge, Node, NodeType
from products.data_warehouse.backend.models import DataWarehouseSavedQuery

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


class TestGetDagStructureActivity:
    @pytest_asyncio.fixture
    async def saved_queries(self, ateam, auser):
        queries = []
        for name in ["model_a", "model_b", "model_c"]:
            query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
                team=ateam,
                name=name,
                query={"query": "SELECT 1", "kind": "HogQLQuery"},
                created_by=auser,
            )
            queries.append(query)
        yield queries
        for query in queries:
            await database_sync_to_async(query.delete)()

    @pytest_asyncio.fixture
    async def dag_nodes(self, ateam, saved_queries):
        dag_id = "test-dag"
        nodes = []
        # source table (not executable)
        source_node = await database_sync_to_async(Node.objects.create)(
            team=ateam,
            dag_id=dag_id,
            name="events",
            type=NodeType.TABLE,
        )
        nodes.append(source_node)
        # executable nodes
        for query in saved_queries:
            node = await database_sync_to_async(Node.objects.create)(
                team=ateam,
                dag_id=dag_id,
                name=query.name,
                type=NodeType.MAT_VIEW,
                saved_query=query,
            )
            nodes.append(node)
        yield nodes
        for node in nodes:
            await database_sync_to_async(node.delete)()

    @pytest_asyncio.fixture
    async def dag_edges(self, ateam, dag_nodes):
        dag_id = "test-dag"
        edges = []
        # events -> model_a, model_a -> model_b, model_a -> model_c
        source, model_a, model_b, model_c = dag_nodes
        edge1 = await database_sync_to_async(Edge.objects.create)(
            team=ateam,
            dag_id=dag_id,
            source=source,
            target=model_a,
        )
        edges.append(edge1)
        edge2 = await database_sync_to_async(Edge.objects.create)(
            team=ateam,
            dag_id=dag_id,
            source=model_a,
            target=model_b,
        )
        edges.append(edge2)
        edge3 = await database_sync_to_async(Edge.objects.create)(
            team=ateam,
            dag_id=dag_id,
            source=model_a,
            target=model_c,
        )
        edges.append(edge3)
        yield edges
        for edge in edges:
            await database_sync_to_async(edge.delete)()

    async def test_retrieves_all_nodes(self, activity_environment, ateam, dag_nodes):
        inputs = GetDAGStructureInputs(team_id=ateam.pk, dag_id="test-dag")
        dag = await activity_environment.run(get_dag_structure_activity, inputs)
        assert len(dag.nodes) == 4
        node_ids = {str(node.id) for node in dag_nodes}
        assert set(dag.nodes) == node_ids

    async def test_filters_executable_nodes(self, activity_environment, ateam, dag_nodes):
        inputs = GetDAGStructureInputs(team_id=ateam.pk, dag_id="test-dag")
        dag = await activity_environment.run(get_dag_structure_activity, inputs)
        # only MAT_VIEW nodes are executable (model_a, model_b, model_c)
        assert len(dag.executable_nodes) == 3
        source_node = dag_nodes[0]
        assert str(source_node.id) not in dag.executable_nodes

    @pytest.mark.usefixtures("dag_edges")  # avoids type checking unused arg
    async def test_excludes_source_table_edges(self, activity_environment, ateam):
        inputs = GetDAGStructureInputs(team_id=ateam.pk, dag_id="test-dag")
        dag = await activity_environment.run(get_dag_structure_activity, inputs)
        # edges from TABLE nodes are excluded
        # only model_a -> model_b and model_a -> model_c should be present
        assert len(dag.edges) == 2

    async def test_empty_dag(self, activity_environment, ateam):
        inputs = GetDAGStructureInputs(team_id=ateam.pk, dag_id="nonexistent-dag")
        dag = await activity_environment.run(get_dag_structure_activity, inputs)
        assert len(dag.nodes) == 0
        assert len(dag.executable_nodes) == 0
        assert len(dag.edges) == 0


class TestDagExecutionLevels:
    @pytest.mark.parametrize(
        "nodes,edges,expected_levels",
        [
            pytest.param(
                ["a", "b", "c"],
                [("a", "b"), ("b", "c")],
                [["a"], ["b"], ["c"]],
                id="linear_chain",
            ),
            pytest.param(
                ["a", "b", "c", "d"],
                [("a", "c"), ("b", "c"), ("c", "d")],
                [["a", "b"], ["c"], ["d"]],
                id="y_shape",
            ),
            pytest.param(
                ["a", "b", "c", "d"],
                [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
                [["a"], ["b", "c"], ["d"]],
                id="diamond_shape",
            ),
            pytest.param(
                ["a", "b", "c"],
                [],
                [["a", "b", "c"]],
                id="no_dependencies",
            ),
            pytest.param(
                ["a"],
                [],
                [["a"]],
                id="single_node",
            ),
            pytest.param(
                ["a", "b", "c", "d", "e"],
                [("a", "c"), ("b", "c"), ("c", "d"), ("c", "e")],
                [["a", "b"], ["c"], ["d", "e"]],
                id="x_shape",
            ),
        ],
    )
    def test_topological_sort(self, nodes, edges, expected_levels):
        edge_lookup = _get_edge_lookup(edges)
        levels = _dag_execution_levels(team_id=1, dag_id="test", nodes=nodes, edge_lookup=edge_lookup)
        assert len(levels) == len(expected_levels)
        for actual, expected in zip(levels, expected_levels):
            assert set(actual) == set(expected)

    def test_raises_on_cycle(self):
        nodes = ["a", "b", "c"]
        edges = [("a", "b"), ("b", "c"), ("c", "a")]
        edge_lookup = _get_edge_lookup(edges)
        with pytest.raises(EmptyDAGOrCycleError):
            _dag_execution_levels(team_id=1, dag_id="test", nodes=nodes, edge_lookup=edge_lookup)


class TestDAGUtils:
    @pytest.mark.parametrize(
        "edges,expected",
        [
            pytest.param(
                [("a", "b"), ("a", "c")],
                {"b": {"a"}, "c": {"a"}},
                id="single_source_multiple_targets",
            ),
            pytest.param(
                [("a", "c"), ("b", "c")],
                {"c": {"a", "b"}},
                id="multiple_sources_single_target",
            ),
            pytest.param(
                [],
                {},
                id="empty_edges",
            ),
            pytest.param(
                [("a", "b"), ("b", "c"), ("c", "d")],
                {"b": {"a"}, "c": {"b"}, "d": {"c"}},
                id="linear_chain",
            ),
        ],
    )
    def test_edge_lookup(self, edges, expected):
        result = _get_edge_lookup(edges)
        assert dict(result) == expected

    @pytest.mark.parametrize(
        "edges,expected",
        [
            pytest.param(
                [("a", "b"), ("a", "c")],
                {"a": {"b", "c"}},
                id="single_source_multiple_targets",
            ),
            pytest.param(
                [("a", "c"), ("b", "c")],
                {"a": {"c"}, "b": {"c"}},
                id="multiple_sources_single_target",
            ),
            pytest.param(
                [],
                {},
                id="empty_edges",
            ),
            pytest.param(
                [("a", "b"), ("b", "c"), ("c", "d")],
                {"a": {"b"}, "b": {"c"}, "c": {"d"}},
                id="linear_chain",
            ),
        ],
    )
    def test_dependent_lookup(self, edges, expected):
        edge_lookup = _get_edge_lookup(edges)
        result = _get_dependent_lookup(edge_lookup)
        assert dict(result) == expected

    @pytest.mark.parametrize(
        "edges,expected",
        [
            pytest.param(
                [("a", "b"), ("b", "c"), ("c", "d")],
                {"a": {"b", "c", "d"}, "b": {"c", "d"}, "c": {"d"}, "d": set()},
                id="linear_chain",
            ),
            pytest.param(
                [("a", "b"), ("a", "c")],
                {"a": {"b", "c"}, "b": set(), "c": set()},
                id="fork",
            ),
            pytest.param(
                [("a", "c"), ("b", "c")],
                {"a": {"c"}, "b": {"c"}, "c": set()},
                id="join",
            ),
            pytest.param(
                [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
                {"a": {"b", "c", "d"}, "b": {"d"}, "c": {"d"}, "d": set()},
                id="diamond",
            ),
            pytest.param(
                [],
                {},
                id="empty_edges",
            ),
        ],
    )
    def test_downstream_lookup(self, edges, expected):
        edge_lookup = _get_edge_lookup(edges)
        result = _get_downstream_lookup(edge_lookup)
        assert dict(result) == expected

    def test_downstream_lookup_shared_paths(self):
        """Test that nodes with shared downstream paths are computed correctly.

        This test verifies the fix for a bug where using a shared visited set
        across node computations would cause incorrect downstream calculation.
        In a DAG like:
            a -> c -> e
            b -> c
            b -> d -> e
        Both 'a' and 'b' should correctly include 'e' in their downstreams,
        even though 'e' is reachable via different paths.
        """
        edges = [("a", "c"), ("b", "c"), ("b", "d"), ("c", "e"), ("d", "e")]
        edge_lookup = _get_edge_lookup(edges)
        result = _get_downstream_lookup(edge_lookup)
        assert result["a"] == {"c", "e"}
        assert result["b"] == {"c", "d", "e"}
        assert result["c"] == {"e"}
        assert result["d"] == {"e"}

    def test_downstream_lookup_multiple_roots(self):
        """Test DAG with multiple root nodes sharing downstream paths.

        With the bug, if 'a' was processed first and visited 'd', 'e', 'f',
        then when processing 'b' and 'c', those nodes wouldn't be explored again.
        """
        edges = [
            ("a", "d"),
            ("b", "d"),
            ("c", "e"),
            ("d", "f"),
            ("e", "f"),
        ]
        edge_lookup = _get_edge_lookup(edges)
        result = _get_downstream_lookup(edge_lookup)
        assert result["a"] == {"d", "f"}
        assert result["b"] == {"d", "f"}
        assert result["c"] == {"e", "f"}
        assert result["d"] == {"f"}
        assert result["e"] == {"f"}


class TestExecuteDAGWorkflow:
    async def test_handles_empty_dag(self, ateam):
        """Test that the workflow returns early with empty result when no executable nodes exist."""

        @temporal_activity.defn(name="get_dag_structure_activity")
        async def stub_get_dag_structure(_: GetDAGStructureInputs) -> DAG:
            return DAG(nodes=[], executable_nodes=[], edges=[])

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-queue",
                workflows=[ExecuteDAGWorkflow],
                activities=[stub_get_dag_structure],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result: ExecuteDAGResult = await env.client.execute_workflow(
                    ExecuteDAGWorkflow.run,
                    ExecuteDAGInputs(team_id=ateam.pk, dag_id="empty-dag"),
                    id=f"test-empty-dag-{uuid.uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=dt.timedelta(seconds=30),
                )

        assert result.scheduled_nodes == 0
        assert result.successful_nodes == 0
        assert result.failed_nodes == 0
        assert result.skipped_nodes == 0


_mock_workflow_calls: list[str] = []
_mock_workflow_should_fail: set[str] = set()


@temporal_workflow.defn(name="materialize-view")
class MockMaterializeViewWorkflow:
    @temporal_workflow.run
    async def run(self, inputs: MaterializeViewWorkflowInputs) -> MaterializeViewWorkflowResult:
        _mock_workflow_calls.append(inputs.node_id)
        if inputs.node_id in _mock_workflow_should_fail:
            raise temporalio.exceptions.ApplicationError(f"Node {inputs.node_id} failed")
        return MaterializeViewWorkflowResult(
            job_id="test-job",
            node_id=inputs.node_id,
            rows_materialized=100,
            duration_seconds=1.0,
        )


class TestExecuteDAGWorkflowWithMocks:
    """Tests that use module-level mock workflows to test orchestration behavior."""

    @pytest.fixture(autouse=True)
    def reset_mock_state(self):
        _mock_workflow_calls.clear()
        _mock_workflow_should_fail.clear()
        yield
        _mock_workflow_calls.clear()
        _mock_workflow_should_fail.clear()

    async def test_skips_downstream_on_failure(self):
        """Test that downstream nodes are skipped when an upstream node fails."""
        dag_id = "test-dag"
        node_a_id = str(uuid.uuid4())
        node_b_id = str(uuid.uuid4())
        node_c_id = str(uuid.uuid4())

        @temporal_activity.defn(name="get_dag_structure_activity")
        async def stub_get_dag_structure(_: GetDAGStructureInputs) -> DAG:
            return DAG(
                nodes=[node_a_id, node_b_id, node_c_id],
                executable_nodes=[node_a_id, node_b_id, node_c_id],
                edges=[(node_a_id, node_b_id), (node_b_id, node_c_id)],
            )

        # node a should fail
        _mock_workflow_should_fail.add(node_a_id)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-queue",
                workflows=[ExecuteDAGWorkflow, MockMaterializeViewWorkflow],
                activities=[stub_get_dag_structure],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result: ExecuteDAGResult = await env.client.execute_workflow(
                    ExecuteDAGWorkflow.run,
                    ExecuteDAGInputs(team_id=1, dag_id=dag_id),
                    id=f"test-skip-downstream-{uuid.uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=dt.timedelta(seconds=30),
                )

        assert result.failed_nodes == 1
        assert result.skipped_nodes == 2
        assert result.successful_nodes == 0
        # only node_a should have been called (it's the first level)
        assert node_a_id in _mock_workflow_calls
        assert node_b_id not in _mock_workflow_calls
        assert node_c_id not in _mock_workflow_calls

    async def test_filters_by_node_ids(self):
        """Test that specifying node_ids filters which nodes are executed."""
        dag_id = "test-dag"
        node_a_id = str(uuid.uuid4())
        node_b_id = str(uuid.uuid4())
        node_c_id = str(uuid.uuid4())

        @temporal_activity.defn(name="get_dag_structure_activity")
        async def stub_get_dag_structure(_: GetDAGStructureInputs) -> DAG:
            return DAG(
                nodes=[node_a_id, node_b_id, node_c_id],
                executable_nodes=[node_a_id, node_b_id, node_c_id],
                edges=[],
            )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-queue",
                workflows=[ExecuteDAGWorkflow, MockMaterializeViewWorkflow],
                activities=[stub_get_dag_structure],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result: ExecuteDAGResult = await env.client.execute_workflow(
                    ExecuteDAGWorkflow.run,
                    ExecuteDAGInputs(team_id=1, dag_id=dag_id, node_ids=[node_a_id, node_c_id]),
                    id=f"test-filter-nodes-{uuid.uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=dt.timedelta(seconds=30),
                )

        assert result.scheduled_nodes == 2
        assert result.successful_nodes == 2
        assert node_a_id in _mock_workflow_calls
        assert node_c_id in _mock_workflow_calls
        assert node_b_id not in _mock_workflow_calls

    async def test_returns_node_results_with_failure_details(self):
        """Test that the workflow returns detailed results for each node including failures."""
        dag_id = "test-dag"
        node_a_id = str(uuid.uuid4())
        node_b_id = str(uuid.uuid4())

        @temporal_activity.defn(name="get_dag_structure_activity")
        async def stub_get_dag_structure(_: GetDAGStructureInputs) -> DAG:
            return DAG(
                nodes=[node_a_id, node_b_id],
                executable_nodes=[node_a_id, node_b_id],
                edges=[(node_a_id, node_b_id)],
            )

        # node a should fail
        _mock_workflow_should_fail.add(node_a_id)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-queue",
                workflows=[ExecuteDAGWorkflow, MockMaterializeViewWorkflow],
                activities=[stub_get_dag_structure],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result: ExecuteDAGResult = await env.client.execute_workflow(
                    ExecuteDAGWorkflow.run,
                    ExecuteDAGInputs(team_id=1, dag_id=dag_id),
                    id=f"test-node-results-{uuid.uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=dt.timedelta(seconds=30),
                )

        assert len(result.node_results) == 2
        # find results by node_id
        node_a_result = next(r for r in result.node_results if r.node_id == node_a_id)
        node_b_result = next(r for r in result.node_results if r.node_id == node_b_id)
        assert node_a_result.success is False
        assert node_a_result.error is not None
        assert node_b_result.success is False
        assert node_b_result.skipped is True
        assert node_b_result.skip_reason is not None

    async def test_all_nodes_success(self):
        """Test successful execution of all nodes."""
        dag_id = "test-dag"
        # a and b have no dependencies, c depends on both
        node_a_id = str(uuid.uuid4())
        node_b_id = str(uuid.uuid4())
        node_c_id = str(uuid.uuid4())

        @temporal_activity.defn(name="get_dag_structure_activity")
        async def stub_get_dag_structure(_: GetDAGStructureInputs) -> DAG:
            return DAG(
                nodes=[node_a_id, node_b_id, node_c_id],
                executable_nodes=[node_a_id, node_b_id, node_c_id],
                edges=[(node_a_id, node_c_id), (node_b_id, node_c_id)],
            )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="test-queue",
                workflows=[ExecuteDAGWorkflow, MockMaterializeViewWorkflow],
                activities=[stub_get_dag_structure],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                result: ExecuteDAGResult = await env.client.execute_workflow(
                    ExecuteDAGWorkflow.run,
                    ExecuteDAGInputs(team_id=1, dag_id=dag_id),
                    id=f"test-parallel-{uuid.uuid4()}",
                    task_queue="test-queue",
                    execution_timeout=dt.timedelta(seconds=30),
                )

        # all nodes should be called
        assert node_a_id in _mock_workflow_calls
        assert node_b_id in _mock_workflow_calls
        assert node_c_id in _mock_workflow_calls
        assert result.scheduled_nodes == 3
        assert result.successful_nodes == 3
        assert result.failed_nodes == 0
        assert result.skipped_nodes == 0
        assert len(result.node_results) == 3
        assert all(r.success for r in result.node_results)
