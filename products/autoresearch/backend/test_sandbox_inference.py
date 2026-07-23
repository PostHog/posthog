import io

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

import pandas as pd
from parameterized import parameterized

from products.autoresearch.backend import sandbox_inference
from products.autoresearch.backend.artifacts import ArtifactBundle
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline, AutoresearchRun
from products.autoresearch.backend.sandbox_inference import (
    _FILE_BEGIN,
    _FILE_END,
    SandboxInferenceError,
    SandboxScoreResult,
    _between_sentinels,
    _join_scores,
    _materialize_score_data,
    _numeric_feature_cols,
    _read_metrics,
    _read_scores,
    features_parquet,
    fit_champion_model,
    labels_parquet,
    materialize_training_data,
    score_via_sandbox,
)
from products.tasks.backend.facade.sandbox import ExecutionResult


def _scores_parquet(rows: list[tuple[str, float]]) -> bytes:
    """Build a scores.parquet payload (distinct_id, p_y) the way an agent's predict.py would."""
    buf = io.BytesIO()
    pd.DataFrame({"distinct_id": [r[0] for r in rows], "p_y": [r[1] for r in rows]}).to_parquet(buf, index=False)
    return buf.getvalue()


_TRAINING_ROWS = [
    {"distinct_id": "p1", "events_total": 10, "pageviews": 5, "__label": 1, "__fold": 1},
    {"distinct_id": "p2", "events_total": 0, "pageviews": 0, "__label": 0, "__fold": 2},
    {"distinct_id": "p3", "events_total": 3, "pageviews": 1, "__label": 1, "__fold": 0},  # holdout
]
_SCORE_ROWS = [
    {"distinct_id": "s1", "events_total": 7, "pageviews": 2},
    {"distinct_id": "s2", "events_total": 1, "pageviews": 0},
]


def _training_materialized() -> sandbox_inference.MaterializedData:
    return sandbox_inference.MaterializedData(
        feature_cols=["events_total", "pageviews"],
        train_rows=[r for r in _TRAINING_ROWS if r["__fold"] != 0],
        holdout_rows=[r for r in _TRAINING_ROWS if r["__fold"] == 0],
    )


class _FakeSandbox:
    """Stands in for a Tasks sandbox: records writes, routes execute() by command.

    Bundle scripts communicate via files; reads are sentinel-bracketed cats, so a
    cat command is recognised by _FILE_BEGIN and the target file name in the command.
    """

    def __init__(
        self,
        *,
        scores_parquet: bytes = b"",
        metrics_json: str = "",
        model_bytes: bytes = b"PICKLE",
        train_exit: int = 0,
        predict_exit: int = 0,
    ):
        self.written: dict[str, bytes] = {}
        self._scores_parquet = scores_parquet
        self._metrics_json = metrics_json
        self._model_bytes = model_bytes
        self._train_exit = train_exit
        self._predict_exit = predict_exit
        self.destroyed = False

    def __enter__(self) -> "_FakeSandbox":
        return self

    def __exit__(self, *exc) -> bool:
        self.destroyed = True
        return False

    def write_file(self, path: str, payload: bytes) -> None:
        self.written[path] = payload

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        if _FILE_BEGIN in command:  # a sentinel-bracketed readback
            if "base64" in command:  # binary readback (model.pkl or scores.parquet), base64-encoded
                import base64

                raw = self._scores_parquet if "scores.parquet" in command else self._model_bytes
                payload = base64.b64encode(raw).decode()
            elif "output.json" in command:
                payload = self._metrics_json
            else:
                payload = ""
            return ExecutionResult(stdout=f"{_FILE_BEGIN}\n{payload}\n{_FILE_END}\n", stderr="", exit_code=0)
        if "train.py" in command:
            return ExecutionResult(stdout="", stderr="boom" if self._train_exit else "", exit_code=self._train_exit)
        if "predict.py" in command:
            return ExecutionResult(stdout="", stderr="boom" if self._predict_exit else "", exit_code=self._predict_exit)
        return ExecutionResult(stdout="", stderr="", exit_code=0)


