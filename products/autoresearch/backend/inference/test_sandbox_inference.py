import io
import json
import base64
from decimal import Decimal

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import pandas as pd
from parameterized import parameterized

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.user import User

from products.autoresearch.backend.inference import sandbox as sandbox_inference
from products.autoresearch.backend.inference.sandbox import (
    _FEATURE_COLUMNS_JSON,
    _FILE_BEGIN,
    _FILE_END,
    SandboxInferenceError,
    SandboxScoreResult,
    _between_sentinels,
    _join_scores,
    _materialize_score_data,
    _numeric_feature_cols,
    _read_binary_file,
    _read_metrics,
    _read_scores,
    features_parquet,
    fit_champion_model,
    labels_parquet,
    materialize_training_data,
    score_via_sandbox,
)
from products.autoresearch.backend.models import AutoresearchModel, AutoresearchPipeline
from products.autoresearch.backend.query import HogQLResult
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.artifacts import ArtifactBundle, BundleNotFound
from products.tasks.backend.facade.sandbox import ExecutionResult

_VALID_FEATURE_SQL = "SELECT a.person_id AS distinct_id, count() AS events_total FROM {anchors} a GROUP BY a.person_id"


def _scores_parquet(rows: list[tuple[str, object]]) -> bytes:
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
_METRICS_JSON = '{"holdout_auc": 0.73, "n_train": 2, "n_features": 2}'


def _training_materialized() -> sandbox_inference.MaterializedData:
    return sandbox_inference.MaterializedData(
        feature_cols=["events_total", "pageviews"],
        train_rows=[r for r in _TRAINING_ROWS if r["__fold"] != 0],
        holdout_rows=[r for r in _TRAINING_ROWS if r["__fold"] == 0],
    )


