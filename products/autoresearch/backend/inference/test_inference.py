from datetime import date, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.capture import CaptureInternalResult

from products.autoresearch.backend.dataset.labeling import PREDICTION_EVENT_NAME
from products.autoresearch.backend.inference import scoring
from products.autoresearch.backend.inference.sandbox import _MATERIALIZE_ROW_LIMIT
from products.autoresearch.backend.inference.scoring import (
    InferenceRunError,
    ScoredPopulation,
    _fetch_inference_rows,
    _fetch_population_distinct_ids,
    _fetch_stub_feature_rows,
    _fetch_training_rows,
    _resolve_distinct_ids,
    _score_rows,
    run_inference_for_pipeline,
    score_population,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.query import HogQLResult
from products.autoresearch.backend.testing import TeamScopedTestMixin

_STUB_RECIPE = {
    "feature_sql": "SELECT person_id AS distinct_id, count() AS events_total_30d FROM events GROUP BY person_id",
    "model_class": "sklearn.linear_model.LogisticRegression",
    "model_params": {},
    "stub": True,
}
_ANCHORS_FEATURE_SQL = (
    "SELECT a.person_id AS distinct_id, count() AS events_total FROM {anchors} a GROUP BY a.person_id"
)
_ANCHORS_RECIPE = {
    "feature_sql": _ANCHORS_FEATURE_SQL,
    "model_class": "sklearn.linear_model.LogisticRegression",
    "model_params": {},
}
_STUB_ROWS = [
    {"distinct_id": "user-1", "events_total_30d": 50, "days_since_last_seen": 2},
    {"distinct_id": "user-2", "events_total_30d": 10, "days_since_last_seen": 15},
]


def _accepted(events: list[dict]) -> CaptureInternalResult:
    return CaptureInternalResult(status_code=200, ok=[e["event_uuid"] for e in events])


def _capture_accepting_everything() -> MagicMock:
    return MagicMock(side_effect=lambda **kwargs: _accepted(kwargs["events"]))


class TestScoreRows(SimpleTestCase):
    def test_score_rows_produces_values_between_0_and_1(self):
        rows = [
            {"distinct_id": "user-1", "events_total_30d": 100, "days_since_last_seen": 0},
            {"distinct_id": "user-2", "events_total_30d": 0, "days_since_last_seen": 30},
            {"distinct_id": "user-3", "events_total_30d": 50, "days_since_last_seen": 5},
        ]
        scored = _score_rows(rows)
        assert len(scored) == 3
        for row in scored:
            assert 0.0 <= row["p_y"] <= 1.0, f"Score {row['p_y']} for {row['distinct_id']} out of range"

    def test_score_rows_higher_activity_scores_higher(self):
        rows = [
            {"distinct_id": "active", "events_total_30d": 200, "days_since_last_seen": 0},
            {"distinct_id": "inactive", "events_total_30d": 0, "days_since_last_seen": 30},
        ]
        scored = {r["distinct_id"]: r["p_y"] for r in _score_rows(rows)}
        assert scored["active"] > scored["inactive"]

    def test_score_rows_treats_zero_days_since_last_seen_as_most_recent(self):
        rows = [
            {"distinct_id": "today", "events_total_30d": 10, "days_since_last_seen": 0},
            {"distinct_id": "stale", "events_total_30d": 10, "days_since_last_seen": 30},
            {"distinct_id": "unknown", "events_total_30d": 10, "days_since_last_seen": None},
        ]
        scored = {r["distinct_id"]: r["p_y"] for r in _score_rows(rows)}
        assert scored["today"] > scored["stale"]
        assert scored["unknown"] == scored["stale"]

    def test_score_rows_empty_input(self):
        assert _score_rows([]) == []


class TestRunInferencePipeline(TeamScopedTestMixin, BaseTest):
    def _make_pipeline_and_model(self, **pipeline_kwargs) -> tuple[AutoresearchPipeline, AutoresearchModel]:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            output_person_property="predicted_p_pageview",
            **pipeline_kwargs,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe=_STUB_RECIPE,
            recipe_hash="deadbeef",
            holdout_score=0.7,
        )
        return pipeline, model

    def _run_live(self, pipeline, model, capture: MagicMock, rows=_STUB_ROWS, resolved=None) -> AutoresearchRun:
        with (
            patch.object(scoring, "_fetch_stub_feature_rows", return_value=rows),
            patch.object(scoring, "_resolve_distinct_ids", return_value=resolved or {}),
            patch.object(scoring, "capture_batch_internal", capture),
        ):
            return run_inference_for_pipeline(pipeline=pipeline, model=model)

    def test_run_inference_emits_one_batch_and_records_the_run(self):
        pipeline, model = self._make_pipeline_and_model()
        capture = _capture_accepting_everything()

        run = self._run_live(pipeline, model, capture, resolved={"user-1": "real-distinct-id"})

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 2
        assert run.metrics["holdout_auc"] == 0.7
        assert capture.call_count == 1
        kwargs = capture.call_args.kwargs
        events = kwargs["events"]
        assert kwargs["process_person_profile"] is True
        assert [e["event"] for e in events] == [PREDICTION_EVENT_NAME, PREDICTION_EVENT_NAME]
        by_person = {e["properties"]["$autoresearch_person_id"]: e for e in events}
        # A resolved person is attached to their real distinct_id and gets the output property;
        # an unresolved one stays person-less so a UUID never becomes a person.
        assert by_person["user-1"]["distinct_id"] == "real-distinct-id"
        assert by_person["user-1"]["options"] == {"process_person_profile": True}
        assert by_person["user-1"]["properties"]["$set"] == {
            "predicted_p_pageview": by_person["user-1"]["properties"]["$autoresearch_p_y"]
        }
        assert by_person["user-2"]["distinct_id"] == "user-2"
        assert by_person["user-2"]["options"] == {"process_person_profile": False}
        assert "$set" not in by_person["user-2"]["properties"]
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is not None

    def test_run_inference_zero_rows_completes_without_emitting(self):
        pipeline, model = self._make_pipeline_and_model()
        capture = _capture_accepting_everything()
        run = self._run_live(pipeline, model, capture, rows=[])
        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 0
        capture.assert_not_called()

    @parameterized.expand(
        [
            ("transport_failure", Exception("capture unavailable"), None),
            (
                "one_event_dropped",
                None,
                lambda events: CaptureInternalResult(
                    status_code=200, ok=[events[0]["event_uuid"]], dropped=[events[1]["event_uuid"]]
                ),
            ),
        ]
    )
    def test_any_emit_failure_fails_the_run(self, _name, side_effect, result_for):
        # Completing with a partial batch advanced last_scored_at past the people who never
        # received their prediction; the deterministic UUIDs make a full replay safe instead.
        pipeline, model = self._make_pipeline_and_model()
        capture = MagicMock(side_effect=side_effect or (lambda **kwargs: result_for(kwargs["events"])))

        with self.assertRaises(InferenceRunError):
            self._run_live(pipeline, model, capture)

        run = AutoresearchRun.objects.filter(pipeline=pipeline).latest("created_at")
        assert run.status == AutoresearchRun.Status.FAILED
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None

    def test_champion_replaced_during_scoring_fails_before_emitting(self):
        # A superseded model's $set would overwrite the new champion's live property.
        pipeline, model = self._make_pipeline_and_model()
        capture = _capture_accepting_everything()

        def archive_then_return_rows(**_kwargs):
            AutoresearchModel.objects.filter(pk=model.pk).update(role=AutoresearchModel.Role.ARCHIVED)
            return _STUB_ROWS

        with (
            patch.object(scoring, "_fetch_stub_feature_rows", side_effect=archive_then_return_rows),
            patch.object(scoring, "_resolve_distinct_ids", return_value={}),
            patch.object(scoring, "capture_batch_internal", capture),
        ):
            with self.assertRaises(InferenceRunError):
                run_inference_for_pipeline(pipeline=pipeline, model=model)
        capture.assert_not_called()

    def test_prediction_events_are_identical_across_a_retry(self):
        pipeline, model = self._make_pipeline_and_model()
        first = _capture_accepting_everything()
        second = _capture_accepting_everything()
        self._run_live(pipeline, model, first)
        self._run_live(pipeline, model, second)
        assert [e["event_uuid"] for e in first.call_args.kwargs["events"]] == [
            e["event_uuid"] for e in second.call_args.kwargs["events"]
        ]

    def test_pipeline_without_a_creator_fails_instead_of_querying_with_no_user(self):
        # With no acting user HogQL fails closed and silently masks the pipeline from its own data.
        pipeline, model = self._make_pipeline_and_model()
        pipeline.created_by = None
        pipeline.save(update_fields=["created_by"])
        with patch.object(scoring, "run_hogql") as hogql:
            with self.assertRaises(InferenceRunError):
                run_inference_for_pipeline(pipeline=pipeline, model=model)
        hogql.assert_not_called()