class TestMaterializeData(BaseTest):
    def _pipeline(self) -> AutoresearchPipeline:
        return AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="mat",
            target_event="downloaded_file",
            horizon_days=7,
        )

    def test_training_data_splits_folds_and_extracts_feature_cols(self):
        pipeline = self._pipeline()
        with patch.object(sandbox_inference, "_run_hogql", return_value=_TRAINING_ROWS):
            data = materialize_training_data(team=self.team, pipeline=pipeline, feature_sql="SELECT 1 FROM {anchors}")

        assert data.feature_cols == ["events_total", "pageviews"]
        assert [r["distinct_id"] for r in data.train_rows] == ["p1", "p2"]
        assert [r["distinct_id"] for r in data.holdout_rows] == ["p3"]

    def test_score_data_is_inference_only_no_labels(self):
        pipeline = self._pipeline()
        with patch.object(sandbox_inference, "_run_hogql", return_value=_SCORE_ROWS) as run:
            score_rows = _materialize_score_data(
                team=self.team, pipeline=pipeline, feature_sql="SELECT 1 FROM {anchors}"
            )

        # exactly one query (inference anchors only) — no training/holdout materialization
        assert run.call_count == 1
        assert [r["distinct_id"] for r in score_rows] == ["s1", "s2"]

    def test_numeric_feature_cols_excludes_label_fold_and_distinct_id(self):
        cols = _numeric_feature_cols(_TRAINING_ROWS)
        assert cols == ["events_total", "pageviews"]
        assert "__label" not in cols and "__fold" not in cols and "distinct_id" not in cols

    def test_run_hogql_appends_explicit_limit(self):
        # Without an explicit LIMIT, HogQL caps the materialization at 100 rows — the
        # training/holdout/score matrices must be bounded high, not silently truncated.
        captured: dict = {}

        class _FakeRunner:
            def __init__(self, query, team):
                captured["query"] = query.query

            def run(self, execution_mode):
                return MagicMock(results=[], columns=[])

        with patch.object(sandbox_inference, "HogQLQueryRunner", _FakeRunner):
            sandbox_inference._run_hogql(team=self.team, sql="SELECT person_id FROM events", values={})

        assert captured["query"].rstrip().endswith(f"LIMIT {sandbox_inference._MATERIALIZE_ROW_LIMIT}")


class TestParquetSerialization(BaseTest):
    def test_features_parquet_columns_and_rows(self):
        df = pd.read_parquet(io.BytesIO(features_parquet(_SCORE_ROWS, ["events_total", "pageviews"])))
        assert list(df.columns) == ["distinct_id", "events_total", "pageviews"]
        assert df.iloc[0]["distinct_id"] == "s1"
        assert df.iloc[0]["events_total"] == 7.0
        assert df.iloc[0]["pageviews"] == 2.0

    def test_labels_parquet_columns_and_rows(self):
        df = pd.read_parquet(io.BytesIO(labels_parquet(_TRAINING_ROWS)))
        assert list(df.columns) == ["distinct_id", "__label"]
        assert df.iloc[0]["distinct_id"] == "p1"
        assert int(df.iloc[0]["__label"]) == 1

    def test_features_parquet_missing_value_becomes_zero(self):
        rows = [{"distinct_id": "x", "events_total": None}]
        df = pd.read_parquet(io.BytesIO(features_parquet(rows, ["events_total", "pageviews"])))
        # both feature cols present; missing/None coerced to 0.0
        assert df.iloc[0]["events_total"] == 0.0
        assert df.iloc[0]["pageviews"] == 0.0

    def test_features_parquet_distinct_id_is_string(self):
        rows = [{"distinct_id": 12345, "events_total": 1}]
        df = pd.read_parquet(io.BytesIO(features_parquet(rows, ["events_total"])))
        assert df.iloc[0]["distinct_id"] == "12345"


