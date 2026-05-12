import datetime as dt

import temporalio.common
import temporalio.workflow
import temporalio.exceptions

from posthog.temporal.common.base import PostHogWorkflow

from .retry_policy import DEFAULT_RETRY_POLICY, EMIT_SIGNAL_RETRY_POLICY, FORK_RETRY_POLICY, JUDGE_RETRY_POLICY
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


@temporalio.workflow.defn(name="schedule-due-watched-questions")
class ScheduleDueWatchedQuestionsWorkflow(PostHogWorkflow):
    """Hourly fan-out: pull all TrackedQuestions whose next_run_at has passed and spawn a
    child workflow per question. Mirrors `ScheduleDueAlertChecksWorkflow`."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @temporalio.workflow.run
    async def run(self) -> None:
        due: list[RetrievedTrackedQuestion] = await temporalio.workflow.execute_activity(
            "retrieve_due_watched_questions",
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=DEFAULT_RETRY_POLICY,
        )
        if not due:
            return

        # Deterministic child IDs prevent the sweep from starting a second concurrent check
        # for a question whose previous workflow has not yet completed (e.g. a manual
        # run_now spawned earlier). Temporal enforces ID uniqueness across open workflows.
        for question in due:
            try:
                await temporalio.workflow.execute_child_workflow(
                    CheckWatchedQuestionWorkflow.run,
                    CheckWatchedQuestionInputs(
                        tracked_question_id=question.tracked_question_id,
                        team_id=question.team_id,
                    ),
                    id=f"check-watched-question-{question.tracked_question_id}",
                    parent_close_policy=temporalio.workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(minutes=20),
                )
            except temporalio.exceptions.WorkflowAlreadyStartedError:
                # A prior check is still in flight — let it finish and skip this tick.
                continue


@temporalio.workflow.defn(name="check-watched-question")
class CheckWatchedQuestionWorkflow(PostHogWorkflow):
    """Per-question drift check: fork the conversation, judge the result, emit on drift."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> CheckWatchedQuestionInputs:
        import json

        if not inputs:
            raise ValueError("CheckWatchedQuestionWorkflow requires inputs")
        payload = json.loads(inputs[0])
        return CheckWatchedQuestionInputs(
            tracked_question_id=payload["tracked_question_id"],
            team_id=int(payload["team_id"]),
        )

    @temporalio.workflow.run
    async def run(self, inputs: CheckWatchedQuestionInputs) -> None:
        fork_result: ForkConversationActivityResult | None = None
        try:
            fork_result = await temporalio.workflow.execute_activity(
                "fork_conversation_activity",
                ForkConversationActivityInputs(tracked_question_id=inputs.tracked_question_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=FORK_RETRY_POLICY,
            )

            judge_result: JudgeDriftActivityResult = await temporalio.workflow.execute_activity(
                "judge_drift_activity",
                JudgeDriftActivityInputs(
                    tracked_question_id=inputs.tracked_question_id,
                    forked_conversation_id=fork_result.forked_conversation_id,
                    narrative=fork_result.narrative,
                ),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=JUDGE_RETRY_POLICY,
            )

            signal_emitted_at = None
            signal_source_id = ""
            run_state = "ok"
            severity = judge_result.severity

            if judge_result.drift_detected and judge_result.severity in ("moderate", "significant"):
                emit_result: EmitDriftSignalActivityResult = await temporalio.workflow.execute_activity(
                    "emit_drift_signal_activity",
                    EmitDriftSignalActivityInputs(
                        tracked_question_id=inputs.tracked_question_id,
                        forked_conversation_id=fork_result.forked_conversation_id,
                        narrative=fork_result.narrative,
                        query_kind=fork_result.query_kind,
                        severity=judge_result.severity,  # type: ignore[arg-type]
                        judge_summary=judge_result.summary,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=2),
                    retry_policy=EMIT_SIGNAL_RETRY_POLICY,
                )
                signal_emitted_at = emit_result.signal_emitted_at
                signal_source_id = emit_result.signal_source_id
                run_state = "drifted" if signal_emitted_at else "ok"

            await temporalio.workflow.execute_activity(
                "persist_watched_question_run_activity",
                PersistRunActivityInputs(
                    tracked_question_id=inputs.tracked_question_id,
                    state=run_state,  # type: ignore[arg-type]
                    severity=severity,  # type: ignore[arg-type]
                    forked_conversation_id=fork_result.forked_conversation_id,
                    narrative=fork_result.narrative,
                    judge_summary=judge_result.summary,
                    judge_payload=judge_result.payload,
                    signal_emitted_at=signal_emitted_at,
                    signal_source_id=signal_source_id,
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=DEFAULT_RETRY_POLICY,
            )

        except Exception as exc:
            await temporalio.workflow.execute_activity(
                "persist_watched_question_run_activity",
                PersistRunActivityInputs(
                    tracked_question_id=inputs.tracked_question_id,
                    state="error",
                    forked_conversation_id=fork_result.forked_conversation_id if fork_result else None,
                    narrative=fork_result.narrative if fork_result else "",
                    error=repr(exc)[:1000],
                ),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            raise


WATCHED_QUESTION_WORKFLOWS = [
    ScheduleDueWatchedQuestionsWorkflow,
    CheckWatchedQuestionWorkflow,
]


__all__ = [
    "CheckWatchedQuestionInputs",
    "CheckWatchedQuestionWorkflow",
    "ScheduleDueWatchedQuestionsWorkflow",
    "WATCHED_QUESTION_WORKFLOWS",
]
