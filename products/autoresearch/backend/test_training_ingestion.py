import json

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone as django_timezone

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.training_ingestion import (
    ITERATION_EVENT_NAME,
    _extract_json_from_text,
    _extract_last_agent_message,
    handle_task_run_completed,
)

MINIMAL_RECIPE: dict = {
    "feature_sql": "SELECT person_id AS distinct_id FROM events GROUP BY person_id",
    "feature_transforms": [],
    "model_class": "sklearn.linear_model.LogisticRegression",
    "model_params": {"C": 1.0},
    "fit_signature": "abc123",
    "trained_on": "2026-01-01 to 2026-02-01",
    "holdout_score": 0.72,
    "agent_description": "Simple pageview count feature.",
    "model_explanation": {"top_features": [{"name": "pageview_count", "importance": 0.9, "direction": "positive"}]},
    "iterations": [],
}


def _task_run(status: str = "completed", output: dict | None = None, state: dict | None = None):
    """Build a minimal mock TaskRun-like object."""

    class FakeTaskRun:
        pass

    tr = FakeTaskRun()
    tr.id = "00000000-0000-0000-0000-000000000001"  # type: ignore[attr-defined]
    tr.status = status  # type: ignore[attr-defined]
    tr.output = output  # type: ignore[attr-defined]
    tr.state = state or {}  # type: ignore[attr-defined]
    tr.error_message = None  # type: ignore[attr-defined]
    tr.log_url = None  # type: ignore[attr-defined]
    return tr


