"""Tests for Phase 2 — emit $automl_prediction events from a run's predictions parquet."""

from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa

from products.automl.backend import logic
from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import RunKind, RunStatus, TaskType
from products.automl.backend.inference import emit

from .test_retrain import _make_active_pipeline_with_winning_run


def _fake_predictions_table(
    *,
    n_rows: int = 3,
    include_id: bool = True,
    include_proba: bool = True,
    id_column: str = "person_id",
) -> pa.Table:
    """Build an in-memory pyarrow Table mimicking the CLI's predict output."""
    data: dict[str, list] = {}
    if include_id:
        data[id_column] = [f"p{i}" for i in range(n_rows)]
    data["prediction"] = [i % 2 for i in range(n_rows)]
    if include_proba:
        data["proba_0"] = [0.3 + 0.1 * i for i in range(n_rows)]
        data["proba_1"] = [0.7 - 0.1 * i for i in range(n_rows)]
    return pa.Table.from_pydict(data)


def _ok_response() -> MagicMock:
    """Mock a successful requests Response (capture-rs returns 200)."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock(return_value=None)
    return resp


def _make_succeeded_inference_run(team_id: int, *, name: str, manifest: dict, user_id: int):
    """Open + flip an inference run to SUCCEEDED without triggering emission.

    Tests below want to drive emit_predictions_for_run directly with controlled
    inputs, so we patch capture_internal during the record-outcome call to
    swallow the auto-emit side effect.
    """
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team_id, name=name)
    from products.tasks.backend.models import Task

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid4()
        run_dto = api.infer(team_id=team_id, pipeline_id=pipeline_dto.id, user_id=user_id)
    # Auto-emission fires on record_inference_outcome — patch it out here so
    # the run lands terminal without making real capture calls.
    with patch("products.automl.backend.inference.emit.emit_predictions_for_run", return_value=0):
        api.record_inference_outcome(
            team_id=team_id,
            run_id=run_dto.id,
            params=contracts.RecordInferenceOutcomeInput(
                status=RunStatus.SUCCEEDED,
                outcome_report="ok",
                inference_result=manifest,
            ),
        )
    run = logic.get_pipeline_run(team_id=team_id, run_id=run_dto.id)
    assert run is not None
    return pipeline_dto, run


# ---- emit_predictions_for_run unit behavior ----


@pytest.mark.django_db
def test_emit_predictions_noops_without_uri(team, user):
    """No predictions_uri → 0 emitted, no HTTP calls."""
    _, run = _make_succeeded_inference_run(team.id, name="emit_no_uri", manifest={}, user_id=user.id)

    with patch("products.automl.backend.inference.emit.capture_internal") as mock_capture:
        emitted = emit.emit_predictions_for_run(run)

    assert emitted == 0
    mock_capture.assert_not_called()


@pytest.mark.django_db
def test_emit_predictions_classification_emits_one_event_per_row(team, user):
    """3-row parquet → 3 capture_internal calls with the right shape."""
    manifest = {
        "predictions_uri": "s3://fake/predictions.parquet",
        "inference_run_id": "20260514T120000Z",
        "model_run_id": "20260513T214213Z",
        "id_column": "person_id",
    }
    pipeline_dto, run = _make_succeeded_inference_run(
        team.id, name="emit_classification", manifest=manifest, user_id=user.id
    )

    fake_table = _fake_predictions_table(n_rows=3)
    with (
        patch("products.automl.backend.inference.emit._read_predictions", return_value=fake_table),
        patch("products.automl.backend.inference.emit.capture_internal", return_value=_ok_response()) as mock_capture,
    ):
        emitted = emit.emit_predictions_for_run(run)

    assert emitted == 3
    assert mock_capture.call_count == 3

    # First call's properties — verify metadata + per-row fields.
    first_call_kwargs = mock_capture.call_args_list[0].kwargs
    assert first_call_kwargs["token"] == team.api_token
    assert first_call_kwargs["event_name"] == "$automl_prediction"
    assert first_call_kwargs["event_source"] == "automl_inference"
    assert first_call_kwargs["distinct_id"] == "p0"
    props = first_call_kwargs["properties"]
    assert props["$automl_pipeline_id"] == str(pipeline_dto.id)
    assert props["$automl_run_id"] == str(run.id)
    assert props["$automl_inference_run_id"] == "20260514T120000Z"
    assert props["$automl_model_run_id"] == "20260513T214213Z"
    assert props["$automl_task_type"] == "classification"
    assert props["$automl_id_column"] == "person_id"
    assert props["$automl_prediction"] == 0
    assert props["$automl_proba_0"] == pytest.approx(0.3)
    assert props["$automl_proba_1"] == pytest.approx(0.7)
    assert props["$automl_score"] == pytest.approx(0.7)  # last sorted proba = positive
    assert props["$automl_score_column"] == "proba_1"
    # The fixture `_make_active_pipeline_with_winning_run` builds a pipeline
    # with config={"target_event": "uploaded_file", "horizon_days": 14}.
    # Verify those flow through as self-describing properties.
    assert props["$automl_target_event"] == "uploaded_file"
    assert props["$automl_horizon_days"] == 14
    assert props["$automl_outcome_description"] == "P(uploaded_file within 14 days)"


def test_outcome_description_shapes():
    """Inline coverage of the human-label helper across task types."""
    from products.automl.backend.inference.emit import _outcome_description

    assert (
        _outcome_description(
            target_event="upgraded_plan", framing="adoption", horizon_days=14, task_type="classification"
        )
        == "P(upgraded_plan within 14 days) — adoption"
    )
    assert (
        _outcome_description(target_event="churned", framing="", horizon_days=30, task_type="classification")
        == "P(churned within 30 days)"
    )
    assert (
        _outcome_description(target_event="ltv", framing="", horizon_days=None, task_type="regression")
        == "Predicted ltv (regression)"
    )
    assert (
        _outcome_description(target_event="", framing="behavior", horizon_days=None, task_type="clustering")
        == "Cluster assignment (behavior)"
    )
    assert (
        _outcome_description(target_event="revenue", framing="", horizon_days=None, task_type="forecasting")
        == "Forecast of revenue"
    )


@pytest.mark.django_db
def test_emit_predictions_writes_person_property_when_output_property_set(team, user):
    """When pipeline.output_property_name is set, emission adds a `$set` block
    so the score lands on the person profile (queryable from cohorts/flags)."""
    # Build a custom pipeline with output_property_name set — _make_active fixture
    # doesn't carry it through but the underlying contract field does.
    from products.automl.backend.facade.enums import PipelineStatus

    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="emit_with_output_prop",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
            output_property_name="automl_p_test",
        ),
    )
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.BOOTSTRAP_PENDING)
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.ACTIVE)

    # Skip the champion-version requirement by going straight to the emit
    # function — it doesn't require the facade.infer happy path for unit work.
    run = logic.create_pipeline_run(
        team_id=team.id,
        pipeline_id=dto.id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.INFERENCE,
            task_slug="emit_with_output_prop",
            task_workspace_root="s3://automl/tasks/emit_with_output_prop",
        ),
    )
    run.inference_result = {
        "predictions_uri": "s3://fake/predictions.parquet",
        "id_column": "person_id",
    }
    run.status = RunStatus.SUCCEEDED.value
    run.save(update_fields=["inference_result", "status", "updated_at"])

    fake_table = _fake_predictions_table(n_rows=2)
    with (
        patch("products.automl.backend.inference.emit._read_predictions", return_value=fake_table),
        patch("products.automl.backend.inference.emit.capture_internal", return_value=_ok_response()) as mock_capture,
    ):
        emitted = emit.emit_predictions_for_run(run)

    assert emitted == 2
    first_props = mock_capture.call_args_list[0].kwargs["properties"]
    assert "$set" in first_props, "output_property_name should drive a `$set` block"
    assert first_props["$set"] == {"automl_p_test": pytest.approx(0.7)}
    # process_person_profile must be true so the $set sticks.
    assert mock_capture.call_args_list[0].kwargs["process_person_profile"] is True


@pytest.mark.django_db
def test_emit_predictions_skips_when_id_column_missing(team, user):
    """If the parquet doesn't carry the configured id_column, refuse to emit
    (rather than silently distinct_id-ing on the wrong field)."""
    manifest = {"predictions_uri": "s3://fake/predictions.parquet", "id_column": "person_id"}
    _, run = _make_succeeded_inference_run(team.id, name="emit_no_id_col", manifest=manifest, user_id=user.id)

    fake_table = _fake_predictions_table(n_rows=3, include_id=False)
    with (
        patch("products.automl.backend.inference.emit._read_predictions", return_value=fake_table),
        patch("products.automl.backend.inference.emit.capture_internal") as mock_capture,
    ):
        emitted = emit.emit_predictions_for_run(run)

    assert emitted == 0
    mock_capture.assert_not_called()


@pytest.mark.django_db
def test_emit_predictions_continues_on_per_row_capture_failure(team, user):
    """One bad row shouldn't drop the whole batch — we log and continue.
    Returns the count of *successfully* emitted events."""
    manifest = {"predictions_uri": "s3://fake/predictions.parquet", "id_column": "person_id"}
    _, run = _make_succeeded_inference_run(team.id, name="emit_partial_fail", manifest=manifest, user_id=user.id)

    fake_table = _fake_predictions_table(n_rows=3)

    # Second call raises; first + third succeed.
    bad_response = MagicMock()
    bad_response.raise_for_status.side_effect = RuntimeError("capture-rs 500")
    with (
        patch("products.automl.backend.inference.emit._read_predictions", return_value=fake_table),
        patch(
            "products.automl.backend.inference.emit.capture_internal",
            side_effect=[_ok_response(), bad_response, _ok_response()],
        ),
    ):
        emitted = emit.emit_predictions_for_run(run)

    assert emitted == 2


@pytest.mark.django_db
def test_emit_predictions_zero_rows_returns_zero(team, user):
    """Empty parquet — 0 emitted, no HTTP calls."""
    manifest = {"predictions_uri": "s3://fake/predictions.parquet", "id_column": "person_id"}
    _, run = _make_succeeded_inference_run(team.id, name="emit_zero_rows", manifest=manifest, user_id=user.id)

    empty_table = pa.Table.from_pydict({"person_id": [], "prediction": [], "proba_0": [], "proba_1": []})
    with (
        patch("products.automl.backend.inference.emit._read_predictions", return_value=empty_table),
        patch("products.automl.backend.inference.emit.capture_internal") as mock_capture,
    ):
        emitted = emit.emit_predictions_for_run(run)

    assert emitted == 0
    mock_capture.assert_not_called()


# ---- Integration: record_inference_outcome fires emit on SUCCEEDED ----


@pytest.mark.django_db
def test_record_inference_outcome_succeeded_triggers_emit(team, user):
    """The auto-hook in logic.record_inference_outcome calls emit on SUCCEEDED."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="emit_auto_hook")
    from products.tasks.backend.models import Task

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    with patch("products.automl.backend.inference.emit.emit_predictions_for_run", return_value=5) as mock_emit:
        api.record_inference_outcome(
            team_id=team.id,
            run_id=run_dto.id,
            params=contracts.RecordInferenceOutcomeInput(
                status=RunStatus.SUCCEEDED,
                outcome_report="ok",
                inference_result={"predictions_uri": "s3://fake/p.parquet"},
            ),
        )

    mock_emit.assert_called_once()
    emitted_run_arg = mock_emit.call_args.args[0]
    assert emitted_run_arg.id == run_dto.id


