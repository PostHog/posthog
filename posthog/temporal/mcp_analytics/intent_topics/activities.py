"""Thin Temporal activities over the intent topics runs in the mcp_analytics facade."""

from datetime import UTC, datetime

import structlog
from temporalio import activity

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.mcp_analytics.intent_topics.constants import ASSIGN_OVERLAP, ASSIGN_WINDOW, REFIT_REASSIGN_WINDOW
from posthog.temporal.mcp_analytics.intent_topics.models import IntentTopicsRunResult, IntentTopicsWorkflowInputs

from products.mcp_analytics.backend.facade import api as mcp_analytics_api
from products.mcp_analytics.backend.facade.contracts import IntentTopicsRunOutcome

logger = structlog.get_logger(__name__)


def _now(inputs: IntentTopicsWorkflowInputs) -> datetime:
    return datetime.fromisoformat(inputs.now) if inputs.now else datetime.now(tz=UTC)


def _result(team_id: int, outcome: IntentTopicsRunOutcome) -> IntentTopicsRunResult:
    return IntentTopicsRunResult(
        team_id=team_id,
        kind=outcome.kind,
        status=outcome.status,
        run_id=outcome.run_id,
        n_intents=outcome.n_intents,
        n_topics=outcome.n_topics,
        n_outliers=outcome.n_outliers,
        n_embeddings_requested=outcome.n_embeddings_requested,
        error_message=outcome.error_message,
    )


@database_sync_to_async_pool
def _run_sync(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    with team_scope(inputs.team_id):
        team = Team.objects.get(pk=inputs.team_id)
        now = _now(inputs)
        return _result(team.pk, mcp_analytics_api.sync_intent_topic_embeddings(team, now=now))


@database_sync_to_async_pool
def _run_assign(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    with team_scope(inputs.team_id):
        team = Team.objects.get(pk=inputs.team_id)
        now = _now(inputs)
        return _result(
            team.pk,
            mcp_analytics_api.assign_intent_topics(
                team, window_start=now - ASSIGN_WINDOW - ASSIGN_OVERLAP, window_end=now
            ),
        )


@database_sync_to_async_pool
def _run_refit(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    with team_scope(inputs.team_id):
        team = Team.objects.get(pk=inputs.team_id)
        return _result(team.pk, mcp_analytics_api.refit_intent_topics(team, now=_now(inputs)))


@database_sync_to_async_pool
def _run_reassign_after_refit(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    with team_scope(inputs.team_id):
        team = Team.objects.get(pk=inputs.team_id)
        now = _now(inputs)
        return _result(
            team.pk,
            mcp_analytics_api.assign_intent_topics(team, window_start=now - REFIT_REASSIGN_WINDOW, window_end=now),
        )


@activity.defn
async def sync_intent_embeddings_activity(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    async with Heartbeater():
        return await _run_sync(inputs)


@activity.defn
async def assign_intent_topics_activity(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    async with Heartbeater():
        return await _run_assign(inputs)


@activity.defn
async def refit_intent_topics_activity(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    async with Heartbeater():
        return await _run_refit(inputs)


@activity.defn
async def reassign_after_refit_activity(inputs: IntentTopicsWorkflowInputs) -> IntentTopicsRunResult:
    async with Heartbeater():
        return await _run_reassign_after_refit(inputs)
