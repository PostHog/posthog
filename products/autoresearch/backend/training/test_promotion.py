from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone as django_timezone

from parameterized import parameterized

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.artifacts import ArtifactBundle
from products.autoresearch.backend.training.promotion import PromotionError, complete_training_run

ANCHORED_FEATURE_SQL = "SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a GROUP BY a.person_id"


class TestCompleteTrainingRun(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test",
            target_event="$pageview",
            horizon_days=7,
            iteration_budget=10,
            iteration_budget_remaining=10,
        )

    def _run(self) -> AutoresearchTrainingRun:
        return AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.RUNNING,
            iteration_budget=10,
            started_at=django_timezone.now(),
        )

    def _iteration(
        self,
        run: AutoresearchTrainingRun,
        *,
        number: int,
        status: str = AutoresearchIteration.Status.KEPT,
        holdout: float | None = 0.8,
        feature_sql: str = ANCHORED_FEATURE_SQL,
    ) -> AutoresearchIteration:
        return AutoresearchIteration.objects.create(
            pipeline=self.pipeline,
            training_run=run,
            iteration_number=number,
            recipe_hash=f"hash{number}",
            recipe_snapshot={"feature_sql": feature_sql} if feature_sql else {},
            model_spec={"model_class": "sklearn.linear_model.LogisticRegression", "model_params": {}},
            holdout_score=holdout,
            status=status,
            agent_description=f"iteration {number}",
        )

    def _champion(self) -> AutoresearchModel:
        return AutoresearchModel.objects.get(pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION)

    @parameterized.expand(
        [
            # A null-score kept iteration must not outrank a scored one (Postgres puts
            # NULLs first on a bare DESC).
            ("kept_null_vs_scored", [("kept", None), ("kept", 0.6)], 0.6),
            # A discarded iteration never wins, however it scored.
            ("discarded_never_outranks_kept", [("discarded", 0.9), ("kept", 0.4)], 0.4),
        ]
    )
    def test_champion_selection_ranks_kept_scored_iterations(self, _name, iterations, expected_score):
        run = self._run()
        for number, (status, holdout) in enumerate(iterations):
            self._iteration(run, number=number, status=status, holdout=holdout)

        result = complete_training_run(run)

        assert result["best_holdout_score"] == expected_score
        assert self._champion().holdout_score == expected_score

    def test_completion_without_a_kept_scored_iteration_is_refused(self):
        # A run whose iterations all crashed or went unscored is a failed experiment, not a
        # champion at score 0.
        run = self._run()
        self._iteration(run, number=0, status=AutoresearchIteration.Status.CRASHED, holdout=None)
        self._iteration(run, number=1, status=AutoresearchIteration.Status.DISCARDED, holdout=0.9)

        with self.assertRaises(PromotionError):
            complete_training_run(run)
        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_nomination_cannot_beat_the_server_ranking(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.9)
        nominated = self._iteration(run, number=1, holdout=0.7)

        result = complete_training_run(run, best_iteration_id=nominated.id)

        # The nomination comes from the sandbox agent, so a lower-scoring pick never wins.
        assert result["best_holdout_score"] == 0.9

    @parameterized.expand(
        [
            ("discarded", AutoresearchIteration.Status.DISCARDED, 0.95),
            ("null_score", AutoresearchIteration.Status.KEPT, None),
        ]
    )
    def test_ineligible_nomination_falls_back_to_server_selection(self, _name, status, holdout):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)
        ineligible = self._iteration(run, number=1, status=status, holdout=holdout)

        result = complete_training_run(run, best_iteration_id=ineligible.id)

        # The nomination is ignored; the best scored kept iteration wins instead.
        assert result["best_holdout_score"] == 0.8
        assert self._champion().holdout_score == 0.8

    def test_unknown_nominated_iteration_raises(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)
        foreign = self._iteration(self._run(), number=0, holdout=0.9)

        with self.assertRaises(PromotionError):
            complete_training_run(run, best_iteration_id=foreign.id)

    def test_storage_failure_aborts_completion(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)

        with patch(
            "products.autoresearch.backend.training.artifacts.read_bundle",
            side_effect=RuntimeError("storage unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                complete_training_run(run)

        # The run stays RUNNING so completion can be retried once storage recovers —
        # swallowing the error would pin the model to the legacy recipe path forever.
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_empty_feature_sql_without_bundle_is_refused(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8, feature_sql="")

        with self.assertRaises(PromotionError):
            complete_training_run(run)

        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_empty_feature_sql_with_bundle_completes(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8, feature_sql="")

        bundle = ArtifactBundle(train_py="pass", predict_py="pass", features_sql=ANCHORED_FEATURE_SQL)
        with patch("products.autoresearch.backend.training.artifacts.read_bundle", return_value=bundle):
            result = complete_training_run(run)

        assert result["promoted"] is True
        assert self._champion().artifact_prefix != ""

    def test_bundle_sql_without_anchors_blocks_promotion(self):
        # The uploaded features.sql is what fitting runs, and it need not match the validated
        # iteration snapshot — SQL without {anchors} reads the outcome window.
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)

        leaky = ArtifactBundle(
            train_py="pass",
            predict_py="pass",
            features_sql="SELECT person_id AS distinct_id, count() AS c FROM events GROUP BY person_id",
        )
        with patch("products.autoresearch.backend.training.artifacts.read_bundle", return_value=leaky):
            with self.assertRaises(PromotionError):
                complete_training_run(run)

        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_second_completion_is_a_noop(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)
        first = complete_training_run(run)

        # The stale instance simulates the TaskRun signal racing the complete action:
        # its out-of-transaction status guard saw RUNNING before the first call committed.
        second = complete_training_run(run)

        assert first["model_id"] is not None
        assert second["model_id"] is None
        assert second["promoted"] is False
        assert AutoresearchModel.objects.filter(pipeline=self.pipeline).count() == 1
