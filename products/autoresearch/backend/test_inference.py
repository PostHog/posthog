from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.autoresearch.backend.inference import (
    _build_population_conditions,
    _score_rows,
    run_inference_for_pipeline,
)
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


class TestBuildPopulationConditions(BaseTest):
    def test_empty_properties_returns_empty(self):
        parts, values = _build_population_conditions([])
        assert parts == []
        assert values == {}

    def test_is_set_operator(self):
        parts, values = _build_population_conditions([{"key": "email", "type": "person", "operator": "is_set"}])
        assert len(parts) == 1
        assert "isNotNull(person.properties.email)" in parts[0]
        assert values == {}

    def test_is_not_set_operator(self):
        parts, values = _build_population_conditions([{"key": "email", "type": "person", "operator": "is_not_set"}])
        assert len(parts) == 1
        assert "isNull(person.properties.email)" in parts[0]

    def test_exact_scalar_value(self):
        parts, values = _build_population_conditions(
            [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
        )
        assert len(parts) == 1
        assert "person.properties.plan = {pop_0}" in parts[0]
        assert values["pop_0"] == "pro"

    def test_exact_list_value(self):
        parts, values = _build_population_conditions(
            [{"key": "plan", "type": "person", "operator": "exact", "value": ["pro", "enterprise"]}]
        )
        assert len(parts) == 1
        assert "IN" in parts[0]
        assert values["pop_0_0"] == "pro"
        assert values["pop_0_1"] == "enterprise"

    def test_is_not_scalar(self):
        parts, values = _build_population_conditions(
            [{"key": "plan", "type": "person", "operator": "is_not", "value": "free"}]
        )
        assert "person.properties.plan != {pop_0}" in parts[0]
        assert values["pop_0"] == "free"

    def test_icontains(self):
        parts, values = _build_population_conditions(
            [{"key": "email", "type": "person", "operator": "icontains", "value": "posthog"}]
        )
        assert "ILIKE" in parts[0]
        assert values["pop_0"] == "%posthog%"

    def test_not_icontains(self):
        parts, values = _build_population_conditions(
            [{"key": "email", "type": "person", "operator": "not_icontains", "value": "test"}]
        )
        assert "NOT ILIKE" in parts[0]
        assert values["pop_0"] == "%test%"

    def test_gt_operator(self):
        parts, values = _build_population_conditions([{"key": "age", "type": "person", "operator": "gt", "value": 18}])
        assert "toFloat64OrNull(person.properties.age) > {pop_0}" in parts[0]
        assert values["pop_0"] == 18

    def test_event_type_uses_event_properties(self):
        parts, values = _build_population_conditions(
            [{"key": "plan", "type": "event", "operator": "exact", "value": "pro"}]
        )
        assert "properties.plan" in parts[0]
        assert "person.properties" not in parts[0]

    def test_unsafe_key_skipped(self):
        parts, values = _build_population_conditions(
            [{"key": "'; DROP TABLE users; --", "type": "person", "operator": "is_set"}]
        )
        assert parts == []

    def test_unsupported_prop_type_skipped(self):
        parts, values = _build_population_conditions(
            [{"key": "cohort_id", "type": "cohort", "operator": "exact", "value": "123"}]
        )
        assert parts == []

    def test_multiple_conditions_all_included(self):
        parts, values = _build_population_conditions(
            [
                {"key": "email", "type": "person", "operator": "is_set"},
                {"key": "plan", "type": "person", "operator": "exact", "value": "pro"},
            ]
        )
        assert len(parts) == 2


class TestFetchFeatureRowsPopulationFilter(BaseTest):
    def _make_pipeline(self, inference_population: dict) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            inference_population=inference_population,
        )

    def _make_model(self, pipeline: AutoresearchPipeline) -> AutoresearchModel:
        return AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={
                "feature_sql": "SELECT distinct_id FROM events GROUP BY distinct_id",
                "stub": True,
            },
            recipe_hash="abc123",
        )

    @patch("products.autoresearch.backend.inference._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.HogQLQueryRunner")
    def test_empty_population_does_not_filter(self, mock_runner_cls: MagicMock, mock_pop: MagicMock):
        pipeline = self._make_pipeline(inference_population={})
        model = self._make_model(pipeline)

        mock_result = MagicMock()
        mock_result.results = [("user-1",), ("user-2",)]
        mock_result.columns = ["distinct_id"]
        mock_runner_cls.return_value.run.return_value = mock_result

        from products.autoresearch.backend.inference import _fetch_feature_rows

        rows = _fetch_feature_rows(team=self.team, pipeline=pipeline, model=model)

        mock_pop.assert_not_called()
        assert len(rows) == 2

    @patch("products.autoresearch.backend.inference._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.HogQLQueryRunner")
    def test_population_filter_restricts_rows(self, mock_runner_cls: MagicMock, mock_pop: MagicMock):
        pipeline = self._make_pipeline(
            inference_population={
                "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
            }
        )
        model = self._make_model(pipeline)

        mock_result = MagicMock()
        mock_result.results = [("user-1",), ("user-2",), ("user-3",)]
        mock_result.columns = ["distinct_id"]
        mock_runner_cls.return_value.run.return_value = mock_result

        # Only user-1 and user-3 are in the population
        mock_pop.return_value = frozenset(["user-1", "user-3"])

        from products.autoresearch.backend.inference import _fetch_feature_rows

        rows = _fetch_feature_rows(team=self.team, pipeline=pipeline, model=model)

        assert len(rows) == 2
        assert {r["distinct_id"] for r in rows} == {"user-1", "user-3"}

    @patch("products.autoresearch.backend.inference._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.HogQLQueryRunner")
    def test_population_query_failure_fails_open(self, mock_runner_cls: MagicMock, mock_pop: MagicMock):
        pipeline = self._make_pipeline(
            inference_population={
                "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
            }
        )
        model = self._make_model(pipeline)

        mock_result = MagicMock()
        mock_result.results = [("user-1",), ("user-2",)]
        mock_result.columns = ["distinct_id"]
        mock_runner_cls.return_value.run.return_value = mock_result

        # Simulate population query failure (returns None = fail open)
        mock_pop.return_value = None

        from products.autoresearch.backend.inference import _fetch_feature_rows

        rows = _fetch_feature_rows(team=self.team, pipeline=pipeline, model=model)

        # All rows returned — fail open, not fail closed
        assert len(rows) == 2
