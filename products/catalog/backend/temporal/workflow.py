"""The catalog traversal workflow.

Single workflow that owns one pass over a team's catalog. Phase 1
(deterministic) is implemented here; Phase 2 (agentic LLM enrichment) will
append activities after the deterministic phase before `complete_traversal_run`
in a follow-up.

Workflow ID is `f"catalog-traversal-{team_id}"` so signal-triggered runs
debounce naturally via `WorkflowIDReusePolicy.REJECT_DUPLICATE` (added when
the trigger wiring lands) — no Redis lock needed.
"""

from dataclasses import dataclass
from itertools import batched

from temporalio import workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.catalog.backend.temporal.activities.agent import (
    count_descriptions_for_run,
    spawn_catalog_agent_task,
    wait_for_task_run_completion,
)
from products.catalog.backend.temporal.activities.enumerate import (
    CatalogNodeRef,
    enumerate_saved_queries,
    enumerate_warehouse_tables,
)
from products.catalog.backend.temporal.activities.metric_proposal import (
    count_metrics_for_run,
    spawn_catalog_metric_proposal_task,
)
from products.catalog.backend.temporal.activities.propose import propose_saved_query_lineage, propose_warehouse_joins
from products.catalog.backend.temporal.activities.run import (
    CompleteRunArgs,
    CreateRunArgs,
    FailRunArgs,
    TraversalCounts,
    complete_traversal_run,
    create_traversal_run,
    fail_traversal_run,
)
from products.catalog.backend.temporal.activities.upsert import UpsertNodeBatchArgs, upsert_node_batch
from products.catalog.backend.temporal.constants import (
    AGENT_METRIC_SPAWN_ACTIVITY_TIMEOUT,
    AGENT_METRIC_WAIT_ACTIVITY_TIMEOUT,
    AGENT_METRIC_WAIT_HEARTBEAT_TIMEOUT,
    AGENT_SPAWN_ACTIVITY_TIMEOUT,
    AGENT_WAIT_ACTIVITY_TIMEOUT,
    AGENT_WAIT_HEARTBEAT_TIMEOUT,
    BATCH_SIZE,
    DEFAULT_RETRY_POLICY,
    ENUMERATE_ACTIVITY_TIMEOUT,
    ENUMERATE_HEARTBEAT_TIMEOUT,
    ENUMERATE_SCHEDULE_TO_CLOSE_TIMEOUT,
    PROPOSE_ACTIVITY_TIMEOUT,
    PROPOSE_HEARTBEAT_TIMEOUT,
    PROPOSE_SCHEDULE_TO_CLOSE_TIMEOUT,
    RUN_LIFECYCLE_ACTIVITY_TIMEOUT,
    RUN_LIFECYCLE_HEARTBEAT_TIMEOUT,
    RUN_LIFECYCLE_SCHEDULE_TO_CLOSE_TIMEOUT,
    UPSERT_ACTIVITY_TIMEOUT,
    UPSERT_HEARTBEAT_TIMEOUT,
    UPSERT_SCHEDULE_TO_CLOSE_TIMEOUT,
    WORKFLOW_NAME,
)


@dataclass
class CatalogTraversalInputs:
    team_id: int
    trigger: str = "manual"  # CatalogTraversalRun.Trigger value
    generator_model: str | None = None


@dataclass
class CatalogTraversalResult:
    run_id: str
    nodes: int = 0
    columns: int = 0
    relationships: int = 0
    descriptions: int = 0
    metrics: int = 0