class TestFileReadback(BaseTest):
    def test_between_sentinels_extracts_body(self):
        stdout = f"junk before\n{_FILE_BEGIN}\ndistinct_id,p_y\ns1,0.8\n{_FILE_END}\njunk after"
        body = _between_sentinels(stdout)
        assert body == "distinct_id,p_y\ns1,0.8"

    def test_between_sentinels_raises_when_missing(self):
        with self.assertRaises(SandboxInferenceError):
            _between_sentinels("no sentinels here")

    @parameterized.expand(
        [
            ("plain", '{"holdout_auc": 0.73, "n_train": 2, "n_features": 2}', 0.73),
            ("null_auc", '{"holdout_auc": null, "n_train": 5, "n_features": 1}', None),
        ]
    )
    def test_read_metrics_returns_validated_dict(self, _name, metrics_json, expected_auc):
        fake = _FakeSandbox(metrics_json=metrics_json)
        meta = _read_metrics(fake)
        assert meta["holdout_auc"] == expected_auc

    def test_read_metrics_raises_on_missing_keys(self):
        fake = _FakeSandbox(metrics_json='{"holdout_auc": 0.7}')  # missing n_train, n_features
        with self.assertRaises(SandboxInferenceError):
            _read_metrics(fake)

    def test_read_metrics_raises_on_invalid_json(self):
        fake = _FakeSandbox(metrics_json="not json")
        with self.assertRaises(SandboxInferenceError):
            _read_metrics(fake)

    def test_read_scores_parses_parquet(self):
        fake = _FakeSandbox(scores_parquet=_scores_parquet([("s1", 0.8), ("s2", 0.2)]))
        scores = _read_scores(fake)
        assert scores == {"s1": 0.8, "s2": 0.2}

    def test_read_scores_raises_when_empty(self):
        fake = _FakeSandbox(scores_parquet=_scores_parquet([]))
        with self.assertRaises(SandboxInferenceError):
            _read_scores(fake)

    def test_join_scores_drops_unscored_rows(self):
        scored = _join_scores(score_rows=_SCORE_ROWS, scores={"s1": 0.8})
        assert len(scored) == 1
        assert scored[0]["distinct_id"] == "s1"
        assert scored[0]["p_y"] == 0.8