class TestPredictionDateGuards(TeamScopedTestMixin, BaseTest):
    def _pipeline_and_model(self, **pipeline_kwargs) -> tuple[AutoresearchPipeline, AutoresearchModel]:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Dates",
            target_event="$pageview",
            horizon_days=7,
            **pipeline_kwargs,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe=_ANCHORS_RECIPE, recipe_hash="abc"
        )
        return pipeline, model

    def _assert_refused(self, pipeline, model, prediction_date, score: MagicMock):
        with patch.object(scoring, "_score_via_anchors", score):
            with self.assertRaises(InferenceRunError):
                run_inference_for_pipeline(pipeline=pipeline, model=model, prediction_date=prediction_date)
        score.assert_not_called()
        run = AutoresearchRun.objects.filter(pipeline=pipeline).latest("created_at")
        assert run.status == AutoresearchRun.Status.FAILED

    def test_future_prediction_date_is_refused(self):
        # A future date reads as live: today's features under a future label.
        pipeline, model = self._pipeline_and_model()
        self._assert_refused(pipeline, model, date.today() + timedelta(days=1), MagicMock())

    def test_backfill_past_the_teams_drop_threshold_is_refused(self):
        # Capture accepts the events and ingestion drops them, so the run would record rows
        # scored with nothing behind them.
        self.team.drop_events_older_than = timedelta(days=7)
        self.team.save(update_fields=["drop_events_older_than"])
        pipeline, model = self._pipeline_and_model()
        self._assert_refused(pipeline, model, date.today() - timedelta(days=30), MagicMock())

    def test_backfill_of_a_person_property_population_is_refused(self):
        # Person properties are evaluated as they are today, so the historical membership
        # the backfill claims would be fiction.
        pipeline, model = self._pipeline_and_model(
            inference_population={
                "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
            }
        )
        self._assert_refused(pipeline, model, date.today() - timedelta(days=3), MagicMock())

    def test_backfilling_a_past_date_leaves_last_scored_at_alone(self):
        # Advancing the watermark on a backfill makes the coordinator treat the pipeline as
        # freshly scored, suppressing today's live run for a whole cadence.
        pipeline, model = self._pipeline_and_model()
        scored = ScoredPopulation(rows=[{"distinct_id": str(uuid4()), "p_y": 0.4}], holdout_auc=None)
        with (
            patch.object(scoring, "_score_via_anchors", return_value=scored),
            patch.object(scoring, "capture_batch_internal", _capture_accepting_everything()) as capture,
        ):
            run = run_inference_for_pipeline(
                pipeline=pipeline, model=model, prediction_date=date.today() - timedelta(days=30)
            )

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert capture.call_args.kwargs["process_person_profile"] is False
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None

    def test_backfilling_a_stub_champion_is_refused(self):
        # The stub evaluates features at now(), so backfilling it would stamp today's data on
        # a past date and validate it against that date's outcome.
        pipeline, model = self._pipeline_and_model()
        model.model_recipe = _STUB_RECIPE
        model.save(update_fields=["model_recipe"])
        with patch.object(scoring, "_fetch_stub_feature_rows") as fetch:
            with self.assertRaises(InferenceRunError):
                run_inference_for_pipeline(
                    pipeline=pipeline, model=model, prediction_date=date.today() - timedelta(days=30)
                )
        fetch.assert_not_called()


