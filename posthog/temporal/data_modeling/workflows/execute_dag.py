import json
import datetime as dt
import dataclasses
from collections import defaultdict

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.data_modeling.activities import GetDAGStructureInputs, get_dag_structure_activity
from posthog.temporal.data_modeling.workflows.materialize_view import (
    MaterializeViewWorkflow,
    MaterializeViewWorkflowInputs,
    MaterializeViewWorkflowResult,
)


class EmptyDAGOrCycleError(Exception):
    """Raised when the DAG is empty or contains a cycle according to _dag_execution_levels."""

    pass


@dataclasses.dataclass
class ExecuteDAGInputs:
    """Inputs for the DAGOrchestratorWorkflow.

    Attributes:
        team_id: the team ID that owns the DAG.
        dag_id: the DAG to execute.
        node_ids: optional list of specific node IDs to materialize. If not provided,
            all materializable nodes in the DAG will be processed.
    """

    team_id: int
    dag_id: str
    node_ids: list[str] | None = None

    @property
    def properties_to_log(self) -> dict:
        return {
            "team_id": self.team_id,
            "dag_id": self.dag_id,
            "node_ids": self.node_ids,
        }


@dataclasses.dataclass
class NodeResult:
    """Result for a single node materialization."""

    node_id: str
    success: bool
    rows_materialized: int | None = None
    duration_seconds: float | None = None
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


@dataclasses.dataclass
class ExecuteDAGResult:
    """Result from the DAGOrchestratorWorkflow.

    Attributes:
        dag_id: The DAG that was orchestrated.
        scheduled_nodes: Total number of nodes that were scheduled for materialization.
        successful_nodes: Number of nodes that materialized successfully.
        failed_nodes: Number of nodes that failed to materialize.
        skipped_nodes: Number of nodes skipped due to upstream failures.
        duration_seconds: Total duration of the workflow in seconds.
        node_results: Individual results for each node.
    """

    dag_id: str
    scheduled_nodes: int
    successful_nodes: int
    failed_nodes: int
    skipped_nodes: int
    duration_seconds: float
    node_results: list[NodeResult]


def _get_edge_lookup(edges: list[tuple[str, str]]):
    edge_lookup = defaultdict(set)
    for source, target in edges:
        edge_lookup[target].add(source)
    return edge_lookup


def _get_dependent_lookup(edge_lookup: dict):
    # builds the inverse of the edge_lookup in the DAG object
    dependents = defaultdict(set)
    for target, sources in edge_lookup.items():
        for source in sources:
            dependents[source].add(target)
    return dependents


def _get_downstream_lookup(edge_lookup: dict):
    downstreams = _get_dependent_lookup(edge_lookup)

    def _get_all_downstream(node_id: str, visited: set[str]) -> set[str]:
        if node_id in visited:
            return set()
        visited.add(node_id)
        result = set(downstreams[node_id])
        for downstream in list(downstreams[node_id]):
            result.update(_get_all_downstream(downstream, visited))
        return result

    visited: set[str] = set()
    for node in list(downstreams.keys()):
        downstreams[node] = _get_all_downstream(node, visited)

    return downstreams


def _dag_execution_levels(
    team_id: int,
    dag_id: str,
    nodes: list[str],
    edge_lookup: dict,
) -> list[list[str]]:
    """Compute execution levels using kahn's topological sort."""
    # Initialize in_degree for all nodes, defaulting to 0 for nodes with no dependencies
    in_degree = {node_id: len(edge_lookup.get(node_id, set())) for node_id in nodes}
    # inverse of the edge_lookup
    dependents = _get_dependent_lookup(edge_lookup)
    levels: list[list[str]] = []
    remaining = nodes.copy()
    while remaining:
        current_level = [node_id for node_id in remaining if in_degree[node_id] == 0]
        if not current_level:
            # the only cases where this is possible are an empty DAG or a cycle in the DAG
            raise EmptyDAGOrCycleError(f"DAG is either empty or contains a cycle: team={team_id} dag={dag_id}")
        levels.append(current_level)
        for node_id in current_level:
            remaining.remove(node_id)
            for dependent in dependents[node_id]:
                if dependent in remaining:
                    in_degree[dependent] -= 1
    return levels


