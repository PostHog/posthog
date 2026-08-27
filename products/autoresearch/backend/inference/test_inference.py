from datetime import date, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.autoresearch.backend.dataset.labeling import _build_population_conditions
from products.autoresearch.backend.inference import scoring
from products.autoresearch.backend.inference.sandbox import _MATERIALIZE_ROW_LIMIT
from products.autoresearch.backend.inference.scoring import (
    InferenceRunError,
    _fetch_feature_rows,
    _fetch_inference_rows,
    _fetch_label_distinct_ids,
    _fetch_population_distinct_ids,
    _fetch_training_rows,
    _score_rows,
    run_inference_for_pipeline,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.query import HogQLResult
from products.autoresearch.backend.testing import TeamScopedTestMixin


class TestScoreRows(TeamScopedTestMixin, BaseTest):
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


class TestRunInferencePipeline(TeamScopedTestMixin, BaseTest):
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

    @patch("products.autoresearch.backend.inference.scoring.capture_internal")
    @patch("products.autoresearch.backend.inference.scoring._fetch_feature_rows")
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

    @patch("products.autoresearch.backend.inference.scoring.capture_internal")
    @patch("products.autoresearch.backend.inference.scoring._fetch_feature_rows")
    def test_run_inference_zero_rows_completes_ok(self, mock_fetch: MagicMock, mock_capture: MagicMock):
        mock_fetch.return_value = []
        pipeline, model = self._make_pipeline_and_model()
        run = run_inference_for_pipeline(pipeline=pipeline, model=model)
        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 0
        mock_capture.assert_not_called()

    @patch("products.autoresearch.backend.inference.scoring.capture_internal")
    @patch("products.autoresearch.backend.inference.scoring._fetch_feature_rows")
    def test_all_emit_failures_fail_the_run(self, mock_fetch: MagicMock, mock_capture: MagicMock):
        # Rows were scored but every capture call failed: the run must fail so
        # last_scored_at does not advance and the coordinator retries.
        mock_fetch.return_value = [
            {"distinct_id": "user-1", "events_total_30d": 50, "days_since_last_seen": 2},
            {"distinct_id": "user-2", "events_total_30d": 10, "days_since_last_seen": 15},
        ]
        mock_capture.side_effect = Exception("capture unavailable")

        pipeline, model = self._make_pipeline_and_model()
        with self.assertRaises(InferenceRunError):
            run_inference_for_pipeline(pipeline=pipeline, model=model)

        run = AutoresearchRun.objects.filter(pipeline=pipeline).latest("created_at")
        assert run.status == AutoresearchRun.Status.FAILED
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None

    @patch("products.autoresearch.backend.inference.scoring.capture_internal")
    @patch("products.autoresearch.backend.inference.scoring._fetch_feature_rows")
    def test_partial_emit_failure_completes_with_error_count(self, mock_fetch: MagicMock, mock_capture: MagicMock):
        mock_fetch.return_value = [
            {"distinct_id": "user-1", "events_total_30d": 50, "days_since_last_seen": 2},
            {"distinct_id": "user-2", "events_total_30d": 10, "days_since_last_seen": 15},
        ]
        mock_capture.side_effect = [MagicMock(), Exception("boom")]

        pipeline, model = self._make_pipeline_and_model()
        run = run_inference_for_pipeline(pipeline=pipeline, model=model)

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 1
        assert run.metrics["emit_errors"] == 1


class TestBuildPopulationConditions(TeamScopedTestMixin, BaseTest):
    def test_empty_properties_returns_empty(self):
        parts, values = _build_population_conditions([])
        assert parts == []
        assert values == {}

    def test_is_set_operator(self):
        parts, values = _build_population_conditions([{"key": "email", "type": "person", "operator": "is_set"}])
        assert len(parts) == 1
        assert "isNotNull(person.properties[{pop_k_0}])" in parts[0]
        assert values == {"pop_k_0": "email"}

    def test_is_not_set_operator(self):
        parts, values = _build_population_conditions([{"key": "email", "type": "person", "operator": "is_not_set"}])
        assert len(parts) == 1
        assert "isNull(person.properties[{pop_k_0}])" in parts[0]
        assert values == {"pop_k_0": "email"}

    def test_exact_scalar_value(self):
        parts, values = _build_population_conditions(
            [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
        )
        assert len(parts) == 1
        assert "person.properties[{pop_k_0}] = {pop_0}" in parts[0]
        assert values["pop_k_0"] == "plan"
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
        assert "person.properties[{pop_k_0}] != {pop_0}" in parts[0]
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
        assert "toFloat64OrNull(person.properties[{pop_k_0}]) > {pop_0}" in parts[0]
        assert values["pop_0"] == 18

    def test_event_type_uses_event_properties(self):
        parts, values = _build_population_conditions(
            [{"key": "plan", "type": "event", "operator": "exact", "value": "pro"}]
        )
        assert "properties[{pop_k_0}]" in parts[0]
        assert "person.properties" not in parts[0]

    def test_hostile_key_is_bound_not_interpolated(self):
        # Keys are bound as HogQL values, so a hostile key must never reach the SQL text.
        hostile_key = "'; DROP TABLE users; --"
        parts, values = _build_population_conditions([{"key": hostile_key, "type": "person", "operator": "is_set"}])
        assert len(parts) == 1
        assert hostile_key not in parts[0]
        assert values["pop_k_0"] == hostile_key

    def test_multiple_conditions_all_included(self):
        parts, values = _build_population_conditions(
            [
                {"key": "email", "type": "person", "operator": "is_set"},
                {"key": "plan", "type": "person", "operator": "exact", "value": "pro"},
            ]
        )
        assert len(parts) == 2


class TestQueryFailuresFailTheRun(TeamScopedTestMixin, BaseTest):
    def _pipeline_and_model(self) -> tuple[AutoresearchPipeline, AutoresearchModel]:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Failing",
            target_event="$pageview",
            horizon_days=7,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"feature_sql": "SELECT person_id AS distinct_id FROM events", "stub": True},
            recipe_hash="abc123",
        )
        return pipeline, model

    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_feature_query_failure_fails_the_run(self, mock_run_hogql: MagicMock):
        # Returning no rows on a transient failure completed the run as an empty population
        # and advanced the cadence, so the day's scoring was skipped with nothing retried.
        mock_run_hogql.side_effect = Exception("clickhouse timeout")
        pipeline, model = self._pipeline_and_model()

        with self.assertRaises(InferenceRunError):
            run_inference_for_pipeline(pipeline=pipeline, model=model)

        run = AutoresearchRun.objects.filter(pipeline=pipeline).latest("created_at")
        assert run.status == AutoresearchRun.Status.FAILED
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None


