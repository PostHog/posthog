import json
from datetime import timedelta
from typing import Any

from temporalio import common, workflow

from posthog.temporal.backfill_group_type_created_at.activities import (
    apply_group_type_created_at_backfill,
    plan_group_type_created_at_backfill,
)
from posthog.temporal.backfill_group_type_created_at.types import (
    ApplyBackfillInput,
    BackfillGroupTypeCreatedAtInput,
    PlanBackfillInput,
)
from posthog.temporal.common.base import PostHogWorkflow


@workflow.defn(name="backfill-group-type-created-at")
class BackfillGroupTypeCreatedAtWorkflow(PostHogWorkflow):
    """Recompute posthog_grouptypemapping.created_at from the earliest event per group.

    Imported historical events get masked in HogQL because the group type mapping's
    created_at postdates them. This workflow lowers created_at to the earliest event
    actually carrying each group, unblocking insights and dashboards.
    Supports dry_run to preview the planned changes without writing.

    Ingestion self-heals this on its own now: insertGroupType lowers an existing mapping's
    created_at with LEAST on re-ingest (see nodejs postgres-group-repository.ts), so a
    historical import that re-registers a group type walks the floor back without staff help.
    This workflow stays as the staff remediation for cases ingestion can't reach — most of
    all because it writes created_at via raw SQL against the persons DB, so it keeps working
    while the admin edit path is degraded (the personhog migration dropped created_at from the
    mapping update RPC).

    The floor it can reach is hard: the plan reads `minIf(timestamp, notEmpty($group_N))`, the
    earliest event that actually carries each group. A customer whose original import never set
    `$groups` on its events has no such timestamp to walk back to, so a backfill run skips those
    mappings ("no events carry this group") and the fix is a re-import that sets $groups, not a
    backfill.
    """

    @staticmethod
    def parse_inputs(input: list[str]) -> BackfillGroupTypeCreatedAtInput:
        loaded = json.loads(input[0])
        return BackfillGroupTypeCreatedAtInput(**loaded)

    @workflow.run
    async def run(self, input: BackfillGroupTypeCreatedAtInput) -> dict:
        plan = await workflow.execute_activity(
            plan_group_type_created_at_backfill,
            PlanBackfillInput(team_id=input.team_id),
            # The ClickHouse min() scans the project's events; give it room.
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=common.RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=30),
                # A missing team is fatal — don't retry it (matched by class name).
                non_retryable_error_types=["BackfillGroupTypeCreatedAtError"],
            ),
        )

        result: dict[str, Any] = {
            "team_id": input.team_id,
            "project_id": plan["project_id"],
            "dry_run": input.dry_run,
            "updates": plan["updates"],
            "skipped": plan["skipped"],
            "updated": 0,
        }

        if input.dry_run:
            workflow.logger.info(
                f"DRY RUN: would backfill created_at for {len(plan['updates'])} group type mappings "
                f"in project {plan['project_id']}: {plan['updates']}"
            )
            return result

        if not plan["updates"]:
            workflow.logger.info(f"No group type mappings need created_at backfill in project {plan['project_id']}")
            return result

        apply_result = await workflow.execute_activity(
            apply_group_type_created_at_backfill,
            ApplyBackfillInput(project_id=plan["project_id"], updates=plan["updates"]),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
        )
        result["updated"] = apply_result["updated"]

        workflow.logger.info(
            f"Backfilled created_at for {apply_result['updated']} group type mappings in project {plan['project_id']}"
        )
        return result
