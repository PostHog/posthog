import json
import hashlib

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models.scoping import unscoped
from posthog.storage.object_storage import ObjectStorageError

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.artifacts import ArtifactBundle, InvalidArtifactContent, PartialBundle
from products.autoresearch.backend.training.promotion import PromotionError, complete_training_run

ANCHORED_FEATURE_SQL = "SELECT a.person_id AS distinct_id, count() AS c FROM {anchors} a GROUP BY a.person_id"
LITERAL_FEATURE_SQL = (
    "SELECT a.person_id AS distinct_id, count() AS c, 'plan upgraded' AS marker FROM {anchors} a GROUP BY a.person_id"
)


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
        model_class: str = "sklearn.linear_model.LogisticRegression",
    ) -> AutoresearchIteration:
        return AutoresearchIteration.objects.create(
            pipeline=self.pipeline,
            training_run=run,
            iteration_number=number,
            recipe_hash=f"hash{number}",
            recipe_snapshot={"feature_sql": feature_sql} if feature_sql else {},
            model_spec={"model_class": model_class, "model_params": {}},
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

    def test_nomination_breaks_a_tie_at_the_top_score(self):
        # Two iterations tie, so ranking alone cannot say which one the uploaded bundle came
        # from. The agent's nomination decides, and it still cannot lift a lower score.
        run = self._run()
        tied = self._iteration(run, number=0, holdout=0.8, model_class="xgboost.XGBClassifier")
        self._iteration(run, number=1, holdout=0.8)

        # Ranking alone takes the later iteration, so a nomination for the earlier one only
        # wins if the tie-break honors it.
        result = complete_training_run(run, best_iteration_id=tied.id)

        assert result["best_holdout_score"] == 0.8
        assert self._champion().model_recipe["model_class"] == "xgboost.XGBClassifier"

    def test_unknown_nominated_iteration_raises(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)
        foreign = self._iteration(self._run(), number=0, holdout=0.9)

        with self.assertRaises(PromotionError):
            complete_training_run(run, best_iteration_id=foreign.id)

    @parameterized.expand(
        [
            # The run stays RUNNING so completion can be retried once storage recovers.
            # Swallowing the error would pin the model to the legacy recipe path forever.
            ("storage_unavailable", RuntimeError("storage unavailable"), RuntimeError),
            # A bundle the storage layer refuses is agent input, so it fails the run instead
            # of reaching the caller as an internal error it would retry.
            ("unusable_bundle", InvalidArtifactContent("train.py is not valid UTF-8 text."), PromotionError),
            # An upload that wrote some of the three files is not "no bundle". Falling back to
            # the recipe path would serve an implementation the agent never authored.
            ("partial_bundle", PartialBundle("Bundle is missing required files: predict.py"), PromotionError),
        ]
    )
    def test_unreadable_bundle_aborts_completion(self, _name, raised, expected):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)

        with patch("products.autoresearch.backend.training.artifacts.read_bundle", side_effect=raised):
            with self.assertRaises(expected):
                complete_training_run(run)

        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    @parameterized.expand(
        [
            ("no_feature_sql", {"feature_sql": ""}),
            # Recording accepts any model_class, because a bundle runs its own code. The
            # in-process scorer resolves the class through importlib and refuses anything
            # off the allowlist, so this champion could never score.
            ("bundle_only_model_class", {"model_class": "my_package.MyClassifier"}),
        ]
    )
    def test_recipe_the_legacy_scorer_cannot_run_is_refused(self, _name, iteration_kwargs):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8, **iteration_kwargs)

        with self.assertRaises(PromotionError):
            complete_training_run(run)

        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.RUNNING
        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_bundle_matching_the_selected_iteration_completes(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)

        # Reindented on the way into the file, which is a formatting difference, not a
        # different model.
        reformatted = ANCHORED_FEATURE_SQL.replace(" FROM ", "\n  FROM ") + "\n"
        bundle = ArtifactBundle(train_py="pass", predict_py="pass", features_sql=reformatted)
        with patch("products.autoresearch.backend.training.artifacts.read_bundle", return_value=bundle):
            result = complete_training_run(run)

        assert result["promoted"] is True
        assert self._champion().artifact_prefix != ""

    @parameterized.expand(
        [
            # The bundle is written once per run, so a losing iteration can overwrite it.
            ("different_query", ANCHORED_FEATURE_SQL.replace("count()", "count(DISTINCT a.person_id)")),
            # Whitespace inside a literal is content, not formatting: this one matches a
            # different event.
            ("whitespace_inside_a_literal", LITERAL_FEATURE_SQL.replace("plan upgraded", "plan  upgraded")),
        ]
    )
    def test_bundle_that_is_not_the_selected_query_is_refused(self, _name, uploaded_sql):
        # Promoting it would advertise the winner's recipe and score against code that never
        # produced them.
        run = self._run()
        self._iteration(run, number=0, holdout=0.9, feature_sql=LITERAL_FEATURE_SQL)

        bundle = ArtifactBundle(train_py="pass", predict_py="pass", features_sql=uploaded_sql)
        with patch("products.autoresearch.backend.training.artifacts.read_bundle", return_value=bundle):
            with self.assertRaises(PromotionError):
                complete_training_run(run)

        assert not AutoresearchModel.objects.filter(pipeline=self.pipeline).exists()

    def test_a_candidate_exactly_on_the_promotion_margin_is_promoted(self):
        # The margin is documented as inclusive, and 0.1 + 0.005 is above 0.105 in binary
        # floating point.
        first = self._run()
        self._iteration(first, number=0, holdout=0.1)
        complete_training_run(first)

        second = self._run()
        self._iteration(second, number=0, holdout=0.105)
        result = complete_training_run(second)

        assert result["promoted"] is True
        assert self._champion().holdout_score == 0.105

    def test_bundle_sql_without_anchors_blocks_promotion(self):
        # The uploaded features.sql is what fitting runs, so SQL without {anchors} reads the
        # outcome window whatever the iteration recorded.
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

    def test_completion_runs_without_an_ambient_team_scope(self):
        # The TaskRun safety net finalizes a run from a worker thread, where no request has
        # set a scope. Every read in promotion goes through a fail-closed manager.
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)

        with unscoped():
            result = complete_training_run(run)

        assert result["promoted"] is True

    def test_challenger_below_the_margin_leaves_the_incumbent_serving(self):
        first = self._run()
        self._iteration(first, number=0, holdout=0.8, model_class="xgboost.XGBClassifier")
        complete_training_run(first)

        second = self._run()
        self._iteration(second, number=0, holdout=0.801)
        bundle = ArtifactBundle(train_py="pass", predict_py="pass", features_sql=ANCHORED_FEATURE_SQL)
        with patch("products.autoresearch.backend.training.artifacts.read_bundle", return_value=bundle):
            with patch("products.autoresearch.backend.training.promotion.fit_champion_model") as fit:
                with self.captureOnCommitCallbacks(execute=True):
                    result = complete_training_run(second)

        assert result["promoted"] is False
        assert result["role"] == AutoresearchModel.Role.CHALLENGER
        assert self._champion().holdout_score == 0.8
        # Inference reads the champion only, so fitting the rejected bundle would spend a
        # sandbox run on an artifact nothing loads.
        fit.assert_not_called()
        second.refresh_from_db()
        # The next run reads this summary as the champion it has to beat.
        assert second.summary["champion_model_class"] == "xgboost.XGBClassifier"

    def test_a_failed_champion_fit_does_not_fail_a_committed_completion(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)

        bundle = ArtifactBundle(train_py="pass", predict_py="pass", features_sql=ANCHORED_FEATURE_SQL)
        with patch("products.autoresearch.backend.training.artifacts.read_bundle", return_value=bundle):
            with patch(
                "products.autoresearch.backend.training.promotion.fit_champion_model",
                # write_model raises this, and it is not a SandboxInferenceError. The run is
                # already committed, so it must not reach the caller as a failed completion.
                side_effect=ObjectStorageError("object storage unavailable"),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    result = complete_training_run(run)

        assert result["promoted"] is True
        run.refresh_from_db()
        assert run.status == AutoresearchTrainingRun.Status.COMPLETED

    def test_model_recipe_hash_identifies_the_stored_recipe(self):
        run = self._run()
        iteration = self._iteration(run, number=0, holdout=0.8)

        complete_training_run(run)

        champion = self._champion()
        expected = hashlib.sha256(
            json.dumps(champion.model_recipe, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        assert champion.recipe_hash == expected
        # The iteration's hash is an agent-supplied string over different content, so copying
        # it would leave the model row's provenance pointing at a recipe it does not hold.
        assert champion.recipe_hash != iteration.recipe_hash

    def test_second_completion_is_a_noop(self):
        run = self._run()
        self._iteration(run, number=0, holdout=0.8)
        first = complete_training_run(run)

        # The stale instance simulates the TaskRun signal racing the complete action:
        # its out-of-transaction status guard saw RUNNING before the first call committed.
        # The no-op answer must not depend on object storage, which the retry never needs.
        with patch(
            "products.autoresearch.backend.training.artifacts.read_bundle",
            side_effect=RuntimeError("storage unavailable"),
        ):
            second = complete_training_run(run)

        assert first["model_id"] is not None
        assert second["model_id"] is None
        assert second["promoted"] is False
        assert AutoresearchModel.objects.filter(pipeline=self.pipeline).count() == 1