class TestRecipeRouting(TeamScopedTestMixin, BaseTest):
    def _pipeline_and_model(self, recipe: dict) -> tuple[AutoresearchPipeline, AutoresearchModel]:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Routing", target_event="$pageview", horizon_days=7
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe=recipe, recipe_hash="abc"
        )
        return pipeline, model

    @parameterized.expand(
        [
            ("trailing_limit", _ANCHORS_FEATURE_SQL + " LIMIT 10"),
            (
                "anchors_only_in_a_comment",
                "-- reads {anchors}\nSELECT person_id AS distinct_id, count() AS events_total FROM events GROUP BY person_id",
            ),
            ("no_anchors_at_all", "SELECT person_id AS distinct_id, count() AS n FROM events GROUP BY person_id"),
        ]
    )
    def test_recipe_sql_the_bundle_path_would_refuse_fails_the_run(self, _name, feature_sql):
        # A trailing LIMIT makes the appended framework bound a parse error; a placeholder that
        # survives only in a comment runs the query with no anchor and no cutoff.
        pipeline, model = self._pipeline_and_model({**_ANCHORS_RECIPE, "feature_sql": feature_sql})
        with patch.object(scoring, "_score_via_anchors") as anchored, patch.object(scoring, "run_hogql") as hogql:
            with self.assertRaises(InferenceRunError):
                score_population(
                    team=self.team, pipeline=pipeline, model=model, prediction_date=date.today(), user=self.user
                )
        anchored.assert_not_called()
        hogql.assert_not_called()

    def test_dry_run_and_live_run_take_the_same_route(self):
        pipeline, model = self._pipeline_and_model(_ANCHORS_RECIPE)
        scored = ScoredPopulation(rows=[{"distinct_id": "p1", "p_y": 0.5}], holdout_auc=0.66)
        with patch.object(scoring, "_score_via_anchors", return_value=scored) as anchored:
            result = score_population(
                team=self.team, pipeline=pipeline, model=model, prediction_date=date.today(), user=self.user
            )
        assert result == scored
        anchored.assert_called_once()

    def test_recipe_only_champion_records_its_holdout_auc(self):
        # Twenty labeled rows with a clean signal fit a real LogisticRegression; a column that
        # is null in the first row and text later must not be taken for a feature.
        pipeline, model = self._pipeline_and_model(_ANCHORS_RECIPE)
        training_rows = []
        for i in range(20):
            positive = i % 2
            training_rows.append(
                {
                    "distinct_id": f"t{i}",
                    "events_total": 40 + i if positive else i,
                    "plan": None if i == 0 else "pro",
                    "__label": positive,
                    "__fold": i % 5,
                }
            )
        inference_rows = [
            {"distinct_id": "busy", "events_total": 55, "plan": "pro"},
            {"distinct_id": "quiet", "events_total": 1, "plan": None},
        ]
        with (
            patch.object(scoring, "_fetch_training_rows", return_value=training_rows),
            patch.object(scoring, "_fetch_inference_rows", return_value=inference_rows),
            patch.object(scoring, "_resolve_distinct_ids", return_value={}),
            patch.object(scoring, "capture_batch_internal", _capture_accepting_everything()),
        ):
            run = run_inference_for_pipeline(pipeline=pipeline, model=model)

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.metrics["holdout_auc"] == 1.0
        dist = run.metrics["score_distribution"]
        assert dist["max"] > dist["min"]


