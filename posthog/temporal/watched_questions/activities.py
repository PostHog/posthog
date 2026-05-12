import datetime as dt

import structlog
import temporalio.activity
from asgiref.sync import sync_to_async

from products.posthog_ai.backend.models import TrackedQuestion, TrackedQuestionRun
from products.posthog_ai.backend.services.conversation_fork import fork_conversation_for_drift_check
from products.posthog_ai.backend.services.drift_judge import judge_drift as judge_drift_service
from products.posthog_ai.backend.services.scheduling import compute_next_run_at
from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalSourceConfig

from .types import (
    CheckWatchedQuestionInputs,
    EmitDriftSignalActivityInputs,
    EmitDriftSignalActivityResult,
    ForkConversationActivityInputs,
    ForkConversationActivityResult,
    JudgeDriftActivityInputs,
    JudgeDriftActivityResult,
    PersistRunActivityInputs,
    RetrievedTrackedQuestion,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn(name="retrieve_due_watched_questions")
async def retrieve_due_watched_questions() -> list[RetrievedTrackedQuestion]:
    @sync_to_async
    def _load() -> list[RetrievedTrackedQuestion]:
        now = dt.datetime.now(tz=dt.UTC)
        rows = list(
            TrackedQuestion.objects.filter(
                status=TrackedQuestion.Status.ACTIVE,
                next_run_at__lte=now,
            )
            .order_by("next_run_at")
            .values_list("id", "team_id")[:200]
        )
        return [RetrievedTrackedQuestion(tracked_question_id=str(rid), team_id=team_id) for rid, team_id in rows]

    return await _load()


@temporalio.activity.defn(name="fork_conversation_activity")
async def fork_conversation_activity(inputs: ForkConversationActivityInputs) -> ForkConversationActivityResult:
    result = await fork_conversation_for_drift_check(inputs.tracked_question_id)
    return ForkConversationActivityResult(
        forked_conversation_id=result.forked_conversation_id,
        narrative=result.narrative,
        query_kind=result.query_kind,
    )


@temporalio.activity.defn(name="judge_drift_activity")
async def judge_drift_activity(inputs: JudgeDriftActivityInputs) -> JudgeDriftActivityResult:
    @sync_to_async
    def _judge() -> JudgeDriftActivityResult:
        verdict = judge_drift_service(inputs.narrative)
        return JudgeDriftActivityResult(
            drift_detected=verdict.drift_detected,
            severity=verdict.severity,
            summary=verdict.summary,
            payload=verdict.payload,
        )

    return await _judge()


def _render_signal_description(
    *,
    tracked_question: TrackedQuestion,
    forked_conversation_id: str,
    narrative: str,
    severity: str,
    judge_summary: str,
) -> str:
    baseline_date = tracked_question.baseline_captured_at.strftime("%Y-%m-%d")
    return (
        f"PostHog AI watched-question drift — {tracked_question.title}\n\n"
        f"User question (asked {baseline_date}):\n"
        f'  "{tracked_question.question_text}"\n\n'
        f"Judge verdict: {severity} drift detected — {judge_summary}\n\n"
        "Max's full comparison:\n\n"
        f"{narrative}\n\n"
        f"Conversation: /project/{tracked_question.team_id}/max/conversations/"
        f"{tracked_question.source_conversation_id}#{tracked_question.source_visualization_message_id}\n"
        f"Forked drift conversation: /project/{tracked_question.team_id}/max/conversations/{forked_conversation_id}\n\n"
        "Investigate: identify the most likely root cause for this material change and open a PR "
        "with either (a) a code/config fix if a deploy is implicated, or (b) a documented "
        "annotation update if the drift is expected."
    )


@temporalio.activity.defn(name="emit_drift_signal_activity")
async def emit_drift_signal_activity(inputs: EmitDriftSignalActivityInputs) -> EmitDriftSignalActivityResult:
    tracked_question = await sync_to_async(TrackedQuestion.objects.select_related("team", "source_conversation").get)(
        id=inputs.tracked_question_id
    )
    team = tracked_question.team

    weight = 0.9 if inputs.severity == "significant" else 0.6
    signal_source_id = f"{tracked_question.id}:{inputs.forked_conversation_id}"
    description = _render_signal_description(
        tracked_question=tracked_question,
        forked_conversation_id=inputs.forked_conversation_id,
        narrative=inputs.narrative,
        severity=inputs.severity,
        judge_summary=inputs.judge_summary,
    )
    extra: dict[str, object] = {
        "tracked_question_id": str(tracked_question.id),
        "source_conversation_id": str(tracked_question.source_conversation_id),
        "forked_conversation_id": inputs.forked_conversation_id,
        "source_human_message_id": str(tracked_question.source_human_message_id),
        "source_visualization_message_id": str(tracked_question.source_visualization_message_id),
        "query_kind": inputs.query_kind or "AssistantTrendsQuery",
        "cadence": tracked_question.cadence,
        "severity": inputs.severity,
        "baseline_captured_at": tracked_question.baseline_captured_at.isoformat(),
        "judge_summary": inputs.judge_summary,
        "repository": tracked_question.repository or None,
    }

    # Make sure the source config is still enabled — guards against a user toggling it off
    # mid-cadence.
    enabled = await sync_to_async(SignalSourceConfig.is_source_enabled)(
        team.id,
        SignalSourceConfig.SourceProduct.POSTHOG_AI,
        SignalSourceConfig.SourceType.QUESTION_DRIFT,
    )
    if not enabled:
        logger.info(
            "Skipping drift signal: source disabled for team.",
            team_id=team.id,
            tracked_question_id=str(tracked_question.id),
        )
        return EmitDriftSignalActivityResult(signal_emitted_at=None, signal_source_id=signal_source_id)

    await emit_signal(
        team=team,
        source_product=SignalSourceConfig.SourceProduct.POSTHOG_AI,
        source_type=SignalSourceConfig.SourceType.QUESTION_DRIFT,
        source_id=signal_source_id,
        description=description,
        weight=weight,
        extra=extra,
    )
    return EmitDriftSignalActivityResult(
        signal_emitted_at=dt.datetime.now(tz=dt.UTC), signal_source_id=signal_source_id
    )


@temporalio.activity.defn(name="persist_watched_question_run_activity")
async def persist_run_and_advance_activity(inputs: PersistRunActivityInputs) -> None:
    @sync_to_async
    def _persist() -> None:
        tracked_question = TrackedQuestion.objects.select_related("team").get(id=inputs.tracked_question_id)
        now = dt.datetime.now(tz=dt.UTC)
        TrackedQuestionRun.objects.create(
            team=tracked_question.team,
            tracked_question=tracked_question,
            forked_conversation_id=inputs.forked_conversation_id,
            state=inputs.state,
            severity=inputs.severity,
            narrative=inputs.narrative,
            judge_summary=inputs.judge_summary,
            judge_payload=inputs.judge_payload,
            error=inputs.error,
            signal_emitted_at=inputs.signal_emitted_at,
            signal_source_id=inputs.signal_source_id,
        )
        tracked_question.last_run_at = now
        tracked_question.next_run_at = compute_next_run_at(
            cadence=tracked_question.cadence, anchor=now, team=tracked_question.team
        )
        tracked_question.save(update_fields=["last_run_at", "next_run_at", "updated_at"])

    await _persist()


WATCHED_QUESTION_ACTIVITIES = [
    retrieve_due_watched_questions,
    fork_conversation_activity,
    judge_drift_activity,
    emit_drift_signal_activity,
    persist_run_and_advance_activity,
]


# Re-export inputs for convenience when scheduling from the API layer.
__all__ = [
    "CheckWatchedQuestionInputs",
    "WATCHED_QUESTION_ACTIVITIES",
    "emit_drift_signal_activity",
    "fork_conversation_activity",
    "judge_drift_activity",
    "persist_run_and_advance_activity",
    "retrieve_due_watched_questions",
]
