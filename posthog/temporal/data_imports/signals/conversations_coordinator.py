"""Coordinator workflow for emitting signals from Conversations tickets.

Runs on a Temporal schedule (hourly). For each team with Conversations signals enabled,
spawns a child workflow that fetches eligible tickets and runs them through the signal pipeline.
"""

import json
import dataclasses
from datetime import timedelta
from typing import Any

import structlog
import posthoganalytics
import temporalio.exceptions
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater
from posthog.temporal.data_imports.signals import InternalSourceType, get_signal_config
from posthog.temporal.data_imports.signals.pipeline import run_signal_pipeline

from products.signals.backend.models import SignalSourceConfig

logger = structlog.get_logger(__name__)

# Max concurrent per-team child workflows
DEFAULT_MAX_CONCURRENT_TEAMS = 50

CONVERSATIONS_SOURCE_TYPE = InternalSourceType.CONVERSATIONS
CONVERSATIONS_SCHEMA_NAME = "tickets"


@dataclasses.dataclass(frozen=True)
class EmitConversationsSignalsInputs:
    team_id: int

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "source_type": CONVERSATIONS_SOURCE_TYPE,
            "schema_name": CONVERSATIONS_SCHEMA_NAME,
        }


@activity.defn
async def get_conversations_signals_enabled_teams_activity() -> list[int]:
    """Get team IDs with conversations signals enabled and AI consent."""
    enabled_team_ids: list[int] = []
    # Tiny bit paranoid, as signals enabled should require AI consent by design
    async for config in (
        SignalSourceConfig.objects.filter(
            source_product=SignalSourceConfig.SourceProduct.CONVERSATIONS,
            source_type=SignalSourceConfig.SourceType.TICKET,
            enabled=True,
        )
        .select_related("team__organization")
        .only("team_id", "team__organization__is_ai_data_processing_approved")
    ):
        team = await database_sync_to_async(lambda c: c.team)(config)
        org = await database_sync_to_async(lambda t: t.organization)(team)
        if org.is_ai_data_processing_approved:
            enabled_team_ids.append(config.team_id)
    return enabled_team_ids


@activity.defn
async def emit_conversations_signals_activity(inputs: EmitConversationsSignalsInputs) -> dict[str, Any]:
    """Emit signals for a single team's conversation tickets."""
    log = logger.bind(signals_type="conversations-signals", **inputs.properties_to_log)
    log.info("Starting conversations signal emission")
    config = get_signal_config(CONVERSATIONS_SOURCE_TYPE, CONVERSATIONS_SCHEMA_NAME)
    if config is None:
        log.warning("No signal config registered for conversations/tickets")
        return {"status": "skipped", "reason": "no_config_registered", "signals_emitted": 0}
    async with Heartbeater():
        team = await Team.objects.aget(id=inputs.team_id)
        records = await database_sync_to_async(config.record_fetcher, thread_sensitive=False)(team, config, {})
        return await run_signal_pipeline(
            team=team,
            config=config,
            records=records,
            extra=inputs.properties_to_log,
        )


@workflow.defn(name="emit-conversations-signals")
class EmitConversationsSignalsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitConversationsSignalsInputs:
        loaded = json.loads(inputs[0])
        return EmitConversationsSignalsInputs(**loaded)

    @workflow.run
    async def run(self, inputs: EmitConversationsSignalsInputs) -> dict[str, Any]:
        return await workflow.execute_activity(
            emit_conversations_signals_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


@workflow.defn(name="conversations-signals-coordinator")
class ConversationsSignalsCoordinatorWorkflow(PostHogWorkflow):
    @workflow.run
    async def run(self) -> dict[str, Any]:
        # Pick teams to emit new conversations from
        enabled_team_ids: list[int] = await workflow.execute_activity(
            get_conversations_signals_enabled_teams_activity,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
            ),
        )
        if not enabled_team_ids:
            workflow.logger.debug("No teams with conversations signals enabled")
            return {
                "teams_processed": 0,
                "teams_succeeded": 0,
                "teams_failed": 0,
                "total_signals_emitted": 0,
            }
        workflow.logger.debug(f"Processing {len(enabled_team_ids)} teams with conversations signals enabled")
        total_signals_emitted = 0
        failed_teams: set[int] = set()
        successful_teams: set[int] = set()
        for batch_start in range(0, len(enabled_team_ids), DEFAULT_MAX_CONCURRENT_TEAMS):
            batch = enabled_team_ids[batch_start : batch_start + DEFAULT_MAX_CONCURRENT_TEAMS]
            workflow_handles: dict[int, Any] = {}
            for team_id in batch:
                try:
                    handle = await workflow.start_child_workflow(
                        EmitConversationsSignalsWorkflow.run,
                        EmitConversationsSignalsInputs(team_id=team_id),
                        id=f"emit-conversations-signals-team-{team_id}",
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        execution_timeout=timedelta(hours=1),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=30),
                            maximum_interval=timedelta(minutes=5),
                        ),
                        parent_close_policy=workflow.ParentClosePolicy.REQUEST_CANCEL,
                    )
                    workflow_handles[team_id] = handle
                except temporalio.exceptions.WorkflowAlreadyStartedError:
                    continue
                except Exception:
                    workflow.logger.exception(f"Failed to start conversations signal emission for team {team_id}")
                    posthoganalytics.capture_exception(properties={"team_id": team_id})
                    failed_teams.add(team_id)
            for team_id, handle in workflow_handles.items():
                try:
                    result = await handle
                    if isinstance(result, dict):
                        total_signals_emitted += result.get("signals_emitted", 0)
                    successful_teams.add(team_id)
                except Exception:
                    workflow.logger.exception(f"Conversations signal emission errored for team {team_id}")
                    posthoganalytics.capture_exception(properties={"team_id": team_id})
                    failed_teams.add(team_id)
        return {
            "teams_processed": len(enabled_team_ids),
            "teams_succeeded": len(successful_teams),
            "teams_failed": len(failed_teams),
            "failed_team_ids": list(failed_teams),
            "total_signals_emitted": total_signals_emitted,
        }
