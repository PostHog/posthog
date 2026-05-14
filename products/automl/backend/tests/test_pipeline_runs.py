"""Tests for the AutoMLPipelineRun lifecycle — open, record EDA, record outcome,
plus the linkage from `record_training_result(run_id=...)` to the run row."""

import uuid

import pytest

from products.automl.backend import logic
from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import ModelRole, RunKind, RunStatus, TaskType
from products.automl.backend.models import AutoMLPipelineRun


def _make_pipeline(team_id: int, name: str = "pipeline_runs_unit"):
    """Create a pipeline via the facade and return its ORM instance."""
    dto = api.create(
        team_id=team_id,
        params=contracts.CreatePipelineInput(
            name=name,
            task_type=TaskType.CLASSIFICATION,
            config={"target_event": "uploaded_file", "horizon_days": 14},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    pipeline = logic.get_pipeline(team_id=team_id, pipeline_id=dto.id)
    assert pipeline is not None
    return pipeline


def _open_run(team_id, pipeline_id, *, run_kind=RunKind.BOOTSTRAP, task_slug="weekly_churn"):
    return api.list_runs_for_pipeline(team_id=team_id, pipeline_id=pipeline_id), logic.create_pipeline_run(
        team_id=team_id,
        pipeline_id=pipeline_id,
        params=contracts.CreatePipelineRunInput(
            run_kind=run_kind,
            task_slug=task_slug,
            task_workspace_root=f"s3://automl/tasks/{task_slug}",
        ),
    )


@pytest.mark.django_db
def test_create_pipeline_run_starts_in_running_status(team):
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    assert run.status == RunStatus.RUNNING.value
    assert run.run_kind == RunKind.BOOTSTRAP.value
    assert run.task_slug == "weekly_churn"
    assert run.task_workspace_root == "s3://automl/tasks/weekly_churn"
    assert run.completed_at is None
    assert run.failure_reason == ""
    assert run.team_id == team.id


@pytest.mark.django_db
def test_create_pipeline_run_fails_closed_on_unknown_pipeline(team):
    """A non-existent pipeline id raises PipelineNotFoundError before any write happens —
    the same fail-closed path catches cross-team-leaked ids."""
    with pytest.raises(contracts.PipelineNotFoundError):
        logic.create_pipeline_run(
            team_id=team.id,
            pipeline_id=uuid.uuid4(),
            params=contracts.CreatePipelineRunInput(
                run_kind=RunKind.BOOTSTRAP,
                task_slug="x",
                task_workspace_root="s3://automl/tasks/x",
            ),
        )


@pytest.mark.django_db
def test_record_eda_result_stashes_payload_and_cli_run_id(team):
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    payload = {
        "n_rows": 217,
        "n_cols": 14,
        "target_type": "binary",
        "class_balance": {"positive_share": 0.193},
        "top_signal_features": [{"name": "active_days_14d", "mi": 0.18}],
    }
    dto = api.record_eda_result(
        team_id=team.id,
        run_id=run.id,
        params=contracts.RecordEdaResultInput(eda_result=payload, cli_run_id="20260514T130000Z"),
    )

    assert dto.eda_result == payload
    assert dto.cli_run_id == "20260514T130000Z"
    # Status hasn't moved — EDA is mid-run, not terminal.
    assert dto.status == RunStatus.RUNNING


@pytest.mark.django_db
def test_record_eda_result_raises_when_run_not_found(team):
    with pytest.raises(contracts.PipelineRunNotFoundError):
        api.record_eda_result(
            team_id=team.id,
            run_id=uuid.uuid4(),
            params=contracts.RecordEdaResultInput(eda_result={}),
        )


@pytest.mark.django_db
def test_record_bootstrap_outcome_flips_to_succeeded(team):
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    dto = api.record_bootstrap_outcome(
        team_id=team.id,
        run_id=run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.SUCCEEDED,
            outcome_report="# Outcome\n\nChampion promoted, metrics clean.",
            agent_session_id="sess_abc123",
        ),
    )

    assert dto.status == RunStatus.SUCCEEDED
    assert dto.outcome_report.startswith("# Outcome")
    assert dto.agent_session_id == "sess_abc123"
    assert dto.completed_at is not None
    assert dto.failure_reason == ""


@pytest.mark.django_db
def test_record_bootstrap_outcome_flips_to_failed_with_reason(team):
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    dto = api.record_bootstrap_outcome(
        team_id=team.id,
        run_id=run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.FAILED,
            outcome_report="# Outcome\n\nTraining bailed — see failure_reason.",
            failure_reason="snapshot_fetch_failed",
        ),
    )

    assert dto.status == RunStatus.FAILED
    assert dto.failure_reason == "snapshot_fetch_failed"
    assert dto.completed_at is not None


@pytest.mark.django_db
def test_record_bootstrap_outcome_rejects_running_status(team):
    """``running`` is the open-state hint, not a terminal one — must reject."""
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    with pytest.raises(ValueError, match="terminal status"):
        api.record_bootstrap_outcome(
            team_id=team.id,
            run_id=run.id,
            params=contracts.RecordBootstrapOutcomeInput(
                status=RunStatus.RUNNING,
                outcome_report="",
            ),
        )