class TestQueryFailuresFailTheRun(TeamScopedTestMixin, BaseTest):
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_feature_query_failure_fails_the_run(self, mock_run_hogql: MagicMock):
        # Returning no rows on a transient failure completed the run as an empty population
        # and advanced the cadence, so the day's scoring was skipped with nothing retried.
        mock_run_hogql.side_effect = Exception("clickhouse timeout")
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Failing", target_event="$pageview", horizon_days=7
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION, model_recipe=_STUB_RECIPE, recipe_hash="abc123"
        )

        with self.assertRaises(InferenceRunError):
            run_inference_for_pipeline(pipeline=pipeline, model=model)

        run = AutoresearchRun.objects.filter(pipeline=pipeline).latest("created_at")
        assert run.status == AutoresearchRun.Status.FAILED
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None


class TestStubFeatureRows(TeamScopedTestMixin, BaseTest):
    def _make_pipeline(self, inference_population: dict) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            inference_population=inference_population,
        )

    @patch("products.autoresearch.backend.inference.scoring._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_empty_population_still_consults_population_filter(self, mock_run_hogql: MagicMock, mock_pop: MagicMock):
        pipeline = self._make_pipeline(inference_population={})
        mock_run_hogql.return_value = HogQLResult(columns=["distinct_id"], rows=[["user-1"], ["user-2"]])
        mock_pop.return_value = None

        rows = _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)

        mock_pop.assert_called_once()
        assert len(rows) == 2
        sent = mock_run_hogql.call_args.kwargs
        assert sent["user"] == self.user
        assert sent["query"].query.rstrip().endswith(f"LIMIT {_MATERIALIZE_ROW_LIMIT}")

    @patch("products.autoresearch.backend.inference.scoring._fetch_population_distinct_ids")
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_population_filter_restricts_rows(self, mock_run_hogql: MagicMock, mock_pop: MagicMock):
        pipeline = self._make_pipeline(
            inference_population={
                "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
            }
        )
        mock_run_hogql.return_value = HogQLResult(columns=["distinct_id"], rows=[["user-1"], ["user-2"], ["user-3"]])
        mock_pop.return_value = frozenset(["user-1", "user-3"])

        rows = _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)

        assert {r["distinct_id"] for r in rows} == {"user-1", "user-3"}

    @parameterized.expand([("blank_identifier", [["user-1"], [""]]), ("duplicate_person", [["user-1"], ["user-1"]])])
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_rows_that_do_not_key_one_person_fail_the_run(self, _name, rows, mock_run_hogql: MagicMock):
        # A blank identifier was silently dropped and a duplicate emitted the same event UUID
        # twice; either way the run completed and reported a row count nobody received.
        pipeline = self._make_pipeline(inference_population={})
        mock_run_hogql.return_value = HogQLResult(columns=["distinct_id"], rows=rows)
        with self.assertRaises(InferenceRunError):
            _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)


