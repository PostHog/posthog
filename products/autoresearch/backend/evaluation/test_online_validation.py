from datetime import UTC, date, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone as django_timezone

import numpy as np
from parameterized import parameterized

from posthog.models.user import User

from products.autoresearch.backend.evaluation import online_validation
from products.autoresearch.backend.evaluation.online_validation import (
    OUTCOME_INGESTION_GRACE,
    STALE_RUN_AFTER,
    OnlineValidationError,
    _compute_validation_metrics,
    _expected_calibration_error,
    _lift_at_k,
    _update_model_realized_metrics,
    find_pending_validation_dates,
    run_online_validation_for_pipeline,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.query import HogQLResult
from products.autoresearch.backend.testing import TeamScopedTestMixin

FROZEN_NOW = "2026-09-11T12:00:00Z"


class TestComputeValidationMetrics(SimpleTestCase):
    def _predictions(self) -> dict[str, float]:
        return {"user-1": 0.9, "user-2": 0.8, "user-3": 0.4, "user-4": 0.3, "user-5": 0.1}

    def test_returns_base_counts(self):
        metrics = _compute_validation_metrics(self._predictions(), frozenset(["user-1", "user-2"]))
        assert metrics["n_scored"] == 5
        assert metrics["n_positive"] == 2
        assert metrics["n_negative"] == 3
        assert metrics["base_rate"] == 0.4
        assert 0.0 <= metrics["brier_score"] <= 1.0
        assert 0.0 <= metrics["calibration_error"] <= 1.0
        assert metrics["lift_at_10"] > 0.0

    @parameterized.expand(
        [
            ("perfect_separation", {"high-1": 0.95, "high-2": 0.90, "low-1": 0.05, "low-2": 0.10}, 1.0),
            ("reversed_scores", {"high-1": 0.05, "high-2": 0.10, "low-1": 0.95, "low-2": 0.90}, 0.0),
        ]
    )
    def test_realized_auc(self, _name, preds, expected_auc):
        metrics = _compute_validation_metrics(preds, frozenset(["high-1", "high-2"]))
        assert metrics["realized_auc"] == expected_auc

    @parameterized.expand(
        [
            ("no_positives", frozenset()),
            ("no_negatives", frozenset(["user-1", "user-2"])),
        ]
    )
    def test_single_class_skips_only_the_auc(self, _name, labels):
        metrics = _compute_validation_metrics({"user-1": 0.5, "user-2": 0.6}, labels)
        assert metrics["warning"] == "single_class_no_auc"
        assert "realized_auc" not in metrics
        assert 0.0 <= metrics["brier_score"] <= 1.0
        assert 0.0 <= metrics["calibration_error"] <= 1.0
        assert "lift_at_10" in metrics


class TestExpectedCalibrationError(SimpleTestCase):
    def test_perfect_calibration_zero_ece(self):
        ece = _expected_calibration_error(np.array([1, 0, 1, 0]), np.array([0.5, 0.5, 0.5, 0.5]))
        assert abs(ece) < 1e-6

    def test_overconfident_model_high_ece(self):
        ece = _expected_calibration_error(np.array([0, 0, 0, 0]), np.array([0.9, 0.9, 0.9, 0.9]))
        assert ece > 0.5


class TestLiftAtK(SimpleTestCase):
    def test_perfect_ranking_lift_at_50_is_2(self):
        lift = _lift_at_k(np.array([1, 1, 0, 0]), np.array([0.9, 0.8, 0.2, 0.1]), k=0.5)
        assert abs(lift - 2.0) < 1e-6

    def test_no_positives_returns_zero(self):
        assert _lift_at_k(np.array([0, 0, 0]), np.array([0.9, 0.5, 0.1]), k=0.5) == 0.0

    def test_lift_normalizes_by_the_rows_actually_selected(self):
        # 11 users at k=0.1 selects 2 rows (ceil), so the random baseline is 2/11 of the
        # positives, not 1.1.
        y_true = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        y_score = np.array([0.99, 0.98, 0.5, 0.4, 0.3, 0.2, 0.1, 0.09, 0.08, 0.07, 0.06])
        assert abs(_lift_at_k(y_true, y_score, k=0.1) - 5.5) < 1e-6

    def test_ties_at_the_boundary_are_split_fractionally_whatever_the_row_order(self):
        y_true = np.array([1, 0, 0, 0, 1, 0])
        y_score = np.full(6, 0.5)
        assert abs(_lift_at_k(y_true, y_score, k=0.5) - 1.0) < 1e-6
        assert abs(_lift_at_k(y_true[::-1], y_score, k=0.5) - 1.0) < 1e-6


def _make_pipeline(team, user: User | None, horizon_days: int = 7) -> AutoresearchPipeline:
    return AutoresearchPipeline.objects.create(
        team=team,
        created_by=user,
        name="Test pipeline",
        target_event="$pageview",
        horizon_days=horizon_days,
        iteration_budget=50,
        iteration_budget_remaining=50,
    )


def _make_model(pipeline: AutoresearchPipeline) -> AutoresearchModel:
    return AutoresearchModel.objects.create(
        pipeline=pipeline,
        role=AutoresearchModel.Role.CHAMPION,
        model_recipe={"stub": True},
        recipe_hash="abc123",
        holdout_score=0.75,
    )


def _inference_run(
    pipeline: AutoresearchPipeline,
    model: AutoresearchModel | None,
    prediction_date: date,
    rows_scored: int,
    *,
    horizon_days: int = 7,
    status: str = AutoresearchRun.Status.COMPLETED,
) -> AutoresearchRun:
    return AutoresearchRun.objects.create(
        pipeline=pipeline,
        model=model,
        run_type=AutoresearchRun.RunType.INFERENCE,
        status=status,
        rows_scored=rows_scored,
        completed_at=django_timezone.now(),
        metrics={"prediction_date": prediction_date.isoformat(), "horizon_days": horizon_days},
    )


def _validation_run(
    pipeline: AutoresearchPipeline,
    prediction_date: date,
    status: str,
    *,
    started_at: datetime | None = None,
    horizon_days: int = 7,
    counts: dict[str, int] | None = None,
) -> AutoresearchRun:
    metrics: dict = {"prediction_date": prediction_date.isoformat(), "horizon_days": horizon_days}
    if counts is not None:
        metrics["per_model"] = {model_id: {"n_scored": n} for model_id, n in counts.items()}
    return AutoresearchRun.objects.create(
        pipeline=pipeline,
        run_type=AutoresearchRun.RunType.VALIDATION,
        status=status,
        started_at=started_at or django_timezone.now(),
        metrics=metrics,
    )


class TestUpdateModelRealizedMetrics(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.model = _make_model(_make_pipeline(self.team, self.user))

    def test_clears_preliminary_on_first_validation(self):
        assert self.model.is_preliminary is True
        _update_model_realized_metrics(
            self.model, {"realized_auc": 0.82, "calibration_error": 0.05}, prediction_date=date(2026, 9, 1)
        )
        updated = AutoresearchModel.objects.get(pk=self.model.pk)
        assert updated.is_preliminary is False
        assert updated.realized_score == 0.82
        assert updated.calibration_error == 0.05
        assert updated.metrics["realized"]["prediction_date"] == "2026-09-01"

    @parameterized.expand(
        [
            ("newer_date_replaces", date(2026, 9, 2), 0.85),
            ("older_retry_keeps_the_newer_evidence", date(2026, 8, 30), 0.80),
        ]
    )
    def test_model_level_score_follows_the_newest_date(self, _name, second_date, expected_score):
        _update_model_realized_metrics(self.model, {"realized_auc": 0.80}, prediction_date=date(2026, 9, 1))
        _update_model_realized_metrics(self.model, {"realized_auc": 0.85}, prediction_date=second_date)
        self.model.refresh_from_db()
        assert self.model.realized_score == expected_score
        assert self.model.is_preliminary is False

    def test_no_auc_leaves_preliminary_unchanged(self):
        _update_model_realized_metrics(self.model, {"warning": "single_class_no_auc"}, prediction_date=date(2026, 9, 1))
        self.model.refresh_from_db()
        assert self.model.is_preliminary is True
        assert self.model.realized_score is None


@time_machine.travel(FROZEN_NOW, tick=False)
class TestFindPendingValidationDates(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.pipeline = _make_pipeline(self.team, self.user)
        self.model = _make_model(self.pipeline)

    def test_matured_dates_come_from_the_inference_runs(self):
        matured = date(2026, 9, 1)
        _inference_run(self.pipeline, self.model, matured, rows_scored=5)
        _inference_run(self.pipeline, self.model, matured, rows_scored=8)
        # Not matured: 2026-09-05 + 7 days is after the frozen 2026-09-11.
        _inference_run(self.pipeline, self.model, date(2026, 9, 5), rows_scored=3)
        # Matured under the horizon the run recorded, not the pipeline's current 7 days.
        _inference_run(self.pipeline, self.model, date(2026, 9, 6), rows_scored=2, horizon_days=3)
        # Nothing emitted, and a run whose model was deleted: neither can be validated.
        _inference_run(self.pipeline, self.model, date(2026, 8, 20), rows_scored=0)
        _inference_run(self.pipeline, None, date(2026, 8, 21), rows_scored=4)

        pending = find_pending_validation_dates(self.pipeline)

        assert [(p.prediction_date, p.horizon_days, p.expected_rows_by_model) for p in pending] == [
            (matured, 7, {str(self.model.pk): 8}),
            (date(2026, 9, 6), 3, {str(self.model.pk): 2}),
        ]
        assert pending[0].window_start == datetime(2026, 9, 1, tzinfo=UTC)
        assert pending[0].window_end == datetime(2026, 9, 8, tzinfo=UTC)

    def test_maturity_waits_for_the_ingestion_grace(self):
        _inference_run(self.pipeline, self.model, date(2026, 9, 4), rows_scored=5)
        window_end = datetime(2026, 9, 11, tzinfo=UTC)
        with time_machine.travel(window_end + OUTCOME_INGESTION_GRACE - timedelta(minutes=1), tick=False):
            assert find_pending_validation_dates(self.pipeline) == []
        with time_machine.travel(window_end + OUTCOME_INGESTION_GRACE, tick=False):
            assert [p.prediction_date for p in find_pending_validation_dates(self.pipeline)] == [date(2026, 9, 4)]

    @parameterized.expand(
        [
            ("fresh_run_waits", timedelta(hours=1), False),
            ("abandoned_run_is_ignored", STALE_RUN_AFTER + timedelta(minutes=1), True),
        ]
    )
    def test_a_date_still_being_scored_waits(self, _name, age, expect_pending):
        matured = date(2026, 9, 1)
        _inference_run(self.pipeline, self.model, matured, rows_scored=5)
        in_flight = _inference_run(
            self.pipeline, self.model, matured, rows_scored=0, status=AutoresearchRun.Status.RUNNING
        )
        AutoresearchRun.objects.filter(pk=in_flight.pk).update(created_at=django_timezone.now() - age)

        assert [p.prediction_date for p in find_pending_validation_dates(self.pipeline)] == (
            [matured] if expect_pending else []
        )

    def test_models_scored_under_different_horizons_validate_as_separate_groups(self):
        # A 14-day replacement scored the same date as the 7-day champion: only the 7-day
        # window has closed by the frozen 2026-09-11, and each group carries its own models.
        other = AutoresearchModel.objects.create(
            pipeline=self.pipeline, role=AutoresearchModel.Role.CHALLENGER, model_recipe={"stub": True}, recipe_hash="x"
        )
        _inference_run(self.pipeline, self.model, date(2026, 9, 1), rows_scored=5, horizon_days=7)
        _inference_run(self.pipeline, other, date(2026, 9, 1), rows_scored=3, horizon_days=14)

        pending = find_pending_validation_dates(self.pipeline)

        assert [(p.horizon_days, p.expected_rows_by_model) for p in pending] == [(7, {str(self.model.pk): 5})]

    def test_a_validated_date_becomes_pending_again_when_its_inference_runs_change(self):
        matured = date(2026, 9, 1)
        _inference_run(self.pipeline, self.model, matured, rows_scored=5)
        _validation_run(self.pipeline, matured, AutoresearchRun.Status.COMPLETED, counts={str(self.model.pk): 5})
        assert find_pending_validation_dates(self.pipeline) == []

        _inference_run(self.pipeline, self.model, matured, rows_scored=6)

        assert [p.expected_rows_by_model for p in find_pending_validation_dates(self.pipeline)] == [
            {str(self.model.pk): 6}
        ]

    @parameterized.expand(
        [
            ("completed_blocks", AutoresearchRun.Status.COMPLETED, timedelta(0), False),
            ("failed_is_retried", AutoresearchRun.Status.FAILED, timedelta(0), True),
            ("fresh_claim_blocks", AutoresearchRun.Status.RUNNING, timedelta(hours=1), False),
            ("stale_claim_is_retried", AutoresearchRun.Status.RUNNING, STALE_RUN_AFTER + timedelta(minutes=1), True),
        ]
    )
    def test_existing_validation_runs(self, _name, status, age, expect_pending):
        matured = date(2026, 9, 1)
        _inference_run(self.pipeline, self.model, matured, rows_scored=5)
        _validation_run(
            self.pipeline, matured, status, started_at=django_timezone.now() - age, counts={str(self.model.pk): 5}
        )

        pending = find_pending_validation_dates(self.pipeline)

        assert [p.prediction_date for p in pending] == ([matured] if expect_pending else [])


def _fake_hogql(
    *,
    predictions: list[list[object]],
    labels: list[list[object]],
    fail_labels_once: bool = False,
) -> MagicMock:
    """Answer the prediction query with ``predictions`` and the label query with ``labels``, recording each call."""
    state = {"labels_failed": False}

    def side_effect(*, team, query, user, execution_mode):
        if "argMax" in query.query:
            return HogQLResult(columns=["model_id", "person_id", "p_y", "emitted_role"], rows=predictions)
        if fail_labels_once and not state["labels_failed"]:
            state["labels_failed"] = True
            raise RuntimeError("clickhouse unavailable")
        return HogQLResult(columns=["person_id"], rows=labels)

    return MagicMock(side_effect=side_effect)


@time_machine.travel(FROZEN_NOW, tick=False)
class TestRunOnlineValidationForPipeline(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.pipeline = _make_pipeline(self.team, self.user)
        self.champion = _make_model(self.pipeline)
        self.prediction_date = date(2026, 9, 1)
        _inference_run(self.pipeline, self.champion, self.prediction_date, rows_scored=4)

    def _prediction_rows(self, n: int) -> list[list[object]]:
        scores = [0.9, 0.8, 0.2, 0.1, 0.5]
        return [[str(self.champion.pk), f"user-{i}", scores[i], "champion"] for i in range(n)]

    def test_validates_a_matured_date_and_records_the_evidence(self):
        hogql = _fake_hogql(predictions=self._prediction_rows(4), labels=[["user-0"], ["user-1"]])

        with patch.object(online_validation, "run_hogql", hogql):
            runs = run_online_validation_for_pipeline(self.pipeline)

        assert [r.status for r in runs] == [AutoresearchRun.Status.COMPLETED]
        run = runs[0]
        assert run.rows_scored == 4
        assert run.metrics["prediction_date"] == "2026-09-01"
        assert run.metrics["realized_labels_count"] == 2
        per_model = run.metrics["per_model"][str(self.champion.pk)]
        assert per_model["emitted_role"] == "champion"
        assert per_model["model_role"] == "champion"
        assert per_model["realized_auc"] == 1.0
        self.champion.refresh_from_db()
        assert self.champion.realized_score == 1.0
        assert self.champion.is_preliminary is False
        assert self.champion.metrics["realized"]["prediction_date"] == "2026-09-01"
        assert find_pending_validation_dates(self.pipeline) == []

        prediction_call, label_call = hogql.call_args_list
        assert prediction_call.kwargs["user"] == self.user
        assert prediction_call.kwargs["query"].values["limit"] == 5
        assert prediction_call.kwargs["query"].values["model_ids"] == (str(self.champion.pk),)
        assert prediction_call.kwargs["query"].values["emitted_from"] == datetime(2026, 9, 1, tzinfo=UTC)
        assert label_call.kwargs["query"].values["window_start"] == datetime(2026, 9, 1, tzinfo=UTC)
        assert label_call.kwargs["query"].values["window_end"] == datetime(2026, 9, 8, tzinfo=UTC)
        assert label_call.kwargs["query"].values["limit"] == 5
        assert "LIMIT {limit}" in label_call.kwargs["query"].query

    @parameterized.expand(
        [
            ("fewer_rows_than_emitted", 3, "Found 3 of the 4 predictions"),
            ("more_rows_than_emitted", 5, "more rows than the inference runs account for (4)"),
        ]
    )
    def test_a_count_mismatch_fails_the_date_and_keeps_it_pending(self, _name, n_rows, error_fragment):
        hogql = _fake_hogql(predictions=self._prediction_rows(n_rows), labels=[["user-0"]])

        with patch.object(online_validation, "run_hogql", hogql):
            runs = run_online_validation_for_pipeline(self.pipeline)

        assert [r.status for r in runs] == [AutoresearchRun.Status.FAILED]
        assert error_fragment in runs[0].error
        assert "per_model" not in runs[0].metrics
        self.champion.refresh_from_db()
        assert self.champion.realized_score is None
        assert [p.prediction_date for p in find_pending_validation_dates(self.pipeline)] == [self.prediction_date]

    def test_a_query_failure_fails_that_date_and_continues_to_the_next(self):
        second_date = date(2026, 9, 2)
        _inference_run(self.pipeline, self.champion, second_date, rows_scored=4)
        hogql = _fake_hogql(predictions=self._prediction_rows(4), labels=[["user-0"]], fail_labels_once=True)

        with patch.object(online_validation, "run_hogql", hogql):
            runs = run_online_validation_for_pipeline(self.pipeline)

        assert [(r.metrics["prediction_date"], r.status) for r in runs] == [
            ("2026-09-01", AutoresearchRun.Status.FAILED),
            ("2026-09-02", AutoresearchRun.Status.COMPLETED),
        ]
        assert "Realized labels query failed" in runs[0].error

    @parameterized.expand(
        [
            ("completed", AutoresearchRun.Status.COMPLETED),
            ("still_running", AutoresearchRun.Status.RUNNING),
        ]
    )
    def test_an_inference_run_appearing_mid_validation_fails_the_date(self, _name, status):
        challenger = AutoresearchModel.objects.create(
            pipeline=self.pipeline,
            role=AutoresearchModel.Role.CHALLENGER,
            model_recipe={"stub": True},
            recipe_hash="def",
        )
        hogql = _fake_hogql(predictions=self._prediction_rows(4), labels=[["user-0"]])
        inner = hogql.side_effect

        def complete_a_rescore_then_answer(**kwargs):
            if "argMax" not in kwargs["query"].query:
                _inference_run(self.pipeline, challenger, self.prediction_date, rows_scored=4, status=status)
            return inner(**kwargs)

        with patch.object(online_validation, "run_hogql", MagicMock(side_effect=complete_a_rescore_then_answer)):
            runs = run_online_validation_for_pipeline(self.pipeline)

        assert [r.status for r in runs] == [AutoresearchRun.Status.FAILED]
        assert "changed while it was being validated" in runs[0].error
        self.champion.refresh_from_db()
        assert self.champion.realized_score is None
        if status == AutoresearchRun.Status.COMPLETED:
            pending = find_pending_validation_dates(self.pipeline)
            assert [set(p.expected_rows_by_model) for p in pending] == [{str(self.champion.pk), str(challenger.pk)}]

    def test_a_pipeline_without_a_creator_fails_before_any_query(self):
        self.pipeline.created_by = None
        self.pipeline.save(update_fields=["created_by"])
        hogql = _fake_hogql(predictions=[], labels=[])

        with patch.object(online_validation, "run_hogql", hogql), self.assertRaises(OnlineValidationError):
            run_online_validation_for_pipeline(self.pipeline)

        hogql.assert_not_called()
        assert not AutoresearchRun.objects.filter(run_type=AutoresearchRun.RunType.VALIDATION).exists()