@workflow.defn(name=WORKFLOW_NAME)
class CatalogTraversalWorkflow(PostHogWorkflow):
    """One full pass over a team's catalog.

    Current shape: open a run row, enumerate warehouse + saved-query tables,
    upsert their nodes and columns, close the run row. HogQL system tables
    and PostHog-native tables are exposed via the
    `system.tables` / `system.columns` / `system.relationships` UNION (see
    `posthog/hogql/database/schema/system_union.py`) and do not flow through
    this workflow. The agentic phase appends to this `run` body in a later
    iteration — no second workflow.
    """

    inputs_cls = CatalogTraversalInputs

    @workflow.run
    async def run(self, inputs: CatalogTraversalInputs) -> CatalogTraversalResult:
        run_id = await workflow.execute_activity(
            create_traversal_run,
            CreateRunArgs(
                team_id=inputs.team_id,
                trigger=inputs.trigger,
                generator_model=inputs.generator_model,
            ),
            start_to_close_timeout=RUN_LIFECYCLE_ACTIVITY_TIMEOUT,
            schedule_to_close_timeout=RUN_LIFECYCLE_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=RUN_LIFECYCLE_HEARTBEAT_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

        counts = TraversalCounts()
        try:
            # --- Deterministic phase ---
            # Walk each source, upsert its nodes + columns through the shared
            # upsert activity. Order is incidental — the upsert is idempotent
            # on the natural key (team, kind, name).
            for enumerator in (
                enumerate_warehouse_tables,
                enumerate_saved_queries,
            ):
                refs: list[CatalogNodeRef] = await workflow.execute_activity(
                    enumerator,
                    inputs.team_id,
                    start_to_close_timeout=ENUMERATE_ACTIVITY_TIMEOUT,
                    schedule_to_close_timeout=ENUMERATE_SCHEDULE_TO_CLOSE_TIMEOUT,
                    heartbeat_timeout=ENUMERATE_HEARTBEAT_TIMEOUT,
                    retry_policy=DEFAULT_RETRY_POLICY,
                )
                for batch in batched(refs, BATCH_SIZE):
                    batch_result = await workflow.execute_activity(
                        upsert_node_batch,
                        UpsertNodeBatchArgs(team_id=inputs.team_id, refs=list(batch)),
                        start_to_close_timeout=UPSERT_ACTIVITY_TIMEOUT,
                        schedule_to_close_timeout=UPSERT_SCHEDULE_TO_CLOSE_TIMEOUT,
                        heartbeat_timeout=UPSERT_HEARTBEAT_TIMEOUT,
                        retry_policy=DEFAULT_RETRY_POLICY,
                    )
                    counts.nodes += batch_result.nodes
                    counts.columns += batch_result.columns

            # --- Deterministic relationship declaration ---
            # Both activities use CatalogAPI.propose_relationship with
            # confidence=1.0, which the facade auto-accepts on first insert.
            # System-table FK edges are declared inline on each PostgresTable
            # (see `posthog/hogql/database/schema/system.py`) and exposed via
            # the `system.relationships` UNION — they do not need a Postgres
            # write.
            for propose_activity in (
                propose_warehouse_joins,
                propose_saved_query_lineage,
            ):
                counts.relationships += await workflow.execute_activity(
                    propose_activity,
                    inputs.team_id,
                    start_to_close_timeout=PROPOSE_ACTIVITY_TIMEOUT,
                    schedule_to_close_timeout=PROPOSE_SCHEDULE_TO_CLOSE_TIMEOUT,
                    heartbeat_timeout=PROPOSE_HEARTBEAT_TIMEOUT,
                    retry_policy=DEFAULT_RETRY_POLICY,
                )

            # --- Agentic phase: description pass ---
            # Spawn a cloud agent task in a sandbox. The agent reads the
            # catalog via HogQL (system.tables / system.columns /
            # system.relationships) and writes synthetic_description back via
            # the catalog-*-create MCP tools. We wait for it to finish so the
            # whole catalog pass is one logical workflow run.
            traversal_started_at = workflow.now().isoformat()
            task_run_id = await workflow.execute_activity(
                spawn_catalog_agent_task,
                inputs.team_id,
                start_to_close_timeout=AGENT_SPAWN_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            agent_status = await workflow.execute_activity(
                wait_for_task_run_completion,
                task_run_id,
                start_to_close_timeout=AGENT_WAIT_ACTIVITY_TIMEOUT,
                heartbeat_timeout=AGENT_WAIT_HEARTBEAT_TIMEOUT,
                # Stream subscription is idempotent (replays from start_id="0"),
                # so worker bounces shouldn't kill the whole catalog run.
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            if agent_status != "completed":
                raise RuntimeError(f"Catalog agent task ended in non-COMPLETED status: {agent_status}")
            counts.descriptions = await workflow.execute_activity(
                count_descriptions_for_run,
                args=[inputs.team_id, traversal_started_at],
                start_to_close_timeout=RUN_LIFECYCLE_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )

            # --- Agentic phase: metric-proposal pass ---
            # Runs after descriptions land so the metric agent can read them
            # while reasoning. It walks dashboards / insights / activity log /
            # app_metrics to surface AARRR-level metrics the team already
            # tracks, and writes each via catalog-metrics-create.
            # `wait_for_task_run_completion` is generic over agent passes; we
            # reuse the same activity used by the description pass above.
            metric_pass_started_at = workflow.now().isoformat()
            metric_task_run_id = await workflow.execute_activity(
                spawn_catalog_metric_proposal_task,
                inputs.team_id,
                start_to_close_timeout=AGENT_METRIC_SPAWN_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            metric_status = await workflow.execute_activity(
                wait_for_task_run_completion,
                metric_task_run_id,
                start_to_close_timeout=AGENT_METRIC_WAIT_ACTIVITY_TIMEOUT,
                heartbeat_timeout=AGENT_METRIC_WAIT_HEARTBEAT_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            if metric_status != "completed":
                raise RuntimeError(f"Catalog metric-proposal task ended in non-COMPLETED status: {metric_status}")
            counts.metrics = await workflow.execute_activity(
                count_metrics_for_run,
                args=[inputs.team_id, metric_pass_started_at],
                start_to_close_timeout=RUN_LIFECYCLE_ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )

            await workflow.execute_activity(
                complete_traversal_run,
                CompleteRunArgs(run_id=run_id, counts=counts),
                start_to_close_timeout=RUN_LIFECYCLE_ACTIVITY_TIMEOUT,
                schedule_to_close_timeout=RUN_LIFECYCLE_SCHEDULE_TO_CLOSE_TIMEOUT,
                heartbeat_timeout=RUN_LIFECYCLE_HEARTBEAT_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
        except Exception as exc:
            # Make the failure visible on the run row even if Temporal will
            # also retry the workflow. fail_traversal_run is idempotent.
            await workflow.execute_activity(
                fail_traversal_run,
                FailRunArgs(run_id=run_id, error=repr(exc)),
                start_to_close_timeout=RUN_LIFECYCLE_ACTIVITY_TIMEOUT,
                schedule_to_close_timeout=RUN_LIFECYCLE_SCHEDULE_TO_CLOSE_TIMEOUT,
                heartbeat_timeout=RUN_LIFECYCLE_HEARTBEAT_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            raise

        return CatalogTraversalResult(
            run_id=run_id,
            nodes=counts.nodes,
            columns=counts.columns,
            relationships=counts.relationships,
            descriptions=counts.descriptions,
            metrics=counts.metrics,
        )