class TestFetchPopulationDistinctIds(TeamScopedTestMixin, BaseTest):
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_empty_population_restricts_to_identified_users_and_ignores_predictions(self, mock_run: MagicMock):
        # The scan must skip the product's own event, or a scored person stays eligible
        # forever on nothing but their predictions.
        mock_run.return_value = HogQLResult(columns=["person_id"], rows=[["person-1"], ["person-2"]])

        allowed = _fetch_population_distinct_ids(team=self.team, population={}, lookback_days=30, user=self.user)

        assert allowed == frozenset({"person-1", "person-2"})
        sent_sql = mock_run.call_args.kwargs["query"].query
        assert "person.is_identified" in sent_sql
        assert f"event != '{PREDICTION_EVENT_NAME}'" in sent_sql

    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_population_query_failure_fails_closed(self, mock_run: MagicMock):
        # A transient HogQL failure must fail the run; treating it as "no restriction" would
        # score everyone and write person properties outside the population.
        mock_run.side_effect = Exception("clickhouse timeout")

        with self.assertRaises(InferenceRunError):
            _fetch_population_distinct_ids(
                team=self.team,
                population={"properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]},
                lookback_days=30,
                user=self.user,
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
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_population_kind_restricts_query(
        self, _name: str, population: dict, expected_fragments: list[str], mock_run: MagicMock
    ):
        # Template populations carry semantic kind specs; the in-process scoring path must
        # compile them or a template pipeline silently scores all identified users.
        mock_run.return_value = HogQLResult(columns=["person_id"], rows=[["person-1"]])

        allowed = _fetch_population_distinct_ids(
            team=self.team, population=population, lookback_days=30, target_event="downloaded_file", user=self.user
        )

        assert allowed == frozenset({"person-1"})
        sent_query = mock_run.call_args.kwargs["query"]
        for fragment in expected_fragments:
            assert fragment in sent_query.query
        assert sent_query.values["lookback"] == 30

    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_uncompilable_population_kind_fails_closed(self, mock_run: MagicMock):
        # A kind spec missing a required key must raise before any query runs; widening to
        # "all identified users" is the failure mode being prevented.
        with self.assertRaises(ValueError):
            _fetch_population_distinct_ids(
                team=self.team, population={"kind": "ever_performed_event"}, lookback_days=30, user=self.user
            )
        mock_run.assert_not_called()


class TestPersonKeyedQueriesAreBounded(TeamScopedTestMixin, BaseTest):
    def _pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Bounded", target_event="$pageview", horizon_days=7
        )

    def _call(self, which: str):
        if which == "population":
            return _fetch_population_distinct_ids(team=self.team, population={}, lookback_days=30, user=self.user)
        person_ids = [str(uuid4()) for _ in range(3)]
        return _resolve_distinct_ids(team=self.team, pipeline=self._pipeline(), person_ids=person_ids, user=self.user)

    @parameterized.expand([("population",), ("identity",)])
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_query_carries_an_explicit_limit(self, which: str, mock_run: MagicMock):
        # HogQL silently caps an unbounded query at 100 rows.
        mock_run.return_value = HogQLResult(columns=["person_id", "did"], rows=[[str(uuid4()), "d1"]])

        self._call(which)

        assert f"LIMIT {_MATERIALIZE_ROW_LIMIT}" in mock_run.call_args.kwargs["query"].query

    @parameterized.expand([("population", False), ("identity", False), ("population", True)])
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_a_result_that_fills_the_bound_fails_the_run(self, which: str, has_more: bool, mock_run: MagicMock):
        # A full result is almost certainly truncated; scoring the partial set would skip
        # users while last_scored_at advanced past them.
        n = 1 if has_more else _MATERIALIZE_ROW_LIMIT
        mock_run.return_value = HogQLResult(
            columns=["person_id", "did"], rows=[[f"person-{i}", "d"] for i in range(n)], has_more=has_more
        )

        with self.assertRaises(InferenceRunError):
            self._call(which)


class TestAnchorsRecipeQueries(TeamScopedTestMixin, BaseTest):
    def _make_pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="anchors", target_event="$pageview", horizon_days=7
        )

    def test_recipe_query_carries_explicit_limit_and_runs_fresh_as_the_user(self):
        # Without an explicit LIMIT, HogQL silently caps the composite query at 100 rows. A
        # cached result would score a stale population, and with no user HogQL fails closed.
        pipeline = self._make_pipeline()
        with (
            patch.object(scoring, "run_hogql") as mock_run_hogql,
            patch.object(scoring, "count_inference_anchors", return_value=0),
        ):
            mock_run_hogql.return_value = HogQLResult(columns=[], rows=[])
            _fetch_inference_rows(
                team=self.team, pipeline=pipeline, feature_sql=_ANCHORS_FEATURE_SQL, cutoff_ts=None, user=self.user
            )
        sent = mock_run_hogql.call_args.kwargs
        assert sent["query"].query.rstrip().endswith(f"LIMIT {_MATERIALIZE_ROW_LIMIT}")
        assert sent["user"] == self.user
        assert sent["execution_mode"].name == "CALCULATE_BLOCKING_ALWAYS"
        assert sent["query"].modifiers is not None

    @parameterized.expand([("training",), ("inference",)])
    def test_recipe_query_hitting_row_limit_fails(self, kind: str):
        # A result that fills the LIMIT is a truncated population; completing would silently
        # skip the users past the cap while last_scored_at advances.
        pipeline = self._make_pipeline()
        full_page = HogQLResult(columns=["distinct_id"], rows=[[f"p{i}"] for i in range(3)])
        with (
            patch.object(scoring, "_MATERIALIZE_ROW_LIMIT", 3),
            patch.object(scoring, "run_hogql", return_value=full_page),
            patch.object(scoring, "count_inference_anchors", return_value=3),
        ):
            with self.assertRaises(InferenceRunError):
                if kind == "training":
                    _fetch_training_rows(
                        team=self.team, pipeline=pipeline, feature_sql=_ANCHORS_FEATURE_SQL, user=self.user
                    )
                else:
                    _fetch_inference_rows(
                        team=self.team,
                        pipeline=pipeline,
                        feature_sql=_ANCHORS_FEATURE_SQL,
                        cutoff_ts=None,
                        user=self.user,
                    )

    def test_inference_rows_thread_backfill_cutoff(self):
        # Backdated scoring must compute features as of the backfill instant, not now().
        pipeline = self._make_pipeline()
        with (
            patch.object(scoring, "run_hogql") as mock_run_hogql,
            patch.object(scoring, "count_inference_anchors", return_value=0) as count,
        ):
            mock_run_hogql.return_value = HogQLResult(columns=[], rows=[])
            _fetch_inference_rows(
                team=self.team,
                pipeline=pipeline,
                feature_sql=_ANCHORS_FEATURE_SQL,
                cutoff_ts=1_700_000_000,
                user=self.user,
            )
        assert mock_run_hogql.call_args.kwargs["query"].values["cutoff_ts"] == 1_700_000_000
        assert count.call_args.kwargs["cutoff_ts"] == 1_700_000_000

    def test_inference_rows_that_drop_an_anchor_fail_the_run(self):
        # An inner join or a WHERE on the joined table drops people with every returned row
        # still looking valid; the anchor count is the only thing that notices.
        pipeline = self._make_pipeline()
        two_rows = HogQLResult(columns=["distinct_id"], rows=[["p1"], ["p2"]])
        with (
            patch.object(scoring, "run_hogql", return_value=two_rows),
            patch.object(scoring, "count_inference_anchors", return_value=3),
        ):
            with self.assertRaises(InferenceRunError):
                _fetch_inference_rows(
                    team=self.team, pipeline=pipeline, feature_sql=_ANCHORS_FEATURE_SQL, cutoff_ts=None, user=self.user
                )
