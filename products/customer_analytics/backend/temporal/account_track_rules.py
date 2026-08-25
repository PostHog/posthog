from __future__ import annotations

import json
import asyncio
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from datetime import timedelta

    import structlog

    from posthog.dataclasses import frozen
    from posthog.exceptions_capture import capture_exception
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.customer_analytics.backend.logic.account_track_rules import (
        fail_account_track_rule_run,
        process_next_account_track_rule_batch,
    )

ACCOUNT_TRACK_RULE_WORKFLOW_NAME = "customer-analytics-account-track-rule-evaluation"

logger = structlog.get_logger(__name__)


@frozen
class AccountTrackRuleEvaluationInput:
    team_id: int
    run_id: str
    config_version: int


@frozen
class AccountTrackRuleEvaluationOutput:
    status: str
    processed: int


def account_track_rule_workflow_id(team_id: int) -> str:
    return f"customer-analytics-account-track-rules-{team_id}"


@activity.defn
async def account_track_rule_process_batch_activity(
    input: AccountTrackRuleEvaluationInput,
) -> AccountTrackRuleEvaluationOutput:
    try:
        async with Heartbeater():
            result = await database_sync_to_async(process_next_account_track_rule_batch, thread_sensitive=False)(
                input.team_id, UUID(input.run_id)
            )
        return AccountTrackRuleEvaluationOutput(status=result.status, processed=result.processed)
    except Exception as error:
        logger.error(  # noqa: TRY400 — exception text can contain rule values
            "account_track_rule_batch_failed",
            team_id=input.team_id,
            run_id=input.run_id,
            config_version=input.config_version,
            exception_type=type(error).__name__,
        )
        capture_exception(
            error,
            {
                "team_id": input.team_id,
                "run_id": input.run_id,
                "config_version": input.config_version,
                "stage": "process_batch",
            },
        )
        raise


@activity.defn
async def account_track_rule_fail_run_activity(input: AccountTrackRuleEvaluationInput) -> None:
    await database_sync_to_async(fail_account_track_rule_run, thread_sensitive=False)(input.team_id, UUID(input.run_id))


@workflow.defn(name=ACCOUNT_TRACK_RULE_WORKFLOW_NAME)
class AccountTrackRuleEvaluationWorkflow:
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountTrackRuleEvaluationInput:
        return AccountTrackRuleEvaluationInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: AccountTrackRuleEvaluationInput) -> AccountTrackRuleEvaluationOutput:
        try:
            while True:
                result = await workflow.execute_activity(
                    account_track_rule_process_batch_activity,
                    input,
                    start_to_close_timeout=timedelta(minutes=10),
                    heartbeat_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
                )
                if result.status not in {"pending", "running"}:
                    return result
        except asyncio.CancelledError:
            await workflow.execute_activity(
                account_track_rule_fail_run_activity,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
        except Exception:
            await workflow.execute_activity(
                account_track_rule_fail_run_activity,
                input,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
