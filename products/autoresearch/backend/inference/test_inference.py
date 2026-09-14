from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.capture import CaptureInternalResult

from products.autoresearch.backend.dataset.labeling import PREDICTION_EVENT_NAME
from products.autoresearch.backend.inference import scoring
from products.autoresearch.backend.inference.sandbox import _MATERIALIZE_ROW_LIMIT, SandboxScoreResult
from products.autoresearch.backend.inference.scoring import (
    InferenceRunError,
    ScoredPopulation,
    ScoringWindow,
    _estimator_for,
    _fetch_inference_rows,
    _fetch_stub_feature_rows,
    _fetch_training_rows,
    _fit_on_training_predict_on_inference,
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
            (
                "one_event_stored_with_a_warning",
                None,
                lambda events: CaptureInternalResult(
                    status_code=200,
                    ok=[events[0]["event_uuid"]],
                    warnings=[events[1]["event_uuid"]],
                    results={events[1]["event_uuid"]: {"result": "warning", "message": "person processing disabled"}},
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


@time_machine.travel("2026-09-11T12:00:00Z", tick=False)
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

    def test_the_dry_run_route_applies_the_same_date_guards(self):
        pipeline, model = self._pipeline_and_model(
            inference_population={
                "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]
            }
        )
        model.artifact_prefix = "tasks/autoresearch/team_1/pipeline_x/run_y"
        model.save(update_fields=["artifact_prefix"])
        with patch.object(scoring, "score_via_sandbox") as sandbox:
            with self.assertRaises(InferenceRunError):
                score_population(
                    team=self.team,
                    pipeline=pipeline,
                    model=model,
                    window=ScoringWindow.for_date(date.today() - timedelta(days=3)),
                    user=self.user,
                )
        sandbox.assert_not_called()

    def test_backfilling_a_past_date_leaves_last_scored_at_alone(self):
        # Advancing the watermark on a backfill makes the coordinator treat the pipeline as
        # freshly scored, suppressing today's live run for a whole cadence.
        pipeline, model = self._pipeline_and_model()
        model.artifact_prefix = "tasks/autoresearch/team_1/pipeline_x/run_y"
        model.save(update_fields=["artifact_prefix"])
        sandbox_result = SandboxScoreResult(
            scored_rows=[{"distinct_id": str(uuid4()), "p_y": 0.4}], holdout_auc=0.6, n_train=1, n_features=1
        )
        with (
            patch.object(scoring, "score_via_sandbox", return_value=sandbox_result) as sandbox,
            patch.object(scoring, "capture_batch_internal", _capture_accepting_everything()) as capture,
        ):
            run = run_inference_for_pipeline(
                pipeline=pipeline, model=model, prediction_date=date.today() - timedelta(days=30)
            )

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert capture.call_args.kwargs["process_person_profile"] is False
        assert isinstance(sandbox.call_args.kwargs["cutoff_ts"], int)
        pipeline.refresh_from_db()
        assert pipeline.last_scored_at is None

    @parameterized.expand([("stub", _STUB_RECIPE), ("anchors", _ANCHORS_RECIPE)])
    def test_backfilling_a_recipe_only_champion_is_refused(self, _name, recipe):
        pipeline, model = self._pipeline_and_model()
        model.model_recipe = recipe
        model.save(update_fields=["model_recipe"])
        with (
            patch.object(scoring, "_fetch_stub_feature_rows") as stub,
            patch.object(scoring, "_score_via_anchors") as anchors,
        ):
            with self.assertRaises(InferenceRunError):
                run_inference_for_pipeline(
                    pipeline=pipeline, model=model, prediction_date=date.today() - timedelta(days=30)
                )
        stub.assert_not_called()
        anchors.assert_not_called()


@time_machine.travel("2026-09-11T12:00:00Z", tick=False)
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
                    team=self.team, pipeline=pipeline, model=model, window=ScoringWindow.for_date(), user=self.user
                )
        anchored.assert_not_called()
        hogql.assert_not_called()

    def test_dry_run_and_live_run_take_the_same_route(self):
        pipeline, model = self._pipeline_and_model(_ANCHORS_RECIPE)
        scored = ScoredPopulation(rows=[{"distinct_id": "p1", "p_y": 0.5}], holdout_auc=0.66)
        with patch.object(scoring, "_score_via_anchors", return_value=scored) as anchored:
            result = score_population(
                team=self.team, pipeline=pipeline, model=model, window=ScoringWindow.for_date(), user=self.user
            )
        assert result == scored
        anchored.assert_called_once()

    @parameterized.expand([("bundle", "score_via_sandbox"), ("recipe", "_score_via_anchors")])
    def test_live_run_binds_every_query_to_the_start_of_the_day(self, _name, scorer):
        # Queries that each evaluate their own now() disagree on the anchors whenever a person
        # becomes eligible between them, and a retry under the same event UUIDs would score a
        # different population than the attempt it repeats.
        pipeline, model = self._pipeline_and_model(_ANCHORS_RECIPE)
        if scorer == "score_via_sandbox":
            model.artifact_prefix = "tasks/autoresearch/team_1/pipeline_x/run_y"
            model.save(update_fields=["artifact_prefix"])
        with patch.object(scoring, scorer) as mocked:
            score_population(
                team=self.team, pipeline=pipeline, model=model, window=ScoringWindow.for_date(), user=self.user
            )
        assert mocked.call_args.kwargs["cutoff_ts"] == int(datetime(2026, 9, 11, tzinfo=UTC).timestamp())

    def test_a_retry_hours_later_gets_the_same_window(self):
        first = ScoringWindow.for_date()
        with time_machine.travel("2026-09-11T19:30:00Z", tick=False):
            retry = ScoringWindow.for_date()
        assert (retry.cutoff_ts, retry.is_backfill) == (first.cutoff_ts, first.is_backfill)

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
    def _make_pipeline(self, inference_population: dict, target_event: str = "$pageview") -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test",
            target_event=target_event,
            horizon_days=7,
            inference_population=inference_population,
        )

    def _sent(self, mock_run: MagicMock) -> tuple[str, dict]:
        query = mock_run.call_args_list[0].kwargs["query"]
        return query.query, query.values

    @staticmethod
    def _feature_then_count(rows: list[list], count: int) -> list[HogQLResult]:
        return [HogQLResult(columns=["distinct_id"], rows=rows), HogQLResult(columns=["count()"], rows=[[count]])]

    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_population_is_applied_inside_the_bounded_query(self, mock_run: MagicMock):
        # Filtering the rows in Python after the bound meant a team with more people than the
        # cap failed every stub run, however small the configured population.
        pipeline = self._make_pipeline(
            {"properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "pro"}]}
        )
        mock_run.side_effect = self._feature_then_count([["user-1"], ["user-3"]], count=2)

        rows = _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)

        assert {r["distinct_id"] for r in rows} == {"user-1", "user-3"}
        sql, values = self._sent(mock_run)
        assert "f.distinct_id IN (SELECT DISTINCT person_id FROM events WHERE" in sql
        assert "person.properties[{pop_k_0}] = {pop_0}" in sql
        assert values["pop_0"] == "pro"
        assert sql.rstrip().endswith(f"LIMIT {_MATERIALIZE_ROW_LIMIT}")
        count_query = mock_run.call_args_list[1].kwargs["query"]
        assert count_query.query.startswith("SELECT count() FROM (SELECT DISTINCT person_id FROM events WHERE")
        assert count_query.values["pop_0"] == "pro"
        assert all(call.kwargs["user"] == self.user for call in mock_run.call_args_list)

    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_empty_population_restricts_to_identified_users_within_the_window(self, mock_run: MagicMock):
        # v1 scores identified users only; the scan must skip the product's own event, or a
        # scored person stays eligible forever, and a future-dated event must not count.
        pipeline = self._make_pipeline({})
        mock_run.side_effect = self._feature_then_count([["user-1"]], count=1)

        _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)

        sql, values = self._sent(mock_run)
        assert "person.is_identified" in sql
        assert f"event != '{PREDICTION_EVENT_NAME}'" in sql
        assert "timestamp < now()" in sql
        assert values["lookback"] == 30

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
        # Template populations carry semantic kind specs; the stub path must compile them or
        # a template pipeline silently scores all identified users.
        pipeline = self._make_pipeline(population, target_event="downloaded_file")
        mock_run.side_effect = self._feature_then_count([["user-1"]], count=1)

        _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)

        sql, _values = self._sent(mock_run)
        for fragment in expected_fragments:
            assert fragment in sql

    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_uncompilable_population_kind_fails_before_any_query(self, mock_run: MagicMock):
        # Widening to "all identified users" is the failure mode being prevented.
        pipeline = self._make_pipeline({"kind": "ever_performed_event"})
        with self.assertRaises(ValueError):
            _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)
        mock_run.assert_not_called()

    @parameterized.expand(
        [
            ("blank_identifier", [["user-1"], [""]], 2),
            ("duplicate_person", [["user-1"], ["user-1"]], 2),
            ("dropped_member", [["user-1"]], 2),
        ]
    )
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_rows_that_do_not_key_one_person_fail_the_run(self, _name, rows, population_count, mock_run: MagicMock):
        # A blank identifier was silently dropped and a duplicate emitted the same event UUID
        # twice; either way the run completed and reported a row count nobody received. Stub
        # SQL that drops a member leaves valid rows behind, so only the population count notices.
        pipeline = self._make_pipeline({})
        mock_run.side_effect = self._feature_then_count(rows, count=population_count)
        with self.assertRaises(InferenceRunError):
            _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)

    @parameterized.expand([("full_page", False), ("has_more", True)])
    @patch("products.autoresearch.backend.inference.scoring.run_hogql")
    def test_a_result_that_fills_the_bound_fails_the_run(self, _name: str, has_more: bool, mock_run: MagicMock):
        # HogQL silently caps an unbounded query at 100 rows, and a full result is almost
        # certainly truncated; scoring the partial set would skip users while the cadence advanced.
        pipeline = self._make_pipeline({})
        n = 1 if has_more else _MATERIALIZE_ROW_LIMIT
        mock_run.return_value = HogQLResult(
            columns=["distinct_id"], rows=[[f"person-{i}"] for i in range(n)], has_more=has_more
        )
        with self.assertRaises(InferenceRunError):
            _fetch_stub_feature_rows(team=self.team, pipeline=pipeline, recipe=_STUB_RECIPE, user=self.user)