class _FakeSandbox:
    def __init__(
        self,
        *,
        scores_parquet: bytes = b"",
        metrics_json: str = "",
        model_bytes: bytes = b"PICKLE",
        train_exit: int = 0,
        predict_exit: int = 0,
        readback_exit: int = 0,
        write_exit_for: str = "",
    ):
        self.written: dict[str, bytes] = {}
        self.commands: list[str] = []
        self._scores_parquet = scores_parquet
        self._metrics_json = metrics_json
        self._model_bytes = model_bytes
        self._train_exit = train_exit
        self._predict_exit = predict_exit
        self._readback_exit = readback_exit
        self._write_exit_for = write_exit_for
        self.destroyed = False

    def __enter__(self) -> "_FakeSandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.destroyed = True

    def write_file(self, path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult:
        if self._write_exit_for and path.endswith(self._write_exit_for):
            return ExecutionResult(stdout="", stderr="no space left on device", exit_code=1)
        self.written[path] = payload
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    def ran(self, script: str) -> bool:
        return any(f"bundle/{script}" in c for c in self.commands)

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        self.commands.append(command)
        if _FILE_BEGIN in command:
            if self._readback_exit:
                return ExecutionResult(stdout="", stderr="missing", exit_code=self._readback_exit)
            if "base64" in command:
                raw = self._scores_parquet if "scores.parquet" in command else self._model_bytes
                payload = base64.b64encode(raw).decode()
            elif "output.json" in command:
                payload = self._metrics_json
            else:
                payload = ""
            return ExecutionResult(stdout=f"{_FILE_BEGIN}\n{payload}\n{_FILE_END}\n", stderr="", exit_code=0)
        if "tail -c" in command:
            return ExecutionResult(stdout="boom", stderr="", exit_code=0)
        if "bundle/train.py" in command:
            return ExecutionResult(stdout="", stderr="", exit_code=self._train_exit)
        if "bundle/predict.py" in command:
            return ExecutionResult(stdout="", stderr="", exit_code=self._predict_exit)
        return ExecutionResult(stdout="", stderr="", exit_code=0)


class TestMaterializeData(TeamScopedTestMixin, BaseTest):
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
        with patch.object(sandbox_inference, "_materialize_rows", return_value=_TRAINING_ROWS):
            data = materialize_training_data(team=self.team, pipeline=pipeline, feature_sql="SELECT 1 FROM {anchors}")

        assert data.feature_cols == ["events_total", "pageviews"]
        assert [r["distinct_id"] for r in data.train_rows] == ["p1", "p2"]
        assert [r["distinct_id"] for r in data.holdout_rows] == ["p3"]

    @parameterized.expand(
        [
            ("duplicate_person", [{"distinct_id": "p1", "__label": 1, "__fold": 1}] * 2),
            ("no_label_match", [{"distinct_id": "p1", "__label": None, "__fold": None}]),
        ]
    )
    def test_training_data_rejects_rows_that_do_not_key_one_labeled_person(self, _name, rows):
        pipeline = self._pipeline()
        with patch.object(sandbox_inference, "_materialize_rows", return_value=rows):
            with self.assertRaises(SandboxInferenceError):
                materialize_training_data(team=self.team, pipeline=pipeline, feature_sql="SELECT 1 FROM {anchors}")

    def test_score_data_is_inference_only_no_labels(self):
        pipeline = self._pipeline()
        with patch.object(sandbox_inference, "_materialize_rows", return_value=_SCORE_ROWS) as run:
            score_rows = _materialize_score_data(
                team=self.team, pipeline=pipeline, feature_sql="SELECT 1 FROM {anchors}"
            )

        # exactly one query (inference anchors only) — no training/holdout materialization
        assert run.call_count == 1
        assert [r["distinct_id"] for r in score_rows] == ["s1", "s2"]

    def test_score_data_rejects_duplicate_persons(self):
        pipeline = self._pipeline()
        with patch.object(sandbox_inference, "_materialize_rows", return_value=[_SCORE_ROWS[0]] * 2):
            with self.assertRaises(SandboxInferenceError):
                _materialize_score_data(team=self.team, pipeline=pipeline, feature_sql="SELECT 1 FROM {anchors}")

    @parameterized.expand(
        [
            ("labels_and_ids_excluded", _TRAINING_ROWS, ["events_total", "pageviews"]),
            (
                "string_column_null_in_first_row",
                [{"distinct_id": "a", "plan": None, "n": 1}, {"distinct_id": "b", "plan": "pro", "n": 2}],
                ["n"],
            ),
            (
                "decimal_and_all_null_are_numeric",
                [{"distinct_id": "a", "amount": Decimal("1.5"), "empty": None}],
                ["amount", "empty"],
            ),
        ]
    )
    def test_numeric_feature_cols(self, _name, rows, expected):
        assert _numeric_feature_cols(rows) == expected

    def test_materialize_rows_bounds_the_query_and_runs_it_fresh_as_the_user(self):
        # Without an explicit LIMIT, HogQL caps the materialization at 100 rows; a cached
        # result would score yesterday's population at yesterday's cutoff.
        captured: dict = {}

        def _capture(*, team, query, **kwargs):
            captured["query"] = query.query
            captured["modifiers"] = query.modifiers
            captured.update(kwargs)
            return HogQLResult(columns=[], rows=[])

        with patch.object(sandbox_inference, "run_hogql", _capture):
            sandbox_inference._materialize_rows(
                team=self.team, sql="SELECT person_id FROM events", values={}, user=self.user
            )

        assert captured["query"].rstrip().endswith(f"LIMIT {sandbox_inference._MATERIALIZE_ROW_LIMIT}")
        assert captured["execution_mode"] == ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        assert captured["user"] == self.user
        # The anchor SQL reads person.is_identified, which only resolves under the labeler's
        # persons-on-events mode.
        assert captured["modifiers"] == sandbox_inference.LABELER_QUERY_MODIFIERS

    @parameterized.expand(
        [
            ("under_limit", 2, False, False),
            ("at_limit", 3, False, True),
            ("runner_reports_more", 2, True, True),
        ]
    )
    def test_materialize_rows_fails_when_result_is_truncated(self, _name, n_rows, has_more, expect_raise):
        # A result that fills the LIMIT is a truncated population — completing would
        # advance last_scored_at while silently skipping the users past the cap.
        page = HogQLResult(columns=["distinct_id"], rows=[[f"p{i}"] for i in range(n_rows)], has_more=has_more)
        with (
            patch.object(sandbox_inference, "_MATERIALIZE_ROW_LIMIT", 3),
            patch.object(sandbox_inference, "run_hogql") as mock_run_hogql,
        ):
            mock_run_hogql.return_value = page
            if expect_raise:
                with self.assertRaises(SandboxInferenceError):
                    sandbox_inference._materialize_rows(team=self.team, sql="SELECT person_id FROM events", values={})
            else:
                rows = sandbox_inference._materialize_rows(
                    team=self.team, sql="SELECT person_id FROM events", values={}
                )
                assert len(rows) == n_rows

    def test_materialize_rows_rejects_duplicate_output_columns(self):
        page = HogQLResult(columns=["distinct_id", "events_total", "events_total"], rows=[["p1", 1, 2]])
        with patch.object(sandbox_inference, "run_hogql", return_value=page):
            with self.assertRaises(SandboxInferenceError):
                sandbox_inference._materialize_rows(team=self.team, sql="SELECT person_id FROM events", values={})


class TestParquetSerialization(SimpleTestCase):
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

    def test_features_parquet_rejects_a_non_numeric_value_in_a_fitted_column(self):
        rows = [{"distinct_id": "x", "events_total": "unknown"}]
        with self.assertRaises(SandboxInferenceError):
            features_parquet(rows, ["events_total"])

    def test_features_parquet_rejects_more_columns_than_the_cap(self):
        cols = [f"f{i}" for i in range(sandbox_inference._MAX_FEATURE_COLS + 1)]
        with self.assertRaises(SandboxInferenceError):
            features_parquet([{"distinct_id": "x"}], cols)

    def test_features_parquet_distinct_id_is_string(self):
        rows = [{"distinct_id": 12345, "events_total": 1}]
        df = pd.read_parquet(io.BytesIO(features_parquet(rows, ["events_total"])))
        assert df.iloc[0]["distinct_id"] == "12345"


class TestFileReadback(SimpleTestCase):
    def test_between_sentinels_extracts_body(self):
        stdout = f"junk before\n{_FILE_BEGIN}\ndistinct_id,p_y\ns1,0.8\n{_FILE_END}\njunk after"
        body = _between_sentinels(stdout)
        assert body == "distinct_id,p_y\ns1,0.8"

    def test_between_sentinels_raises_when_missing(self):
        with self.assertRaises(SandboxInferenceError):
            _between_sentinels("no sentinels here")

    @parameterized.expand(
        [
            ("missing_or_oversized_file", _FakeSandbox(readback_exit=4)),
            ("empty_file", _FakeSandbox(model_bytes=b"")),
        ]
    )
    def test_read_binary_file_fails_instead_of_returning_nothing(self, _name, fake):
        with self.assertRaises(SandboxInferenceError):
            _read_binary_file(fake, "model.pkl")

    def test_readback_command_gates_on_size_before_emitting(self):
        command = sandbox_inference._readback_command("model.pkl", encode=True)
        assert command.index("stat -c %s") < command.index("head -c") < command.index("base64")
        assert str(sandbox_inference._MAX_READBACK_BYTES) in command

    def test_read_binary_file_rejects_a_file_that_grew_past_the_cap_after_the_stat(self):
        fake = _FakeSandbox(model_bytes=b"PICKLE")
        with patch.object(sandbox_inference, "_MAX_READBACK_BYTES", 4):
            with self.assertRaises(SandboxInferenceError):
                _read_binary_file(fake, "model.pkl")

    @parameterized.expand(
        [
            ("plain", _METRICS_JSON, 0.73),
            ("null_auc", '{"holdout_auc": null, "n_train": 5, "n_features": 1}', None),
        ]
    )
    def test_read_metrics_returns_validated_dict(self, _name, metrics_json, expected_auc):
        fake = _FakeSandbox(metrics_json=metrics_json)
        meta = _read_metrics(fake)
        assert meta["holdout_auc"] == expected_auc

    @parameterized.expand(
        [
            ("missing_keys", '{"holdout_auc": 0.7}'),
            ("invalid_json", "not json"),
            ("nan_auc", '{"holdout_auc": NaN, "n_train": 2, "n_features": 2}'),
            ("auc_above_one", '{"holdout_auc": 1.5, "n_train": 2, "n_features": 2}'),
            ("bool_auc", '{"holdout_auc": true, "n_train": 2, "n_features": 2}'),
            ("negative_count", '{"holdout_auc": 0.7, "n_train": -1, "n_features": 2}'),
            ("string_count", '{"holdout_auc": 0.7, "n_train": "2", "n_features": 2}'),
            ("zero_features", '{"holdout_auc": 0.7, "n_train": 2, "n_features": 0}'),
        ]
    )
    def test_read_metrics_rejects_malformed_output(self, _name, metrics_json):
        # train.py is agent-authored: json.loads accepts NaN, and a key check alone lets
        # a bool, a string, or an out-of-range AUC onto the model row.
        fake = _FakeSandbox(metrics_json=metrics_json)
        with self.assertRaises(SandboxInferenceError):
            _read_metrics(fake)

    def test_read_scores_parses_parquet(self):
        fake = _FakeSandbox(scores_parquet=_scores_parquet([("s1", 0.8), ("s2", 0.2)]))
        scores = _read_scores(fake, expected_rows=2)
        assert scores == {"s1": 0.8, "s2": 0.2}

    @parameterized.expand(
        [
            ("empty", [], 2),
            ("duplicate_person", [("s1", 0.8), ("s1", 0.2)], 2),
            ("more_rows_than_inputs", [("s1", 0.8), ("s2", 0.2), ("s3", 0.1)], 2),
            ("nan", [("s1", float("nan"))], 1),
            ("inf", [("s1", float("inf"))], 1),
            ("neg_inf", [("s1", float("-inf"))], 1),
            ("above_one", [("s1", 1.5)], 1),
            ("below_zero", [("s1", -0.01)], 1),
            ("non_numeric", [("s1", "not-a-probability")], 1),
            ("non_string_ids", [(1, 0.5)], 1),
        ]
    )
    def test_read_scores_rejects_malformed_output(self, _name, rows, expected_rows):
        # predict.py output is untrusted agent code: a NaN/inf/out-of-range score, a person
        # scored twice, or a table larger than the input must fail the run rather than
        # flow into emitted prediction events.
        fake = _FakeSandbox(scores_parquet=_scores_parquet(rows))
        with self.assertRaises(SandboxInferenceError):
            _read_scores(fake, expected_rows=expected_rows)

    def test_read_scores_rejects_a_table_that_decodes_past_the_cap(self):
        # A compressible parquet under the readback cap can still expand in the worker.
        fake = _FakeSandbox(scores_parquet=_scores_parquet([("s" * 500, 0.5)]))
        with patch.object(sandbox_inference, "_MAX_READBACK_BYTES", 200):
            with self.assertRaises(SandboxInferenceError):
                _read_scores(fake, expected_rows=1)

    def test_join_scores_fails_when_predictions_omit_rows(self):
        # A user missing from scores.parquet must fail the run — skipping them would
        # advance last_scored_at while silently leaving the user unscored.
        with self.assertRaises(SandboxInferenceError):
            _join_scores(score_rows=_SCORE_ROWS, scores={"s1": 0.8})

    def test_join_scores_keeps_full_precision(self):
        scored = _join_scores(score_rows=_SCORE_ROWS[:1], scores={"s1": 0.123456789})
        assert scored[0]["p_y"] == 0.123456789


class TestScoreViaSandbox(TeamScopedTestMixin, BaseTest):
    def _pipeline_and_model(self, artifact_prefix: str = "tasks/autoresearch/team_1/pipeline_x/run_y", created_by=...):
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            created_by=self.user if created_by is ... else created_by,
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

    def _bundle(self, features_sql: str = _VALID_FEATURE_SQL) -> ArtifactBundle:
        return ArtifactBundle(train_py="# train", predict_py="# predict", features_sql=features_sql)

    def _no_fitted_columns(self):
        return patch.object(sandbox_inference, "read_artifact", side_effect=BundleNotFound("none"))

    def test_predict_run_uses_persisted_model_and_does_not_train(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(scores_parquet=_scores_parquet([("s1", 0.8), ("s2", 0.2)]))
        model.holdout_score = 0.73
        model.metrics = {"n_train": 5}
        model.save(update_fields=["holdout_score", "metrics"])
        fitted_columns = json.dumps(["events_total", "pageviews", "signups"]).encode()
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            patch.object(sandbox_inference, "read_artifact", return_value=fitted_columns),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=_SCORE_ROWS),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            result = score_via_sandbox(team=self.team, pipeline=pipeline, model=model)

        assert isinstance(result, SandboxScoreResult)
        # predict.py sees the columns the champion was fitted on, not whatever this
        # population happens to contain; a column absent today is sent as zeros.
        sent = pd.read_parquet(io.BytesIO(fake.written[f"{sandbox_inference._WORKDIR}/data/score_features.parquet"]))
        assert list(sent.columns) == ["distinct_id", "events_total", "pageviews", "signups"]
        assert list(sent["signups"]) == [0.0, 0.0]
        assert result.holdout_auc == 0.73  # comes from the persisted model, not recomputed
        assert {r["distinct_id"] for r in result.scored_rows} == {"s1", "s2"}
        assert fake.destroyed is True
        # the persisted model + score features were uploaded; predict ran, train.py did NOT
        assert any(p.endswith("model.pkl") for p in fake.written)
        assert any(p.endswith("data/score_features.parquet") for p in fake.written)
        assert not any(p.endswith("data/train_features.parquet") for p in fake.written)
        assert fake.ran("predict.py") and not fake.ran("train.py")

    def test_missing_model_fails_without_fitting(self):
        # Fitting stays at training completion: a cadence that fits would race other
        # cadences for the pickle and turn a 120 s predict into a 300 s fit.
        pipeline, model = self._pipeline_and_model()
        create_mock = MagicMock()
        fit = MagicMock()
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=None),
            patch.object(sandbox_inference, "fit_champion_model", fit),
            patch.object(sandbox_inference.Sandbox, "create", create_mock),
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)

        fit.assert_not_called()
        create_mock.assert_not_called()

    def test_no_artifact_prefix_raises(self):
        pipeline, model = self._pipeline_and_model(artifact_prefix="")
        with self.assertRaises(SandboxInferenceError):
            score_via_sandbox(team=self.team, pipeline=pipeline, model=model)

    @parameterized.expand(
        [
            ("no_anchors", "SELECT person_id AS distinct_id, count() AS n FROM events GROUP BY person_id"),
            (
                "wall_clock",
                "SELECT a.person_id AS distinct_id, countIf(now() > a.cutoff_ts) AS n FROM {anchors} a GROUP BY a.person_id",
            ),
            ("trailing_limit", _VALID_FEATURE_SQL + " LIMIT 10"),
            ("trailing_settings", _VALID_FEATURE_SQL + " SETTINGS max_threads=1"),
        ]
    )
    def test_bundle_feature_sql_is_validated_before_anything_runs(self, _name, features_sql):
        # The recipe snapshot was validated at upload; features.sql is what runs, and a
        # trailing LIMIT would collide with the framework's own on the inference path.
        pipeline, model = self._pipeline_and_model()
        create_mock = MagicMock()
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle(features_sql)),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            patch.object(sandbox_inference, "_materialize_score_data") as materialize,
            patch.object(sandbox_inference.Sandbox, "create", create_mock),
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
        materialize.assert_not_called()
        create_mock.assert_not_called()

    def test_runs_as_the_creator_and_fails_when_the_creator_has_no_access(self):
        # HogQL fails closed without a user, so a departed creator would silently narrow
        # the pipeline's data instead of surfacing.
        outsider = User.objects.create_user(email="outsider@example.com", password=None, first_name="o")
        pipeline, model = self._pipeline_and_model(created_by=outsider)
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            self._no_fitted_columns(),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=[]) as materialize,
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
            materialize.assert_not_called()

            pipeline.created_by = None
            pipeline.save(update_fields=["created_by"])
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
            materialize.assert_not_called()

            with self.assertRaises(SandboxInferenceError):  # no rows, after materialization ran as the user
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model, user=self.user)
        assert materialize.call_args.kwargs["user"] == self.user

    def test_predict_failure_raises_and_destroys_sandbox(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(predict_exit=1)
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            self._no_fitted_columns(),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=_SCORE_ROWS),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            with self.assertRaises(SandboxInferenceError) as ctx:
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
        assert fake.destroyed is True
        assert "boom" in str(ctx.exception)  # the bounded script log tail, not execute().stderr

    def test_model_upload_failure_aborts_before_predict_runs(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(write_exit_for=sandbox_inference._MODEL_PKL)
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            self._no_fitted_columns(),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=_SCORE_ROWS),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
        assert not fake.ran("predict.py")
        assert fake.destroyed is True

    def test_empty_score_rows_raises_before_sandbox(self):
        pipeline, model = self._pipeline_and_model()
        create_mock = MagicMock()
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "read_model", return_value=b"PICKLE"),
            self._no_fitted_columns(),
            patch.object(sandbox_inference, "_materialize_score_data", return_value=[]),
            patch.object(sandbox_inference.Sandbox, "create", create_mock),
        ):
            with self.assertRaises(SandboxInferenceError):
                score_via_sandbox(team=self.team, pipeline=pipeline, model=model)
        create_mock.assert_not_called()  # cheap guard fires before paying for a sandbox

    def test_fit_champion_model_trains_smoke_tests_predict_and_persists(self):
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(
            metrics_json=_METRICS_JSON, model_bytes=b"FITTED", scores_parquet=_scores_parquet([("p3", 0.5)])
        )
        stored: dict = {}
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "materialize_training_data", return_value=_training_materialized()),
            patch.object(
                sandbox_inference, "write_model", side_effect=lambda prefix, content: stored.update(model=content)
            ),
            patch.object(
                sandbox_inference,
                "write_artifact",
                side_effect=lambda prefix, path, content: stored.update({path: content}),
            ),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            metrics = fit_champion_model(team=self.team, pipeline=pipeline, prefix=model.artifact_prefix)

        assert metrics["holdout_auc"] == 0.73
        assert stored["model"] == b"FITTED"  # the fitted model.pkl read back + persisted
        assert json.loads(stored[_FEATURE_COLUMNS_JSON]) == ["events_total", "pageviews"]
        assert any(p.endswith("data/train_features.parquet") for p in fake.written)  # train run materializes training
        assert not any(p.endswith("data/score_features.parquet") for p in fake.written)
        assert fake.ran("train.py") and fake.ran("predict.py")  # predict.py exercised against the holdout
        assert fake.written[f"{sandbox_inference._WORKDIR}/{sandbox_inference._SMOKE_MODEL_PKL}"] == b"FITTED"
        assert any(sandbox_inference._SMOKE_MODEL_PKL in c for c in fake.commands if "predict.py" in c)

    @parameterized.expand(
        [
            ("predict_exits_nonzero", {"predict_exit": 1}),
            ("predict_skips_a_holdout_row", {"scores_parquet": _scores_parquet([("someone-else", 0.5)])}),
            (
                "train_features_upload_fails",
                {"write_exit_for": "data/train_features.parquet", "scores_parquet": _scores_parquet([("p3", 0.5)])},
            ),
            (
                "bundle_upload_fails",
                {"write_exit_for": "bundle/train.py", "scores_parquet": _scores_parquet([("p3", 0.5)])},
            ),
        ]
    )
    def test_fit_champion_model_does_not_persist_when_predict_smoke_test_fails(self, _name, fake_kwargs):
        # A bundle whose predict.py cannot load or apply the fitted model fails at
        # completion, not on the first cadence.
        pipeline, model = self._pipeline_and_model()
        fake = _FakeSandbox(metrics_json=_METRICS_JSON, model_bytes=b"FITTED", **fake_kwargs)
        write_model = MagicMock()
        with (
            patch.object(sandbox_inference, "read_bundle", return_value=self._bundle()),
            patch.object(sandbox_inference, "materialize_training_data", return_value=_training_materialized()),
            patch.object(sandbox_inference, "write_model", write_model),
            patch.object(sandbox_inference, "write_artifact", MagicMock()),
            patch.object(sandbox_inference.Sandbox, "create", return_value=fake),
        ):
            with self.assertRaises(SandboxInferenceError):
                fit_champion_model(team=self.team, pipeline=pipeline, prefix=model.artifact_prefix)
        write_model.assert_not_called()
        assert fake.destroyed is True
