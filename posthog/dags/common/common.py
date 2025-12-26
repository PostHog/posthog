from contextlib import suppress
from enum import Enum
from typing import Optional

import dagster

from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import DagsterTags


class JobOwners(str, Enum):
    TEAM_ANALYTICS_PLATFORM = "team-analytics-platform"
    TEAM_CLICKHOUSE = "team-clickhouse"
    TEAM_DATA_STACK = "team-data-stack"
    TEAM_ERROR_TRACKING = "team-error-tracking"
    TEAM_EXPERIMENTS = "team-experiments"
    TEAM_GROWTH = "team-growth"
    TEAM_INGESTION = "team-ingestion"
    TEAM_LLM_ANALYTICS = "team-llm-analytics"
    TEAM_POSTHOG_AI = "team-posthog-ai"
    TEAM_REVENUE_ANALYTICS = "team-revenue-analytics"
    TEAM_WEB_ANALYTICS = "team-web-analytics"


def dagster_tags(
    context: dagster.OpExecutionContext | dagster.AssetCheckExecutionContext | dagster.AssetExecutionContext,
) -> DagsterTags:
    tags = DagsterTags()
    with suppress(Exception):
        r = context.run
        tags = DagsterTags(
            job_name=r.job_name,
            run_id=r.run_id,
            tags=r.tags,
            root_run_id=r.root_run_id,
            parent_run_id=r.parent_run_id,
            job_snapshot_id=r.job_snapshot_id,
            execution_plan_snapshot_id=r.execution_plan_snapshot_id,
        )

    with suppress(Exception):
        if isinstance(context, dagster.AssetCheckExecutionContext):
            op = context.op_execution_context
            if op and op.op:
                tags.op_name = op.op.name
        elif isinstance(context, dagster.OpExecutionContext):
            if context.op:
                tags.op_name = context.op.name
        elif isinstance(context, dagster.AssetExecutionContext):
            if context.asset_key:
                tags.asset_key = context.asset_key.to_user_string()

    return tags


def settings_with_log_comment(
    context: dagster.OpExecutionContext | dagster.AssetExecutionContext | dagster.AssetCheckExecutionContext,
) -> dict[str, str]:
    qt = query_tagging.get_query_tags()
    qt.with_dagster(dagster_tags(context))
    return {"log_comment": qt.to_json()}


def check_for_concurrent_runs(
    context: dagster.ScheduleEvaluationContext, tags: dict[str, str]
) -> Optional[dagster.SkipReason]:
    # Get the schedule name from the context
    schedule_name = context._schedule_name
    if schedule_name is None:
        context.log.info("Skipping concurrent runs check because schedule name is not available")
        return None

    # Get the schedule definition from the repository to find the associated job
    schedule_def = context.repository_def.get_schedule_def(schedule_name)
    job_name = schedule_def.job_name

    run_records = context.instance.get_run_records(
        dagster.RunsFilter(
            job_name=job_name,
            tags=tags,
            statuses=[
                dagster.DagsterRunStatus.QUEUED,
                dagster.DagsterRunStatus.NOT_STARTED,
                dagster.DagsterRunStatus.STARTING,
                dagster.DagsterRunStatus.STARTED,
            ],
        )
    )

    if len(run_records) > 0:
        context.log.info(f"Skipping {job_name} due to {len(run_records)} active run(s)")
        return dagster.SkipReason(f"Skipping {job_name} run because another run of the same job is already active")

    return None
