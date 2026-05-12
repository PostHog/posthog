import uuid
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from products.posthog_ai.backend.models import TrackedQuestion, TrackedQuestionRun
from products.signals.backend.models import SignalSourceConfig

from ee.models.assistant import Conversation

from ..activities import emit_drift_signal_activity, persist_run_and_advance_activity, retrieve_due_watched_questions
from ..types import EmitDriftSignalActivityInputs, PersistRunActivityInputs


class TestWatchedQuestionActivities(BaseTest):
    def _make_tracked_question(self, **overrides) -> TrackedQuestion:
        conversation = Conversation.objects.create(team=self.team, user=self.user)
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "source_conversation": conversation,
            "source_human_message_id": uuid.uuid4(),
            "source_visualization_message_id": uuid.uuid4(),
            "title": "Watched answer",
            "question_text": "Q?",
            "baseline_summary": "Baseline summary.",
            "baseline_captured_at": timezone.now(),
            "cadence": TrackedQuestion.Cadence.WEEKLY,
            "next_run_at": timezone.now() - timedelta(minutes=5),
        }
        defaults.update(overrides)
        return TrackedQuestion.objects.create(**defaults)

    @pytest.mark.asyncio
    async def test_retrieve_due_watched_questions_returns_due_rows(self) -> None:
        tq = await sync_to_async(self._make_tracked_question)()
        env = ActivityEnvironment()
        rows = await env.run(retrieve_due_watched_questions)
        ids = {row.tracked_question_id for row in rows}
        assert str(tq.id) in ids

    @pytest.mark.asyncio
    async def test_emit_drift_signal_skips_when_source_disabled(self) -> None:
        tq = await sync_to_async(self._make_tracked_question)()
        env = ActivityEnvironment()
        with (
            patch("posthog.temporal.watched_questions.activities.emit_signal", new=AsyncMock()) as mock_emit,
            patch(
                "posthog.temporal.watched_questions.activities.SignalSourceConfig.is_source_enabled",
                return_value=False,
            ),
        ):
            result = await env.run(
                emit_drift_signal_activity,
                EmitDriftSignalActivityInputs(
                    tracked_question_id=str(tq.id),
                    forked_conversation_id=str(uuid.uuid4()),
                    narrative="Activation dropped 30%.",
                    query_kind="AssistantTrendsQuery",
                    severity="significant",
                    judge_summary="Drop in activation.",
                ),
            )
        assert result.signal_emitted_at is None
        mock_emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_emit_drift_signal_calls_emit_signal_when_enabled(self) -> None:
        tq = await sync_to_async(self._make_tracked_question)()
        await sync_to_async(SignalSourceConfig.objects.create)(
            team=self.team,
            source_product=SignalSourceConfig.SourceProduct.POSTHOG_AI,
            source_type=SignalSourceConfig.SourceType.QUESTION_DRIFT,
            enabled=True,
        )
        env = ActivityEnvironment()
        with patch("posthog.temporal.watched_questions.activities.emit_signal", new=AsyncMock()) as mock_emit:
            result = await env.run(
                emit_drift_signal_activity,
                EmitDriftSignalActivityInputs(
                    tracked_question_id=str(tq.id),
                    forked_conversation_id=str(uuid.uuid4()),
                    narrative="Activation dropped from 41% to 28%.",
                    query_kind="AssistantFunnelsQuery",
                    severity="significant",
                    judge_summary="Major drop in activation funnel.",
                ),
            )
        assert result.signal_emitted_at is not None
        mock_emit.assert_awaited_once()
        call_kwargs = mock_emit.await_args.kwargs
        assert call_kwargs["source_product"] == SignalSourceConfig.SourceProduct.POSTHOG_AI
        assert call_kwargs["source_type"] == SignalSourceConfig.SourceType.QUESTION_DRIFT
        assert call_kwargs["weight"] == 0.9
        assert "Activation dropped" in call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_persist_run_creates_row_and_advances_schedule(self) -> None:
        tq = await sync_to_async(self._make_tracked_question)()
        env = ActivityEnvironment()
        await env.run(
            persist_run_and_advance_activity,
            PersistRunActivityInputs(
                tracked_question_id=str(tq.id),
                state="drifted",
                severity="moderate",
                narrative="Narrative.",
                judge_summary="Some drift.",
                forked_conversation_id=None,
            ),
        )
        runs = await sync_to_async(list)(tq.runs.all())
        assert len(runs) == 1
        assert runs[0].state == TrackedQuestionRun.State.DRIFTED
        tq_refreshed = await sync_to_async(TrackedQuestion.objects.get)(id=tq.id)
        assert tq_refreshed.next_run_at > timezone.now()