@temporalio.workflow.defn(name="execute-dag")
class ExecuteDAGWorkflow(PostHogWorkflow):
    """Temporal workflow to orchestrate materialization of all nodes in a DAG.

    This workflow:
    1. Fetches the DAG structure (nodes and edges)
    2. Computes execution levels based on dependencies
    3. Executes materialization workflows in parallel for each level
    4. Tracks success/failure and skips downstream nodes on failure
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExecuteDAGInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return ExecuteDAGInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: ExecuteDAGInputs) -> ExecuteDAGResult:
        temporalio.workflow.logger.info("Starting DAGOrchestratorWorkflow", **inputs.properties_to_log)
        start_time = temporalio.workflow.now()

        # fetch DAG structure
        dag_structure = await temporalio.workflow.execute_activity(
            get_dag_structure_activity,
            GetDAGStructureInputs(
                team_id=inputs.team_id,
                dag_id=inputs.dag_id,
            ),
            start_to_close_timeout=dt.timedelta(minutes=1),
        )
        executable_nodes = dag_structure.executable_nodes
        # filter to requested nodes if specified
        if inputs.node_ids:
            requested_node_set = set(inputs.node_ids)
            executable_nodes = [node_id for node_id in dag_structure.executable_nodes if node_id in requested_node_set]

        if not executable_nodes:
            temporalio.workflow.logger.info("No executable nodes found", **inputs.properties_to_log)
            end_time = temporalio.workflow.now()
            return ExecuteDAGResult(
                dag_id=inputs.dag_id,
                scheduled_nodes=0,
                successful_nodes=0,
                failed_nodes=0,
                skipped_nodes=0,
                duration_seconds=(end_time - start_time).total_seconds(),
                node_results=[],
            )

        edge_lookup = _get_edge_lookup(dag_structure.edges)
        levels = _dag_execution_levels(inputs.team_id, inputs.dag_id, executable_nodes, edge_lookup)

        temporalio.workflow.logger.info(
            "DAG execution levels",
            levels=levels,
            num_levels=len(levels),
            nodes_per_level=[len(level) for level in levels],
            **inputs.properties_to_log,
        )

        node_results: list[NodeResult] = []
        failed_node_set: set[str] = set()
        downstreams = _get_downstream_lookup(edge_lookup)
        for i, level in enumerate(levels):
            temporalio.workflow.logger.info(
                f"Executing level {i + 1}/{len(levels)}",
                nodes=level,
                **inputs.properties_to_log,
            )
            execute_nodes = []
            skip_nodes = []
            for node_id in level:
                should_skip = False
                skip_reason = None
                for failed_id in failed_node_set:
                    if node_id in downstreams[failed_id]:
                        should_skip = True
                        skip_reason = f"Upstream node {failed_id} failed"
                        break
                if should_skip:
                    skip_nodes.append((node_id, skip_reason))
                else:
                    execute_nodes.append(node_id)

            for node_id, skip_reason in skip_nodes:
                node_results.append(
                    NodeResult(
                        node_id=node_id,
                        success=False,
                        skipped=True,
                        skip_reason=skip_reason,
                    )
                )

            if not execute_nodes:
                continue

            # execute child workflows in parallel for this level
            child_handles = []
            for node_id in execute_nodes:
                handle = await temporalio.workflow.start_child_workflow(
                    MaterializeViewWorkflow.run,
                    MaterializeViewWorkflowInputs(
                        team_id=inputs.team_id,
                        dag_id=inputs.dag_id,
                        node_id=node_id,
                    ),
                    id=f"materialize-{inputs.dag_id}-{node_id}-{temporalio.workflow.now().isoformat()}",
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=1,  # retries handled within child workflow
                    ),
                )
                child_handles.append((node_id, handle))

            # wait for all child workflows in this level to complete
            for node_id, handle in child_handles:
                try:
                    result: MaterializeViewWorkflowResult = await handle
                    node_results.append(
                        NodeResult(
                            node_id=node_id,
                            success=True,
                            rows_materialized=result.rows_materialized,
                            duration_seconds=result.duration_seconds,
                        )
                    )
                    temporalio.workflow.logger.info(
                        f"Node {node_id} materialized successfully",
                        rows=result.rows_materialized,
                        **inputs.properties_to_log,
                    )
                except temporalio.exceptions.ChildWorkflowError as e:
                    failed_node_set.add(node_id)
                    error_message = str(e.cause) if e.cause else str(e)
                    node_results.append(
                        NodeResult(
                            node_id=node_id,
                            success=False,
                            error=error_message,
                        )
                    )
                    temporalio.workflow.logger.error(
                        f"Node {node_id} failed to materialize: {error_message}",
                        **inputs.properties_to_log,
                    )
                except Exception as e:
                    capture_exception(e)
                    failed_node_set.add(node_id)
                    node_results.append(
                        NodeResult(
                            node_id=node_id,
                            success=False,
                            error=str(e),
                        )
                    )
                    temporalio.workflow.logger.error(
                        f"Node {node_id} failed with unexpected error: {str(e)}",
                        **inputs.properties_to_log,
                    )

        # compute summary
        end_time = temporalio.workflow.now()
        duration_seconds = (end_time - start_time).total_seconds()

        successful_nodes = sum(1 for r in node_results if r.success)
        failed_nodes = sum(1 for r in node_results if not r.success and not r.skipped)
        skipped_nodes = sum(1 for r in node_results if r.skipped)

        temporalio.workflow.logger.info(
            "DAGOrchestratorWorkflow completed",
            total_nodes=len(node_results),
            successful_nodes=successful_nodes,
            failed_nodes=failed_nodes,
            skipped_nodes=skipped_nodes,
            duration_seconds=duration_seconds,
            **inputs.properties_to_log,
        )

        return ExecuteDAGResult(
            dag_id=inputs.dag_id,
            scheduled_nodes=len(node_results),
            successful_nodes=successful_nodes,
            failed_nodes=failed_nodes,
            skipped_nodes=skipped_nodes,
            duration_seconds=duration_seconds,
            node_results=node_results,
        )
