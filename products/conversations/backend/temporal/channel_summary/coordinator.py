from __future__ import annotations

import json

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from datetime import date, timedelta

    import structlog

    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater

    from products.conversations.backend.channel_summary_ids import build_channel_summary_workflow_id
    from products.conversations.backend.support_slack import get_support_slack_bot_token
    from products.conversations.backend.temporal.channel_summary.constants import (
        MAX_SUMMARIES_PER_RUN,
        MAX_SUMMARIES_PER_TEAM_PER_RUN,
    )
    from products.conversations.backend.temporal.channel_summary.schemas import (
        ChannelSummaryInput,
        CollectDueChannelsOutput,
        SummaryCoordinatorInput,
        SummaryCoordinatorOutput,
    )
    from products.conversations.backend.temporal.channel_summary.summarize import AccountChannelSummaryWorkflow
    from products.customer_analytics.backend.facade import api as customer_analytics

logger = structlog.get_logger(__name__)


def _collect_due_channels() -> list[ChannelSummaryInput]:
    """Ask customer_analytics who is due, then gate on what only conversations knows:
    the team must have the SupportHog bot configured (it reads the channel) and the
    org must have approved AI data processing (messages go to an LLM)."""
    due = customer_analytics.list_accounts_due_for_slack_summary()
    if not due:
        return []
    teams = Team.objects.select_related("organization").in_bulk({item.team_id for item in due})
    eligible: list[ChannelSummaryInput] = []
    per_team: dict[int, int] = {}
    for item in due:
        if len(eligible) >= MAX_SUMMARIES_PER_RUN:
            break
        if per_team.get(item.team_id, 0) >= MAX_SUMMARIES_PER_TEAM_PER_RUN:
            continue
        team = teams.get(item.team_id)
        if team is None or not team.organization.is_ai_data_processing_approved:
            continue
        if not get_support_slack_bot_token(team):
            continue
        per_team[item.team_id] = per_team.get(item.team_id, 0) + 1
        eligible.append(
            ChannelSummaryInput(
                team_id=item.team_id,
                account_id=item.account_id,
                account_name=item.account_name,
                slack_channel_id=item.slack_channel_id,
                cadence=item.cadence,
                period_start=item.period_start.isoformat(),
                period_end=item.period_end.isoformat(),
            )
        )
    return eligible


@activity.defn
async def summary_collect_due_channels_activity(_input: SummaryCoordinatorInput) -> CollectDueChannelsOutput:
    """Scan for account channels due a periodic summary, gated on team-level eligibility."""
    async with Heartbeater():
        due = await database_sync_to_async(_collect_due_channels, thread_sensitive=False)()
    logger.info("channel_summary coordinator: due channels", count=len(due))
    return CollectDueChannelsOutput(due=due)


@workflow.defn(name="account-channel-summary-coordinator")
class ChannelSummaryCoordinatorWorkflow:
    """Hourly coordinator: finds accounts due a channel summary and fans out one child
    workflow per due channel.

    Dispatch is fire-and-forget via ParentClosePolicy.ABANDON. Child ids are
    deterministic per (account, cadence, period), so overlapping ticks can't summarize
    the same period twice while a child is in flight, and the unique DB key backstops
    it after. ALLOW_DUPLICATE_FAILED_ONLY lets a later tick retry a period whose prior
    run failed (its row stays absent, so the account stays due).
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SummaryCoordinatorInput:
        if not inputs:
            return SummaryCoordinatorInput()
        return SummaryCoordinatorInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, _input: SummaryCoordinatorInput) -> SummaryCoordinatorOutput:
        result = await workflow.execute_activity(
            summary_collect_due_channels_activity,
            _input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        started = 0
        skipped = 0
        for item in result.due:
            child_id = build_channel_summary_workflow_id(
                account_id=item.account_id,
                cadence=item.cadence,
                period_start=date.fromisoformat(item.period_start[:10]),
            )
            try:
                await workflow.start_child_workflow(
                    AccountChannelSummaryWorkflow.run,
                    item,
                    id=child_id,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                started += 1
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "channel_summary coordinator: child already running",
                    extra={"child_id": child_id},
                )
                skipped += 1

        return SummaryCoordinatorOutput(due_count=len(result.due), started_count=started, skipped_count=skipped)
