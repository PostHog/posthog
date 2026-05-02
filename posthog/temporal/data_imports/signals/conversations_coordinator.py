"""Coordinator workflow for emitting signals from Conversations tickets.

Runs on a Temporal schedule (hourly). For each team with Conversations signals enabled,
spawns a child workflow that fetches eligible tickets and runs them through the signal pipeline.
"""

import json
import dataclasses
from datetime import timedelta
from typing import Any

import structlog
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
    return [
        team_id
        async for team_id in SignalSourceConfig.objects.filter(
            source_product=SignalSourceConfig.SourceProduct.CONVERSATIONS,
            source_type=SignalSourceConfig.SourceType.TICKET,
            enabled=True,
            # Tiny bit paranoid, as signals enabled should require AI consent by design
            team__organization__is_ai_data_processing_approved=True,
        ).values_list("team_id", flat=True)
    ]


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
        try:
            team = await Team.objects.aget(id=inputs.team_id)
        except Team.DoesNotExist:
            log.warning("Team no longer exists, skipping")
            return {"status": "skipped", "reason": "team_deleted", "signals_emitted": 0}
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


@dataclasses.dataclass(frozen=True)
class CoordinatorState:
    """Resumable state for continue-as-new across batches."""

    remaining_team_ids: list[int] = dataclasses.field(default_factory=list)
    teams_succeeded: int = 0
    teams_failed: int = 0
    total_signals_emitted: int = 0


_DEFAULT_STATE = CoordinatorState()


@workflow.defn(name="conversations-signals-coordinator")
class ConversationsSignalsCoordinatorWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CoordinatorState:
        if not inputs:
            return CoordinatorState()
        loaded = json.loads(inputs[0])
        return CoordinatorState(**loaded)

    @workflow.run
    async def run(self, state: CoordinatorState = _DEFAULT_STATE) -> dict[str, Any]:
        remaining = list(state.remaining_team_ids)
        teams_succeeded = state.teams_succeeded
        teams_failed = state.teams_failed
        total_signals_emitted = state.total_signals_emitted
        # Discover teams unless resuming from continue-as-new
        if not remaining:
            remaining = await workflow.execute_activity(
                get_conversations_signals_enabled_teams_activity,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=10),
                ),
            )
        if not remaining:
            logger.debug("No teams with conversations signals enabled")
            return {
                "teams_processed": teams_succeeded + teams_failed,
                "teams_succeeded": teams_succeeded,
                "teams_failed": teams_failed,
                "total_signals_emitted": total_signals_emitted,
            }
        logger.debug(
            "Processing teams with conversations signals enabled",
            team_count=len(remaining),
        )
        # Process teams in batches to avoid overwhelming Temporal with too many concurrent child workflows
        while remaining:
            batch = remaining[:DEFAULT_MAX_CONCURRENT_TEAMS]
            remaining = remaining[DEFAULT_MAX_CONCURRENT_TEAMS:]
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
                    logger.exception(
                        "Failed to start conversations signal emission for team",
                        team_id=team_id,
                    )
                    teams_failed += 1
            for team_id, handle in workflow_handles.items():
                try:
                    result = await handle
                    if isinstance(result, dict):
                        total_signals_emitted += result.get("signals_emitted", 0)
                    teams_succeeded += 1
                except Exception:
                    logger.exception(
                        "Conversations signal emission errored for team",
                        team_id=team_id,
                    )
                    teams_failed += 1
            # Avoid exceeding Temporal history limits on large rollouts
            if remaining and workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(
                    CoordinatorState(
                        remaining_team_ids=remaining,
                        teams_succeeded=teams_succeeded,
                        teams_failed=teams_failed,
                        total_signals_emitted=total_signals_emitted,
                    )
                )
        return {
            "teams_processed": teams_succeeded + teams_failed,
            "teams_succeeded": teams_succeeded,
            "teams_failed": teams_failed,
            "total_signals_emitted": total_signals_emitted,
        }
