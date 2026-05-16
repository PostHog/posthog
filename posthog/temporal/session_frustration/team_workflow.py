"""Per-team workflow for session frustration detection."""

import json
from datetime import timedelta

import temporalio
import temporalio.exceptions
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.session_frustration.types import TeamWorkflowInputs, TeamWorkflowResult


@temporalio.workflow.defn(name="session-frustration-detection-team")
class SessionFrustrationTeamWorkflow(PostHogWorkflow):
    """Detect frustrated sessions for a single team and emit events."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TeamWorkflowInputs:
        loaded = json.loads(inputs[0])
        return TeamWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: TeamWorkflowInputs) -> TeamWorkflowResult:
        from posthog.temporal.session_frustration.activities import (
            emit_frustration_events_activity,
            filter_already_emitted_activity,
            query_frustrated_sessions_activity,
        )

        retry_policy = RetryPolicy(
            maximum_attempts=3,
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
        )

        # Step 1: Query ClickHouse for frustrated sessions
        sessions = await workflow.execute_activity(
            query_frustrated_sessions_activity,
            inputs,
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=retry_policy,
        )

        if not sessions:
            return TeamWorkflowResult()

        # Step 2: Filter already emitted (Redis dedup)
        new_sessions = await workflow.execute_activity(
            filter_already_emitted_activity,
            args=[inputs.team_id, sessions],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        if not new_sessions:
            return TeamWorkflowResult(
                sessions_queried=len(sessions),
                sessions_deduped=len(sessions),
            )

        # Step 3: Emit events
        events_emitted = await workflow.execute_activity(
            emit_frustration_events_activity,
            args=[inputs.team_id, inputs.api_token, new_sessions],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=retry_policy,
        )

        return TeamWorkflowResult(
            events_emitted=events_emitted,
            sessions_queried=len(sessions),
            sessions_deduped=len(sessions) - len(new_sessions),
        )
