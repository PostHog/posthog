from datetime import date, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

import numpy as np

from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.online_validation import (
    _compute_validation_metrics,
    _expected_calibration_error,
    _find_mature_unvalidated_dates,
    _lift_at_k,
    _update_model_realized_metrics,
    run_online_validation_for_pipeline,
)


class TestComputeValidationMetrics(BaseTest):
    def _predictions(self) -> dict[str, float]:
        return {
            "user-1": 0.9,
            "user-2": 0.8,
            "user-3": 0.4,
            "user-4": 0.3,
            "user-5": 0.1,
        }

    def test_returns_base_counts(self):
        preds = self._predictions()
        labels = frozenset(["user-1", "user-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert metrics["n_scored"] == 5
        assert metrics["n_positive"] == 2
        assert metrics["n_negative"] == 3
        assert metrics["base_rate"] == 0.4

    def test_computes_auc_and_brier(self):
        preds = self._predictions()
        labels = frozenset(["user-1", "user-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert "realized_auc" in metrics
        assert "brier_score" in metrics
        assert 0.0 <= metrics["realized_auc"] <= 1.0
        assert 0.0 <= metrics["brier_score"] <= 1.0

    def test_perfect_separation_gives_high_auc(self):
        preds = {"high-1": 0.95, "high-2": 0.90, "low-1": 0.05, "low-2": 0.10}
        labels = frozenset(["high-1", "high-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert metrics["realized_auc"] == 1.0

    def test_reversed_scores_give_low_auc(self):
        preds = {"high-1": 0.05, "high-2": 0.10, "low-1": 0.95, "low-2": 0.90}
        labels = frozenset(["high-1", "high-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert metrics["realized_auc"] == 0.0

    def test_no_positives_returns_warning(self):
        preds = {"user-1": 0.5, "user-2": 0.6}
        metrics = _compute_validation_metrics(preds, frozenset())
        assert metrics.get("warning") == "single_class_no_auc"
        assert "realized_auc" not in metrics

    def test_no_negatives_returns_warning(self):
        preds = {"user-1": 0.5, "user-2": 0.6}
        labels = frozenset(["user-1", "user-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert metrics.get("warning") == "single_class_no_auc"

    def test_lift_at_k(self):
        preds = self._predictions()
        labels = frozenset(["user-1", "user-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert metrics["lift_at_10"] > 0.0
        assert metrics["lift_at_20"] > 0.0

    def test_calibration_error_range(self):
        preds = self._predictions()
        labels = frozenset(["user-1", "user-2"])
        metrics = _compute_validation_metrics(preds, labels)
        assert 0.0 <= metrics["calibration_error"] <= 1.0


class TestExpectedCalibrationError(BaseTest):
    def test_perfect_calibration_zero_ece(self):
        # One bin where predicted = actual rate
        y_true = np.array([1, 0, 1, 0])
        y_score = np.array([0.5, 0.5, 0.5, 0.5])
        ece = _expected_calibration_error(y_true, y_score)
        assert abs(ece) < 1e-6

    def test_overconfident_model_high_ece(self):
        y_true = np.array([0, 0, 0, 0])
        y_score = np.array([0.9, 0.9, 0.9, 0.9])
        ece = _expected_calibration_error(y_true, y_score)
        assert ece > 0.5


class TestLiftAtK(BaseTest):
    def test_perfect_ranking_lift_at_50_is_2(self):
        y_true = np.array([1, 1, 0, 0])
        y_score = np.array([0.9, 0.8, 0.2, 0.1])
        lift = _lift_at_k(y_true, y_score, k=0.5)
        assert abs(lift - 2.0) < 1e-6

    def test_no_positives_returns_zero(self):
        y_true = np.array([0, 0, 0])
        y_score = np.array([0.9, 0.5, 0.1])
        assert _lift_at_k(y_true, y_score, k=0.5) == 0.0

    def test_random_ranking_lift_near_one(self):
        rng = np.random.default_rng(42)
        n = 1000
        y_true = rng.integers(0, 2, n)
        y_score = rng.uniform(0, 1, n)
        lift = _lift_at_k(y_true, y_score, k=0.5)
        assert 0.8 <= lift <= 1.2


class TestUpdateModelRealizedMetrics(BaseTest):
    def _make_model(self) -> AutoresearchModel:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=50,
            iteration_budget_remaining=50,
        )
        return AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="abc123",
            holdout_score=0.75,
        )

    def test_clears_preliminary_on_first_validation(self):
        model = self._make_model()
        assert model.is_preliminary is True
        _update_model_realized_metrics(model, {"realized_auc": 0.82, "calibration_error": 0.05})
        model.refresh_from_db()
        assert model.is_preliminary is False
        assert model.realized_score == 0.82
        assert model.calibration_error == 0.05

    def test_updates_realized_score_on_subsequent_validation(self):
        model = self._make_model()
        _update_model_realized_metrics(model, {"realized_auc": 0.80})
        _update_model_realized_metrics(model, {"realized_auc": 0.85})
        model.refresh_from_db()
        assert model.realized_score == 0.85
        assert model.is_preliminary is False

    def test_no_auc_leaves_preliminary_unchanged(self):
        model = self._make_model()
        _update_model_realized_metrics(model, {"warning": "single_class_no_auc"})
        model.refresh_from_db()
        assert model.is_preliminary is True
        assert model.realized_score is None


class TestRunOnlineValidationForPipeline(BaseTest):
    def _make_pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            name="Test pipeline",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=50,
            iteration_budget_remaining=50,
        )

    def _make_champion(self, pipeline: AutoresearchPipeline) -> AutoresearchModel:
        return AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            model_recipe={"stub": True},
            recipe_hash="abc123",
            holdout_score=0.75,
        )

    @patch("products.autoresearch.backend.online_validation._fetch_matured_prediction_dates")
    def test_no_mature_dates_returns_empty(self, mock_dates):
        mock_dates.return_value = []
        pipeline = self._make_pipeline()
        runs = run_online_validation_for_pipeline(pipeline)
        assert runs == []

    @patch("products.autoresearch.backend.online_validation._fetch_realized_labels")
    @patch("products.autoresearch.backend.online_validation._fetch_predictions_by_model")
    @patch("products.autoresearch.backend.online_validation._fetch_matured_prediction_dates")
    def test_validates_one_mature_date(self, mock_dates, mock_preds, mock_labels):
        pipeline = self._make_pipeline()
        champion = self._make_champion(pipeline)
        prediction_date = date.today() - timedelta(days=10)

        mock_dates.return_value = [prediction_date]
        mock_preds.return_value = {
            str(champion.pk): {
                "user-a": 0.9,
                "user-b": 0.8,
                "user-c": 0.2,
                "user-d": 0.1,
            }
        }
        mock_labels.return_value = frozenset(["user-a", "user-b"])

        runs = run_online_validation_for_pipeline(pipeline)

        assert len(runs) == 1
        run = runs[0]
        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.run_type == AutoresearchRun.RunType.VALIDATION
        assert run.metrics["prediction_date"] == prediction_date.isoformat()
        assert run.metrics["realized_labels_count"] == 2
        assert str(champion.pk) in run.metrics["per_model"]

        champion.refresh_from_db()
        assert champion.realized_score is not None
        assert champion.is_preliminary is False

    @patch("products.autoresearch.backend.online_validation._fetch_realized_labels")
    @patch("products.autoresearch.backend.online_validation._fetch_predictions_by_model")
    @patch("products.autoresearch.backend.online_validation._fetch_matured_prediction_dates")
    def test_skips_already_validated_dates(self, mock_dates, mock_preds, mock_labels):
        pipeline = self._make_pipeline()
        self._make_champion(pipeline)
        prediction_date = date.today() - timedelta(days=10)

        # Pre-create a completed validation run for that date
        AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.COMPLETED,
            metrics={"prediction_date": prediction_date.isoformat()},
        )

        mock_dates.return_value = [prediction_date]
        runs = run_online_validation_for_pipeline(pipeline)

        assert runs == []
        mock_preds.assert_not_called()
        mock_labels.assert_not_called()

    @patch("products.autoresearch.backend.online_validation._fetch_realized_labels")
    @patch("products.autoresearch.backend.online_validation._fetch_predictions_by_model")
    @patch("products.autoresearch.backend.online_validation._fetch_matured_prediction_dates")
    def test_empty_predictions_marks_run_completed_with_warning(self, mock_dates, mock_preds, mock_labels):
        pipeline = self._make_pipeline()
        prediction_date = date.today() - timedelta(days=10)

        mock_dates.return_value = [prediction_date]
        mock_preds.return_value = {}  # no predictions found
        mock_labels.return_value = frozenset(["user-a"])

        runs = run_online_validation_for_pipeline(pipeline)

        assert len(runs) == 1
        assert runs[0].status == AutoresearchRun.Status.COMPLETED
        assert runs[0].rows_scored == 0
        assert runs[0].metrics.get("warning") == "no_predictions_found"


class TestFindMatureUnvalidatedDates(BaseTest):
    def _make_pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=50,
            iteration_budget_remaining=50,
        )

    @patch("products.autoresearch.backend.online_validation._fetch_matured_prediction_dates")
    def test_excludes_already_validated(self, mock_dates):
        pipeline = self._make_pipeline()
        d1 = date(2026, 5, 1)
        d2 = date(2026, 5, 2)
        mock_dates.return_value = [d1, d2]

        # d1 already validated
        AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.COMPLETED,
            metrics={"prediction_date": d1.isoformat()},
        )

        unvalidated = _find_mature_unvalidated_dates(team=self.team, pipeline=pipeline)
        assert unvalidated == [d2]

    @patch("products.autoresearch.backend.online_validation._fetch_matured_prediction_dates")
    def test_failed_validation_run_is_retried(self, mock_dates):
        pipeline = self._make_pipeline()
        d1 = date(2026, 5, 1)
        mock_dates.return_value = [d1]

        # FAILED run does not count as validated
        AutoresearchRun.objects.create(
            pipeline=pipeline,
            run_type=AutoresearchRun.RunType.VALIDATION,
            status=AutoresearchRun.Status.FAILED,
            metrics={"prediction_date": d1.isoformat()},
        )

        unvalidated = _find_mature_unvalidated_dates(team=self.team, pipeline=pipeline)
        assert d1 in unvalidated