class TestHandleTaskRunCompleted(BaseTest):
    def _make_pipeline(self, **kwargs) -> AutoresearchPipeline:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Test",
            "target_event": "$pageview",
            "horizon_days": 7,
            "iteration_budget": 10,
            "iteration_budget_remaining": 10,
        }
        defaults.update(kwargs)
        return AutoresearchPipeline.objects.create(**defaults)

    def _make_training_run(self, pipeline: AutoresearchPipeline, **kwargs) -> AutoresearchTrainingRun:
        defaults = {
            "pipeline": pipeline,
            "status": AutoresearchTrainingRun.Status.RUNNING,
            "iteration_budget": 10,
            "started_at": django_timezone.now(),
        }
        defaults.update(kwargs)
        return AutoresearchTrainingRun.objects.create(**defaults)

    def test_skips_run_without_training_run_id(self) -> None:
        handle_task_run_completed(_task_run(state={}))
        assert AutoresearchTrainingRun.objects.count() == 0

    def test_marks_failed_on_failed_task_run(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        tr = _task_run(status="failed", state={"autoresearch_training_run_id": str(training_run.id)})
        tr.error_message = "sandbox crashed"

        handle_task_run_completed(tr)

        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.FAILED
        assert "sandbox crashed" in training_run.error

    def test_idempotency_guard_skips_already_completed(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline, status=AutoresearchTrainingRun.Status.COMPLETED)
        handle_task_run_completed(
            _task_run(output=MINIMAL_RECIPE, state={"autoresearch_training_run_id": str(training_run.id)})
        )
        assert AutoresearchModel.objects.filter(pipeline=pipeline).count() == 0

    def test_ingests_structured_output(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        tr = _task_run(output=MINIMAL_RECIPE, state={"autoresearch_training_run_id": str(training_run.id)})

        handle_task_run_completed(tr)

        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.COMPLETED
        assert training_run.best_holdout_score == pytest.approx(0.72)

        champion = AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.holdout_score == pytest.approx(0.72)
        assert champion.source_training_run == training_run

    def test_ingests_iterations(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        recipe = {
            **MINIMAL_RECIPE,
            "iterations": [
                {
                    "iteration_number": 1,
                    "recipe_hash": "iter1hash",
                    "model_class": "sklearn.linear_model.LogisticRegression",
                    "model_params": {"C": 0.5},
                    "feature_summary": "basic features",
                    "holdout_score": 0.65,
                    "status": "discarded",
                    "agent_description": "tried C=0.5",
                },
                {
                    "iteration_number": 2,
                    "recipe_hash": "iter2hash",
                    "model_class": "sklearn.linear_model.LogisticRegression",
                    "model_params": {"C": 1.0},
                    "feature_summary": "basic features",
                    "holdout_score": 0.72,
                    "status": "kept",
                    "agent_description": "C=1.0 better",
                },
            ],
        }
        tr = _task_run(output=recipe, state={"autoresearch_training_run_id": str(training_run.id)})

        handle_task_run_completed(tr)

        assert AutoresearchIteration.objects.filter(training_run=training_run).count() == 2
        training_run.refresh_from_db()
        assert training_run.iteration_count == 2

    def test_archives_existing_champion(self) -> None:
        pipeline = self._make_pipeline()
        old_champion = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="old_hash",
            holdout_score=0.6,
        )
        training_run = self._make_training_run(pipeline)
        tr = _task_run(output=MINIMAL_RECIPE, state={"autoresearch_training_run_id": str(training_run.id)})

        handle_task_run_completed(tr)

        old_champion.refresh_from_db()
        assert old_champion.role == AutoresearchModel.Role.ARCHIVED

    @patch("products.autoresearch.backend.training_ingestion.capture_internal")
    def test_ingests_iterations_emits_events(self, mock_capture: MagicMock) -> None:
        mock_capture.return_value = MagicMock(raise_for_status=MagicMock())

        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        recipe = {
            **MINIMAL_RECIPE,
            "iterations": [
                {
                    "iteration_number": 1,
                    "recipe_hash": "iter1hash",
                    "model_class": "sklearn.linear_model.LogisticRegression",
                    "model_params": {"C": 0.5},
                    "feature_summary": "basic features",
                    "holdout_score": 0.65,
                    "status": "discarded",
                    "agent_description": "tried C=0.5",
                },
                {
                    "iteration_number": 2,
                    "recipe_hash": "iter2hash",
                    "model_class": "sklearn.linear_model.LogisticRegression",
                    "model_params": {"C": 1.0},
                    "feature_summary": "basic features",
                    "holdout_score": 0.72,
                    "status": "kept",
                    "agent_description": "C=1.0 better",
                },
            ],
        }
        tr = _task_run(output=recipe, state={"autoresearch_training_run_id": str(training_run.id)})
        handle_task_run_completed(tr)

        assert mock_capture.call_count == 2

        first_call_kwargs = mock_capture.call_args_list[0].kwargs
        assert first_call_kwargs["event_name"] == ITERATION_EVENT_NAME
        assert first_call_kwargs["distinct_id"] == f"$autoresearch:pipeline:{pipeline.pk}"
        assert first_call_kwargs["process_person_profile"] is False

        props = first_call_kwargs["properties"]
        assert props["$autoresearch_pipeline_id"] == str(pipeline.pk)
        assert props["$autoresearch_training_run_id"] == str(training_run.pk)
        assert props["$autoresearch_iteration_number"] == 1
        assert props["$autoresearch_iteration_status"] == "discarded"
        assert props["$autoresearch_holdout_score"] == pytest.approx(0.65)
        assert props["$autoresearch_model_class"] == "sklearn.linear_model.LogisticRegression"
        assert props["$autoresearch_target_event"] == "$pageview"
        assert props["$autoresearch_horizon_days"] == 7

    @patch("products.autoresearch.backend.training_ingestion.capture_internal")
    def test_no_events_emitted_when_no_iterations(self, mock_capture: MagicMock) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        tr = _task_run(output=MINIMAL_RECIPE, state={"autoresearch_training_run_id": str(training_run.id)})
        handle_task_run_completed(tr)
        mock_capture.assert_not_called()

    @patch("products.autoresearch.backend.training_ingestion.capture_internal")
    def test_emit_failure_does_not_break_ingestion(self, mock_capture: MagicMock) -> None:
        mock_capture.side_effect = RuntimeError("network error")

        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        recipe = {
            **MINIMAL_RECIPE,
            "iterations": [
                {
                    "iteration_number": 1,
                    "recipe_hash": "iter1hash",
                    "model_class": "sklearn.linear_model.LogisticRegression",
                    "model_params": {},
                    "feature_summary": "basic features",
                    "holdout_score": 0.65,
                    "status": "discarded",
                    "agent_description": "first try",
                },
            ],
        }
        tr = _task_run(output=recipe, state={"autoresearch_training_run_id": str(training_run.id)})
        handle_task_run_completed(tr)

        # DB records are persisted even when emission fails
        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.COMPLETED
        assert AutoresearchIteration.objects.filter(training_run=training_run).count() == 1

    def test_marks_failed_when_no_valid_recipe(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        tr = _task_run(output={"bad": "data"}, state={"autoresearch_training_run_id": str(training_run.id)})

        with patch(
            "products.autoresearch.backend.training_ingestion._extract_recipe_from_logs",
            return_value=None,
        ):
            handle_task_run_completed(tr)

        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.FAILED


class TestExtractJsonFromText:
    @pytest.mark.parametrize(
        "text,expected_key",
        [
            ('```json\n{"feature_sql": "SELECT 1"}\n```', "feature_sql"),
            ('```\n{"feature_sql": "SELECT 1"}\n```', "feature_sql"),
            ('Some prose here {"feature_sql": "SELECT 1"} more prose', "feature_sql"),
            ('{"feature_sql": "SELECT 1"}', "feature_sql"),
        ],
    )
    def test_extracts_from_formats(self, text: str, expected_key: str) -> None:
        result = _extract_json_from_text(text)
        assert result is not None
        assert expected_key in result

    def test_returns_none_for_no_json(self) -> None:
        assert _extract_json_from_text("no json here at all") is None

    def test_returns_none_for_json_array(self) -> None:
        assert _extract_json_from_text("[1, 2, 3]") is None


class TestExtractLastAgentMessage:
    def _make_log_line(self, session_update: str, text: str) -> str:
        entry = {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": session_update,
                        "content": {"type": "text", "text": text},
                    }
                },
            }
        }
        return json.dumps(entry)

    def test_extracts_last_agent_message(self) -> None:
        lines = [
            self._make_log_line("user_message", "Hello"),
            self._make_log_line("agent_message", "First response"),
            self._make_log_line("user_message", "Follow up"),
            self._make_log_line("agent_message", "Final response"),
        ]
        result = _extract_last_agent_message("\n".join(lines))
        assert result == "Final response"

    def test_assembles_consecutive_chunks(self) -> None:
        lines = [
            self._make_log_line("agent_message_chunk", "Hello"),
            self._make_log_line("agent_message_chunk", "world"),
        ]
        result = _extract_last_agent_message("\n".join(lines))
        assert result == "Helloworld"

    def test_returns_none_for_empty_log(self) -> None:
        assert _extract_last_agent_message("") is None

    def test_returns_none_for_no_agent_message(self) -> None:
        lines = [self._make_log_line("user_message", "Hello")]
        assert _extract_last_agent_message("\n".join(lines)) is None