class TestResolveDistinctIds(TeamScopedTestMixin, BaseTest):
    def _pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team, created_by=self.user, name="Identity", target_event="$pageview", horizon_days=7
        )

    @patch("products.autoresearch.backend.inference.scoring.get_persons_by_uuids")
    def test_maps_each_person_to_one_current_distinct_id_from_personhog(self, mock_persons: MagicMock):
        # An id read off event history can belong to someone else after a merge or split, so
        # the mapping has to come from the identity store, and a person with no id stays out.
        with_id, without_id, not_a_uuid = str(uuid4()), str(uuid4()), "person-1"
        mock_persons.return_value = [
            MagicMock(uuid=with_id, distinct_ids=["real-id"]),
            MagicMock(uuid=without_id, distinct_ids=[]),
        ]

        mapping = _resolve_distinct_ids(
            team=self.team, pipeline=self._pipeline(), person_ids=[with_id, without_id, not_a_uuid], user=self.user
        )

        assert mapping == {with_id: "real-id"}
        assert mock_persons.call_args.args == (self.team.pk, [with_id, without_id])
        assert mock_persons.call_args.kwargs == {"distinct_id_limit": 1}

    @patch("products.autoresearch.backend.inference.scoring.get_persons_by_uuids", side_effect=RuntimeError("down"))
    def test_identity_store_failure_fails_the_run(self, _mock: MagicMock):
        # Emitting every prediction person-less would leave the output property unset for the
        # whole population while the run reported success.
        with self.assertRaises(InferenceRunError):
            _resolve_distinct_ids(team=self.team, pipeline=self._pipeline(), person_ids=[str(uuid4())], user=self.user)


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
            patch.object(scoring, "count_training_anchors", return_value=3),
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

    @parameterized.expand(
        [
            ("duplicate_person", [["p1", 1, 0, 1], ["p1", 2, 1, 2]]),
            ("unlabeled_row", [["p1", 1, 0, 1], ["p2", 2, None, None]]),
        ]
    )
    def test_training_rows_that_do_not_key_one_labeled_person_fail_the_run(self, _name, rows):
        pipeline = self._make_pipeline()
        result = HogQLResult(columns=["distinct_id", "events_total", "__label", "__fold"], rows=rows)
        with (
            patch.object(scoring, "run_hogql", return_value=result),
            patch.object(scoring, "count_training_anchors", return_value=len(rows)),
        ):
            with self.assertRaises(InferenceRunError):
                _fetch_training_rows(
                    team=self.team, pipeline=pipeline, feature_sql=_ANCHORS_FEATURE_SQL, user=self.user
                )

    def test_training_rows_that_drop_a_labeled_anchor_fail_the_run(self):
        # A join that loses anchors leaves unique, labeled rows behind, so only the count
        # against the labeled anchors notices the selection bias.
        pipeline = self._make_pipeline()
        result = HogQLResult(columns=["distinct_id", "events_total", "__label", "__fold"], rows=[["p1", 1, 0, 1]])
        with (
            patch.object(scoring, "run_hogql", return_value=result),
            patch.object(scoring, "count_training_anchors", return_value=2),
        ):
            with self.assertRaises(InferenceRunError):
                _fetch_training_rows(
                    team=self.team, pipeline=pipeline, feature_sql=_ANCHORS_FEATURE_SQL, user=self.user
                )

    @parameterized.expand(
        [
            ("duplicate_columns", ["distinct_id", "n", "n"], ["p1", 1, 2]),
            ("too_many_columns_of_any_type", ["distinct_id", "a", "b", "c"], ["p1", "x", "y", "z"]),
        ]
    )
    def test_malformed_output_columns_fail_the_run(self, _name, columns, row):
        # A column set is checked as it is read: the numeric filter would discard string
        # columns after they were materialized, so a cap applied only to it never fires.
        pipeline = self._make_pipeline()
        result = HogQLResult(columns=columns, rows=[row])
        with (
            patch.object(scoring, "_MAX_FEATURE_COLS", 2),
            patch.object(scoring, "run_hogql", return_value=result),
            patch.object(scoring, "count_inference_anchors", return_value=1),
        ):
            with self.assertRaises(InferenceRunError):
                _fetch_inference_rows(
                    team=self.team, pipeline=pipeline, feature_sql=_ANCHORS_FEATURE_SQL, cutoff_ts=None, user=self.user
                )

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