@pytest.mark.django_db
def test_record_inference_outcome_failed_skips_emit(team, user):
    """Failed runs must NOT emit — no predictions to score."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="emit_skip_on_fail")
    from products.tasks.backend.models import Task

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    with patch("products.automl.backend.inference.emit.emit_predictions_for_run") as mock_emit:
        api.record_inference_outcome(
            team_id=team.id,
            run_id=run_dto.id,
            params=contracts.RecordInferenceOutcomeInput(
                status=RunStatus.FAILED,
                outcome_report="bailed",
                failure_reason="snapshot_fetch_failed",
            ),
        )

    mock_emit.assert_not_called()


@pytest.mark.django_db
def test_record_inference_outcome_swallows_emit_exception(team, user):
    """Emission failure must NOT cause the MCP record call to fail — the run
    is already terminal at this point; emission is best-effort and rebuildable."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="emit_swallow_exc")
    from products.tasks.backend.models import Task

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    with patch(
        "products.automl.backend.inference.emit.emit_predictions_for_run",
        side_effect=RuntimeError("s3 down"),
    ):
        # Should NOT raise — emission errors are logged + swallowed.
        dto = api.record_inference_outcome(
            team_id=team.id,
            run_id=run_dto.id,
            params=contracts.RecordInferenceOutcomeInput(
                status=RunStatus.SUCCEEDED,
                outcome_report="ok",
                inference_result={"predictions_uri": "s3://fake/p.parquet"},
            ),
        )
    assert dto.status == RunStatus.SUCCEEDED
