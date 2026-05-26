from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.autoresearch.backend.inference import _score_rows, run_inference_for_pipeline
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun


class TestScoreRows(BaseTest):
    def _make_recipe(self) -> dict:
        return {
            "feature_sql": "SELECT person_id AS distinct_id, count() AS events_total_30d FROM events GROUP BY person_id",
            "feature_transforms": {},
            "model_class": "LogisticRegressionStub",
            "model_params": {},
            "fit_signature": None,
            "holdout_score": 0.7,
            "agent_description": "Stub recipe",
        }

    def test_score_rows_produces_values_between_0_and_1(self):
        rows = [
            {"distinct_id": "user-1", "events_total_30d": 100, "days_since_last_seen": 0},
            {"distinct_id": "user-2", "events_total_30d": 0, "days_since_last_seen": 30},
            {"distinct_id": "user-3", "events_total_30d": 50, "days_since_last_seen": 5},
        ]
        recipe = self._make_recipe()
        scored = _score_rows(feature_rows=rows, recipe=recipe)
        assert len(scored) == 3
        for row in scored:
            assert 0.0 <= row["p_y"] <= 1.0, f"Score {row['p_y']} for {row['distinct_id']} out of range"

    def test_score_rows_higher_activity_scores_higher(self):
        rows = [
            {"distinct_id": "active", "events_total_30d": 200, "days_since_last_seen": 0},
            {"distinct_id": "inactive", "events_total_30d": 0, "days_since_last_seen": 30},
        ]
        recipe = self._make_recipe()
        scored = {r["distinct_id"]: r["p_y"] for r in _score_rows(feature_rows=rows, recipe=recipe)}
        assert scored["active"] > scored["inactive"]

    def test_score_rows_empty_input(self):
        recipe = self._make_recipe()
        result = _score_rows(feature_rows=[], recipe=recipe)
        assert result == []


class TestRunInferencePipeline(BaseTest):
    def _make_pipeline_and_model(self) -> tuple[AutoresearchPipeline, AutoresearchModel]:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=50,
            iteration_budget_remaining=50,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={
                "feature_sql": "SELECT person_id AS distinct_id FROM events GROUP BY person_id",
                "feature_transforms": {},
                "model_class": "LogisticRegressionStub",
                "model_params": {},
                "fit_signature": None,
                "holdout_score": 0.7,
                "agent_description": "stub",
            },
            recipe_hash="deadbeef",
            holdout_score=0.7,
        )
        return pipeline, model

    @patch("products.autoresearch.backend.inference.capture_internal")
    @patch("products.autoresearch.backend.inference._fetch_feature_rows")
    def test_run_inference_creates_run_and_emits_events(self, mock_fetch: MagicMock, mock_capture: MagicMock):
        mock_fetch.return_value = [
            {"distinct_id": "user-1", "events_total_30d": 50, "days_since_last_seen": 2},
            {"distinct_id": "user-2", "events_total_30d": 10, "days_since_last_seen": 15},
        ]

        pipeline, model = self._make_pipeline_and_model()
        run = run_inference_for_pipeline(pipeline=pipeline, model=model)

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 2
        assert run.pipeline == pipeline
        assert run.model == model

        assert mock_capture.call_count == 2
        first_call_kwargs = mock_capture.call_args_list[0][1]
        assert first_call_kwargs["event_name"] == "autoresearch_prediction"
        assert "$autoresearch_pipeline_id" in first_call_kwargs["properties"]
        assert "$autoresearch_p_y" in first_call_kwargs["properties"]

    @patch("products.autoresearch.backend.inference.capture_internal")
    @patch("products.autoresearch.backend.inference._fetch_feature_rows")
    def test_run_inference_zero_rows_completes_ok(self, mock_fetch: MagicMock, mock_capture: MagicMock):
        mock_fetch.return_value = []
        pipeline, model = self._make_pipeline_and_model()
        run = run_inference_for_pipeline(pipeline=pipeline, model=model)
        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 0
        mock_capture.assert_not_called()