class TestBackfillDoesNotAdvanceCadence(TeamScopedTestMixin, BaseTest):
    @patch("products.autoresearch.backend.inference.scoring.capture_internal")
    @patch("products.autoresearch.backend.inference.scoring._score_via_anchors")
    def test_backfilling_a_past_date_leaves_last_scored_at_alone(self, mock_score: MagicMock, mock_capture: MagicMock):
        # Advancing the watermark on a backfill makes the coordinator treat the pipeline as
        # freshly scored, suppressing today's live run for a whole cadence.
        mock_score.return_value = [{"distinct_id": str(uuid4()), "p_y": 0.4}]
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Backfill",
            target_event="$pageview",
            horizon_days=7,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"feature_sql": "SELECT person_id AS distinct_id FROM {anchors}", "stub": True},
            recipe_hash="abc123",
        )

        run = run_inference_for_pipeline(
            pipeline=pipeline, model=model, prediction_date=date.today() - timedelta(days=30)
        )

        assert run.status == AutoresearchRun.Status.COMPLETED
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None

    @patch("products.autoresearch.backend.inference.scoring.capture_internal")
    @patch("products.autoresearch.backend.inference.scoring._fetch_feature_rows")
    def test_backfilling_a_recipe_without_anchors_is_refused(self, mock_fetch: MagicMock, mock_capture: MagicMock):
        # The legacy path evaluates features and labels at now(), so backfilling it would
        # stamp today's data on a past date and validate it against that date's outcome.
        mock_fetch.return_value = [{"distinct_id": str(uuid4()), "events_total_30d": 5, "days_since_last_seen": 1}]
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Legacy",
            target_event="$pageview",
            horizon_days=7,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"feature_sql": "SELECT person_id AS distinct_id FROM events", "stub": True},
            recipe_hash="abc123",
        )

        with self.assertRaises(InferenceRunError):
            run_inference_for_pipeline(
                pipeline=pipeline, model=model, prediction_date=date.today() - timedelta(days=30)
            )
        mock_capture.assert_not_called()