@pytest.mark.django_db
def test_record_bootstrap_outcome_is_idempotent_after_terminal(team):
    """Second call no-ops — agent retries after transient blips don't overwrite the timeline."""
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    first = api.record_bootstrap_outcome(
        team_id=team.id,
        run_id=run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.SUCCEEDED,
            outcome_report="first call",
        ),
    )
    # Second call with different content — should be a no-op and return the original.
    second = api.record_bootstrap_outcome(
        team_id=team.id,
        run_id=run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.FAILED,
            outcome_report="trying to overwrite",
            failure_reason="should not stick",
        ),
    )

    assert second.status == first.status == RunStatus.SUCCEEDED
    assert second.outcome_report == "first call"
    assert second.failure_reason == ""


@pytest.mark.django_db
def test_mark_run_failed_is_idempotent(team):
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    failed_once = logic.mark_run_failed(run=run, failure_reason="task_create_failed")
    assert failed_once.status == RunStatus.FAILED.value
    assert failed_once.completed_at is not None

    # Refetch + call again — second call should not move the row.
    refreshed = logic.get_pipeline_run(team_id=team.id, run_id=run.id)
    assert refreshed is not None
    failed_twice = logic.mark_run_failed(run=refreshed, failure_reason="another_reason")
    assert failed_twice.failure_reason == "task_create_failed"


@pytest.mark.django_db
def test_record_training_result_links_run_with_denormalized_summary(team):
    """Passing `run_id` to record_training_result updates the run with
    a compact training summary and the created model version id."""
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    leaderboard = [{"model": f"M{i}", "score_test": 0.8 - 0.01 * i} for i in range(10)]
    version_dto = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=contracts.RecordTrainingResultInput(
            metrics={"roc_auc": 0.81, "log_loss": 0.42},
            leaderboard=leaderboard,
            eval_metric="roc_auc",
            problem_type="binary",
        ),
        run_id=run.id,
    )

    refreshed = api.get_run(team_id=team.id, run_id=run.id)
    assert refreshed is not None
    assert refreshed.created_model_version_id == version_dto.id
    # Compact summary keeps top 5 leaderboard rows + scalar metrics — full
    # leaderboard remains on AutoMLModelVersion.
    assert refreshed.training_result["metrics"] == {"roc_auc": 0.81, "log_loss": 0.42}
    assert len(refreshed.training_result["leaderboard_top5"]) == 5
    assert refreshed.training_result["eval_metric"] == "roc_auc"


@pytest.mark.django_db
def test_record_training_result_with_unknown_run_id_raises(team):
    pipeline = _make_pipeline(team.id)
    with pytest.raises(contracts.PipelineRunNotFoundError):
        api.record_training_result(
            team_id=team.id,
            pipeline_id=pipeline.id,
            params=contracts.RecordTrainingResultInput(metrics={}, leaderboard=[]),
            run_id=uuid.uuid4(),
        )


@pytest.mark.django_db
def test_list_runs_returns_newest_first(team):
    pipeline = _make_pipeline(team.id)
    _, run_a = _open_run(team.id, pipeline.id, task_slug="slug_a")
    _, run_b = _open_run(team.id, pipeline.id, task_slug="slug_b")
    _, run_c = _open_run(team.id, pipeline.id, task_slug="slug_c")

    runs = api.list_runs_for_pipeline(team_id=team.id, pipeline_id=pipeline.id)
    assert [r.id for r in runs] == [run_c.id, run_b.id, run_a.id]


@pytest.mark.django_db
def test_get_run_returns_none_for_unknown_id(team):
    assert api.get_run(team_id=team.id, run_id=uuid.uuid4()) is None


@pytest.mark.django_db
def test_partial_unique_constraint_still_holds_with_runs_present(team):
    """Sanity: AutoMLModelVersion's at-most-one-champion-per-pipeline constraint
    is unaffected by the new run table — runs live alongside, not in the
    versions' role lifecycle."""
    pipeline = _make_pipeline(team.id)
    _, run = _open_run(team.id, pipeline.id)

    # Record two versions via the run, second should land as challenger because
    # the unique constraint still rules at the version table.
    api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=contracts.RecordTrainingResultInput(metrics={"roc_auc": 0.7}, leaderboard=[], role=ModelRole.CHALLENGER),
        run_id=run.id,
    )
    versions = api.list_model_versions(team_id=team.id, pipeline_id=pipeline.id)
    assert len(versions) == 1
    assert versions[0].role == ModelRole.CHALLENGER


@pytest.mark.django_db
def test_run_row_renders_in_model_str_for_admin():
    """`__str__` carries enough info for the Django admin / shell to identify a row."""
    run = AutoMLPipelineRun(
        team_id=1,
        run_kind=RunKind.BOOTSTRAP.value,
        status=RunStatus.RUNNING.value,
        task_slug="weekly_churn",
    )
    rendered = str(run)
    assert "bootstrap" in rendered
    assert "running" in rendered