class TestRecipeFit(SimpleTestCase):
    @parameterized.expand(
        [
            ("seeded_from_the_pipeline", {}, 1234),
            ("recipe_seed_wins", {"random_state": 7}, 7),
        ]
    )
    def test_stochastic_estimator_gets_a_stable_seed(self, _name, params, expected):
        # A retry after a partial capture refits; two fits that disagree leave one cadence
        # with scores from both under the same event UUIDs.
        recipe = {"model_class": "sklearn.ensemble.RandomForestClassifier", "model_params": params}
        assert _estimator_for(recipe, seed=1234).random_state == expected

    def test_estimator_never_takes_every_core(self):
        # The fit runs in the worker process, so an agent's n_jobs=-1 would starve everything else on it.
        recipe = {"model_class": "sklearn.ensemble.RandomForestClassifier", "model_params": {"n_jobs": -1}}
        assert _estimator_for(recipe, seed=1).n_jobs == 1

    def test_training_row_order_does_not_change_the_fit(self):
        recipe = {
            "model_class": "sklearn.ensemble.RandomForestClassifier",
            "model_params": {"n_estimators": 5, "max_depth": 2},
        }
        training_rows = [
            {
                "distinct_id": f"t{i:02d}",
                "x": i % 8,
                "y": (i * 3) % 8,
                "__label": int((i % 8 > 3) ^ ((i * 3) % 8 > 3)),
                "__fold": i % 5,
            }
            for i in range(40)
        ]
        inference_rows = [{"distinct_id": f"s{i}", "x": i, "y": (i * 3) % 8} for i in range(8)]
        forward = _fit_on_training_predict_on_inference(
            training_rows=training_rows, inference_rows=inference_rows, recipe=recipe, pipeline_id="p"
        )
        backward = _fit_on_training_predict_on_inference(
            training_rows=training_rows[::-1], inference_rows=inference_rows, recipe=recipe, pipeline_id="p"
        )
        assert [r["p_y"] for r in forward.rows] == [r["p_y"] for r in backward.rows]

    def test_too_many_feature_columns_fail_before_any_matrix_is_built(self):
        rows = [{"distinct_id": f"p{i}", "a": 1, "b": 2, "c": 3, "__label": i % 2, "__fold": i % 5} for i in range(10)]
        with patch.object(scoring, "_MAX_FEATURE_COLS", 2):
            with self.assertRaises(InferenceRunError):
                _fit_on_training_predict_on_inference(
                    training_rows=rows, inference_rows=rows[:2], recipe=_ANCHORS_RECIPE, pipeline_id="p"
                )