class TestFetchFeatureRowsPopulationFilter(TeamScopedTestMixin, BaseTest):
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

    @patch("products.autoresearch.backend.inference.scoring._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_empty_population_still_consults_population_filter(self, mock_run_hogql: MagicMock, mock_pop: MagicMock):
        # Under the v1 identified-only scope the population filter is consulted even
        # for an empty population — the identified-users restriction lives inside
        # _fetch_population_distinct_ids, which returns None only when nothing applies.
        pipeline = self._make_pipeline(inference_population={})
        model = self._make_model(pipeline)

        mock_run_hogql.return_value = HogQLResult(columns=["distinct_id"], rows=[["user-1"], ["user-2"]])

        mock_pop.return_value = None  # filter decides no restriction applies → all rows kept

        rows = _fetch_feature_rows(team=self.team, pipeline=pipeline, model=model)

        mock_pop.assert_called_once()
        assert len(rows) == 2

    @patch("products.autoresearch.backend.inference.scoring._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_population_filter_restricts_rows(self, mock_run_hogql: MagicMock, mock_pop: MagicMock):
        pipeline = self._make_pipeline(
            inference_population={
                "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
            }
        )
        model = self._make_model(pipeline)

        mock_run_hogql.return_value = HogQLResult(columns=["distinct_id"], rows=[["user-1"], ["user-2"], ["user-3"]])

        # Only user-1 and user-3 are in the population
        mock_pop.return_value = frozenset(["user-1", "user-3"])

        rows = _fetch_feature_rows(team=self.team, pipeline=pipeline, model=model)

        assert len(rows) == 2
        assert {r["distinct_id"] for r in rows} == {"user-1", "user-3"}


class TestFetchPopulationDistinctIds(TeamScopedTestMixin, BaseTest):
    @patch("products.autoresearch.backend.inference.scoring.run_hogql_rows")
    def test_empty_population_restricts_to_identified_users(self, mock_rows: MagicMock):
        # v1 identified-only: even an empty population restricts scoring to identified
        # users — the query carries the is_identified clause and a person_id set is returned.
        mock_rows.return_value = [("person-1",), ("person-2",)]

        allowed = _fetch_population_distinct_ids(team=self.team, population={}, lookback_days=30)

        assert allowed == frozenset({"person-1", "person-2"})
        sent_sql = mock_rows.call_args.kwargs["query"].query
        assert "person.is_identified" in sent_sql

    @patch("products.autoresearch.backend.inference.scoring.run_hogql_rows")
    def test_population_query_failure_fails_closed(self, mock_rows: MagicMock):
        # A transient HogQL failure must fail the run — treating it as "no restriction"
        # would score everyone and write person properties outside the population.
        mock_rows.side_effect = Exception("clickhouse timeout")

        with self.assertRaises(InferenceRunError):
            _fetch_population_distinct_ids(
                team=self.team,
                population={"properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]},
                lookback_days=30,
            )

    @parameterized.expand(
        [
            (
                "ever_performed_event",
                {"kind": "ever_performed_event", "event": "downloaded_file"},
                ["person_id IN (SELECT DISTINCT person_id FROM events WHERE", "AND event = {popk_event})"],
            ),
            (
                "active_not_performed_target",
                {"kind": "active_not_performed_target", "active_within_days": 30},
                ["person_id NOT IN (SELECT DISTINCT person_id FROM events WHERE", "AND (event = {target}))"],
            ),
            (
                "performed_event_within_days",
                {"kind": "performed_event_within_days", "days": 30, "event": "downloaded_file"},
                ["toIntervalDay({popk_days})"],
            ),
        ]
    )
    @patch("products.autoresearch.backend.inference.scoring.run_hogql_rows")
    def test_population_kind_restricts_query(
        self, _name: str, population: dict, expected_fragments: list[str], mock_rows: MagicMock
    ):
        # Template populations carry semantic kind specs; the in-process scoring path
        # must compile them or a template pipeline silently scores all identified users.
        mock_rows.return_value = [("person-1",)]

        allowed = _fetch_population_distinct_ids(
            team=self.team, population=population, lookback_days=30, target_event="downloaded_file"
        )

        assert allowed == frozenset({"person-1"})
        sent_query = mock_rows.call_args.kwargs["query"]
        for fragment in expected_fragments:
            assert fragment in sent_query.query
        assert sent_query.values["lookback"] == 30

    @patch("products.autoresearch.backend.inference.scoring.run_hogql_rows")
    def test_uncompilable_population_kind_fails_closed(self, mock_rows: MagicMock):
        # A kind spec missing a required key must raise before any query runs —
        # widening to "all identified users" is the failure mode being prevented.
        with self.assertRaises(ValueError):
            _fetch_population_distinct_ids(
                team=self.team,
                population={"kind": "ever_performed_event"},
                lookback_days=30,
            )
        mock_rows.assert_not_called()


class TestPersonIdQueriesAreBounded(TeamScopedTestMixin, BaseTest):
    def _pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Bounded",
            target_event="$pageview",
            horizon_days=7,
        )

    def _call(self, which: str):
        if which == "population":
            return _fetch_population_distinct_ids(team=self.team, population={}, lookback_days=30)
        return _fetch_label_distinct_ids(team=self.team, pipeline=self._pipeline())

    @parameterized.expand([("population",), ("label",)])
    @patch("products.autoresearch.backend.inference.scoring.run_hogql_rows")
    def test_query_carries_an_explicit_limit(self, which: str, mock_rows: MagicMock):
        # HogQL silently caps an unbounded query at 100 rows, so dropping the LIMIT
        # scored only the first 100 people while the run reported success.
        mock_rows.return_value = [("person-1",)]

        self._call(which)

        assert f"LIMIT {_MATERIALIZE_ROW_LIMIT}" in mock_rows.call_args.kwargs["query"].query

    @parameterized.expand([("population",), ("label",)])
    @patch("products.autoresearch.backend.inference.scoring.run_hogql_rows")
    def test_a_result_that_fills_the_bound_fails_the_run(self, which: str, mock_rows: MagicMock):
        # A full result is almost certainly truncated; scoring the partial set would skip
        # users while last_scored_at advanced past them.
        mock_rows.return_value = [(f"person-{i}",) for i in range(_MATERIALIZE_ROW_LIMIT)]

        with self.assertRaises(InferenceRunError):
            self._call(which)


class TestAnchorsRecipeQueries(TeamScopedTestMixin, BaseTest):
    _FEATURE_SQL = "SELECT a.person_id AS distinct_id, count() AS events_total FROM {anchors} a GROUP BY a.person_id"

    def _make_pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="anchors",
            target_event="$pageview",
            horizon_days=7,
        )

    def test_recipe_query_carries_explicit_limit(self):
        # Without an explicit LIMIT, HogQL silently caps the composite query at 100 rows.
        pipeline = self._make_pipeline()
        with patch.object(scoring, "run_hogql") as mock_run_hogql:
            mock_run_hogql.return_value = HogQLResult(columns=[], rows=[])
            _fetch_inference_rows(team=self.team, pipeline=pipeline, feature_sql=self._FEATURE_SQL)
        sent_sql = mock_run_hogql.call_args.kwargs["query"].query
        assert sent_sql.rstrip().endswith(f"LIMIT {scoring._MATERIALIZE_ROW_LIMIT}")

    @parameterized.expand([("training",), ("inference",)])
    def test_recipe_query_hitting_row_limit_fails(self, kind: str):
        # A result that fills the LIMIT is a truncated population — completing would
        # silently skip the users past the cap while last_scored_at advances.
        pipeline = self._make_pipeline()
        full_page = HogQLResult(columns=["distinct_id"], rows=[[f"p{i}"] for i in range(3)])
        with (
            patch.object(scoring, "_MATERIALIZE_ROW_LIMIT", 3),
            patch.object(scoring, "run_hogql") as mock_run_hogql,
        ):
            mock_run_hogql.return_value = full_page
            with self.assertRaises(InferenceRunError):
                if kind == "training":
                    _fetch_training_rows(team=self.team, pipeline=pipeline, feature_sql=self._FEATURE_SQL)
                else:
                    _fetch_inference_rows(team=self.team, pipeline=pipeline, feature_sql=self._FEATURE_SQL)

    def test_inference_rows_thread_backfill_cutoff(self):
        # Backdated scoring must compute features as of the backfill instant, not now().
        pipeline = self._make_pipeline()
        with patch.object(scoring, "run_hogql") as mock_run_hogql:
            mock_run_hogql.return_value = HogQLResult(columns=[], rows=[])
            _fetch_inference_rows(
                team=self.team, pipeline=pipeline, feature_sql=self._FEATURE_SQL, cutoff_ts=1_700_000_000
            )
        sent_query = mock_run_hogql.call_args.kwargs["query"]
        assert sent_query.values["cutoff_ts"] == 1_700_000_000