class TestScoreViaSandbox(BaseTest):
    def _pipeline_and_model(self, artifact_prefix: str = "tasks/autoresearch/team_1/pipeline_x/run_y"):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="sandbox",
            target_event="downloaded_file",
            horizon_days=7,
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            recipe_hash="fixture",
            model_recipe={},
            artifact_prefix=artifact_prefix,
        )
        return pipeline, model

    def _bundle(self) -> ArtifactBundle:
        return ArtifactBundle(train_py="# train", predict_py="# predict", features_sql="SELECT 1 FROM {anchors}")

    def test_predict_run_uses_persisted_model_and_does_not_train(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(scores_parquet=_scores_parquet([("s1", 0.8), ("s2", 0.2)]))
        model.holdout_score = 0.73
        model.metrics = {"n_train": 5}
        model.save(update_fields=["holdout_score", "metrics"])
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=_SCORE_ROWS),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            result = score_via_sandbox(team=self.team, pipeline=pipeline, model=model)

        assert isinstance(result, SandboxScoreResult)
        assert result.holdout_auc == 0.73  # comes from the persisted model, not recomputed
        assert {r["distinct_id"] for r in result.scored_rows} == {"s1", "s2"}
        assert fake.destroyed is True
        # the persisted model + score features were uploaded; predict ran, train.py did NOT
        assert any(p.endswith("model.pkl") for p in fake.written)
        assert any(p.endswith("data/score_features.parquet") for p in fake.written)
        assert not any(p.endswith("data/train_features.parquet") for p in fake.written)

    def test_missing_model_self_heals_by_fitting_once(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(scores_parquet=_scores_parquet([("s1", 0.8), ("s2", 0.2)]))
        fit = MagicMock()
        # read_model: absent first (triggers fit), present after the fit
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", side_effect=[None, b"PICKLE"]),
            patch.object(sandbox_inference, "fit_champion_model", fit),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=_SCORE_ROWS),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            result = score_via_sandbox(team=self.team, pipeline=pipeline, model=model)

        fit.assert_called_once()
        assert {r["distinct_id"] for r in result.scored_rows} == {"s1", "s2"}

    def test_no_artifact_prefix_raises(self):
        pipeline, model = self._pipeline_and_model(artifact_prefix="")
        with self.assertRaises(SandboxInferenceError):
            score_via_sandbox(team=self.team, pipeline=pipeline, model=model)

    def test_predict_failure_raises_and_destroys_sandbox(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(predict_exit=1)
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=_SCORE_ROWS),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
        assert fake.destroyed is True

    def test_empty_score_rows_raises_before_sandbox(self):
        pipeline, model = self._pipeline_and_model()
        create_mock = MagicMock()
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=[]),
            patch.object(sandbox_inference.Sandbox, "create", create_mock),
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
        create_mock.assert_not_called()  # cheap guard fires before paying for a sandbox

    def test_fit_champion_model_trains_and_persists(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(metrics_json='{"holdout_auc": 0.73, "n_train": 2, "n_features": 2}', model_bytes=b"FITTED")
        stored: dict = {}
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "materialize_training_data", return_value=_training_materialized()),
            patch.object(
                sandbox_inference, "write_model", side_effect=lambda prefix, content: stored.update(model=content)
            ),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            metrics = fit_champion_model(team=self.team, pipeline=pipeline, prefix=model.artifact_prefix)

        assert metrics["holdout_auc"] == 0.73
        assert stored["model"] == b"FITTED"  # the fitted model.pkl read back + persisted
        assert any(p.endswith("data/train_features.parquet") for p in fake.written)  # train run materializes training
        assert not any(p.endswith("data/score_features.parquet") for p in fake.written)


class TestInferenceRouting(BaseTest):
    def _pipeline_and_bundle_model(self):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user,
            name="routing",
            target_event="downloaded_file",
            horizon_days=7,
            output_person_property="predicted_p_download",
        )
        model = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            recipe_hash="fixture",
            model_recipe={},
            artifact_prefix="tasks/autoresearch/team_1/pipeline_x/run_y",
        )
        return pipeline, model

    def test_bundle_model_routes_to_sandbox_and_records_metrics(self):
        from products.autoresearch.backend.inference import run_inference_for_pipeline

        pipeline, model = self._pipeline_and_bundle_model()
        sandbox_result = SandboxScoreResult(
            scored_rows=[{"distinct_id": "s1", "p_y": 0.8}, {"distinct_id": "s2", "p_y": 0.2}],
            holdout_auc=0.71,
            n_train=2,
            n_features=2,
        )
        emit = MagicMock()
        emit.return_value.raise_for_status = MagicMock()
        with (
            patch("products.autoresearch.backend.inference.score_via_sandbox", return_value=sandbox_result),
            patch("products.autoresearch.backend.inference.capture_internal", emit),
        ):
            run = run_inference_for_pipeline(pipeline=pipeline, model=model)

        assert run.status == AutoresearchRun.Status.COMPLETED
        assert run.rows_scored == 2
        assert run.metrics["sandbox"] is True
        assert run.metrics["holdout_auc"] == 0.71
        assert emit.call_count == 2

    def test_sandbox_failure_marks_run_failed_with_error(self):
        from products.autoresearch.backend.inference import run_inference_for_pipeline

        pipeline, model = self._pipeline_and_bundle_model()
        with patch(
            "products.autoresearch.backend.inference.score_via_sandbox",
            side_effect=SandboxInferenceError("train.py failed"),
        ):
            with self.assertRaises(SandboxInferenceError):
                run_inference_for_pipeline(pipeline=pipeline, model=model)

        run = AutoresearchRun.objects.filter(pipeline=pipeline).latest("created_at")
        assert run.status == AutoresearchRun.Status.FAILED
        assert "train.py failed" in run.error
