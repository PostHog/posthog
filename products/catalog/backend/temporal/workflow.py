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

from products.catalog.backend.temporal.activities.enumerate import (
    CatalogNodeRef,
    enumerate_posthog_tables,
    enumerate_saved_queries,
    enumerate_system_tables,
    enumerate_warehouse_tables,
)
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
    BATCH_SIZE,
    DEFAULT_RETRY_POLICY,
    ENUMERATE_ACTIVITY_TIMEOUT,
    ENUMERATE_HEARTBEAT_TIMEOUT,
    ENUMERATE_SCHEDULE_TO_CLOSE_TIMEOUT,
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


@workflow.defn(name=WORKFLOW_NAME)
class CatalogTraversalWorkflow(PostHogWorkflow):
    """One full pass over a team's catalog.

    Current shape: open a run row, enumerate warehouse / saved query / system /
    posthog tables, upsert their nodes and columns, close the run row. The
    agentic phase appends to this `run` body in a later iteration — no second
    workflow.
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
                enumerate_system_tables,
                enumerate_posthog_tables,
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

            # --- Relationship declaration lands in commit 4 ---
            # --- Agentic phase activities follow in a later iteration ---

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
        )
