"""Tests for the retrain flow — facade, parent-run discovery, brief construction.

Mirrors test_bootstrap.py's shape. The retrain skill on disk is covered by
the same `test_skill_*` patterns; here we exercise the in-process facade +
brief + state-machine bits.
"""

import re
import json
import uuid
from pathlib import Path

import pytest
from unittest.mock import patch

from products.automl.backend import logic
from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import PipelineStatus, RunKind, RunStatus, TaskType
from products.automl.backend.training import retrain
from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RETRAIN_SKILL_ROOT = _REPO_ROOT / "products" / "automl" / "skills" / "automl-retrain"


def _make_active_pipeline_with_winning_run(team_id: int, *, name: str = "retrain_unit"):
    """Set up the steady state: a pipeline that completed bootstrap and has
    a winning run (succeeded + created_model_version_id non-null).

    Returns (pipeline_dto, winning_run, version_dto).
    """
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
    # Move pipeline to BOOTSTRAP_PENDING (in the real flow, `api.start` does
    # this then enqueues a Task — bypassing the Task enqueue for tests).
    logic.transition_pipeline(team_id=team_id, pipeline_id=dto.id, new_status=PipelineStatus.BOOTSTRAP_PENDING)
    # Open a bootstrap run + record a training result linked to it.
    run = logic.create_pipeline_run(
        team_id=team_id,
        pipeline_id=dto.id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.BOOTSTRAP,
            task_slug=name,
            task_workspace_root=f"s3://automl/tasks/{name}",
        ),
    )
    version = api.record_training_result(
        team_id=team_id,
        pipeline_id=dto.id,
        params=contracts.RecordTrainingResultInput(
            metrics={"accuracy": 0.7, "score_test": 0.7},
            leaderboard=[{"model": "M1", "score_test": 0.7}],
            eval_metric="accuracy",
        ),
        run_id=run.id,
    )
    # Promote the version to champion — the real bootstrap flow does this
    # after the gate check passes; here we just go straight there.
    api.promote_to_champion(team_id=team_id, model_version_id=version.id)
    # Flip the run to succeeded (this transitions the pipeline to ACTIVE).
    api.record_bootstrap_outcome(
        team_id=team_id,
        run_id=run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.SUCCEEDED,
            outcome_report="# Bootstrap done",
        ),
    )
    refreshed = api.get(team_id=team_id, pipeline_id=dto.id)
    assert refreshed is not None
    assert refreshed.status == PipelineStatus.ACTIVE, "bootstrap success must lift pipeline to ACTIVE"
    winning_run = logic.get_pipeline_run(team_id=team_id, run_id=run.id)
    assert winning_run is not None
    return refreshed, winning_run, version


@pytest.mark.django_db
def test_record_bootstrap_outcome_lifts_pipeline_to_active_on_success(team):
    """Successful bootstrap with a champion = pipeline → ACTIVE.

    Without this, retrain can't ever start. Pinning the transition explicitly."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id)
    assert pipeline_dto.status == PipelineStatus.ACTIVE
    assert winning_run.status == RunStatus.SUCCEEDED.value
    assert winning_run.completed_at is not None


@pytest.mark.django_db
def test_record_bootstrap_outcome_flips_pipeline_to_failed_on_bootstrap_failure(team):
    """Failed bootstrap = pipeline → FAILED so the user can see and retry."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="bootstrap_fail_unit",
            task_type=TaskType.CLASSIFICATION,
            config={"target_event": "uploaded_file"},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    # Move to BOOTSTRAP_PENDING manually (simulate what `start` does).
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.BOOTSTRAP_PENDING)
    run = logic.create_pipeline_run(
        team_id=team.id,
        pipeline_id=dto.id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.BOOTSTRAP,
            task_slug="x",
            task_workspace_root="s3://automl/tasks/x",
        ),
    )
    api.record_bootstrap_outcome(
        team_id=team.id,
        run_id=run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.FAILED,
            outcome_report="# Bootstrap bailed",
            failure_reason="population_too_small",
        ),
    )
    refreshed = api.get(team_id=team.id, pipeline_id=dto.id)
    assert refreshed is not None
    assert refreshed.status == PipelineStatus.FAILED


@pytest.mark.django_db
def test_find_latest_winning_run_returns_most_recent_succeeded_with_version(team):
    """Parent-run discovery: pick the newest succeeded run that landed a model
    version. Earlier runs (succeeded-but-no-version, or running) must be skipped."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id)

    # Open a second run that's still running — must NOT be picked.
    in_flight = logic.create_pipeline_run(
        team_id=team.id,
        pipeline_id=pipeline_dto.id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.RETRAIN,
            task_slug="retrain_unit",
            task_workspace_root="s3://automl/tasks/retrain_unit",
            parent_run_id=winning_run.id,
        ),
    )
    assert in_flight.status == RunStatus.RUNNING.value

    latest = logic.find_latest_winning_run(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert latest is not None
    assert latest.id == winning_run.id


@pytest.mark.django_db
def test_find_latest_winning_run_returns_none_when_no_winner(team):
    """No succeeded-with-version run = no parent."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="no_winner_unit",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    assert logic.find_latest_winning_run(team_id=team.id, pipeline_id=dto.id) is None


@pytest.mark.django_db
def test_retrain_rejects_non_active_pipelines(team):
    """Retrain only makes sense on ACTIVE pipelines. DRAFT, FAILED, BOOTSTRAP_*
    must all be rejected with RetrainNotApplicableError."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="draft_unit",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    # Pipeline is DRAFT — retrain must reject.
    with pytest.raises(contracts.RetrainNotApplicableError, match="must be ACTIVE"):
        api.retrain(team_id=team.id, pipeline_id=dto.id, user_id=1)


@pytest.mark.django_db
def test_retrain_rejects_active_pipeline_with_no_winning_run(team):
    """ACTIVE-but-no-winner shouldn't be possible in practice, but if it
    happens (manual state surgery, etc.), retrain must catch it explicitly
    so the user knows to bootstrap first."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="active_no_winner_unit",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    # Force pipeline to ACTIVE without a winning run.
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.BOOTSTRAP_PENDING)
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.ACTIVE)

    with pytest.raises(contracts.RetrainNotApplicableError, match="no winning run"):
        api.retrain(team_id=team.id, pipeline_id=dto.id, user_id=1)


@pytest.mark.django_db
def test_retrain_opens_run_with_parent_id_and_enqueues_task(team, user):
    """The happy path: ACTIVE pipeline + winning run → retrain opens a new
    RETRAIN run chained to the parent + dispatches a Task with the retrain
    brief + AutoML sandbox template."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id, name="retrain_happy")

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid.uuid4()
        run_dto = api.retrain(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    # The new run row is RETRAIN-kind chained to the parent.
    assert run_dto.run_kind == RunKind.RETRAIN
    assert run_dto.status == RunStatus.RUNNING
    assert run_dto.parent_run_id == winning_run.id
    assert run_dto.task_slug == "retrain_happy"
    assert run_dto.task_workspace_root == "s3://automl/tasks/retrain_happy"
    assert run_dto.task_id is not None

    # Task.create_and_run was called with the right kwargs.
    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["origin_product"] == Task.OriginProduct.AUTOML
    assert kwargs["mode"] == "background"
    assert kwargs["create_pr"] is False
    assert kwargs["sandbox_template"] == SandboxTemplate.AUTOML
    assert kwargs["title"].startswith("AutoML retrain:")

    # Pipeline status stays ACTIVE — retrain doesn't change pipeline state.
    pipeline_refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_refreshed is not None
    assert pipeline_refreshed.status == PipelineStatus.ACTIVE


@pytest.mark.django_db
def test_retrain_marks_run_failed_on_task_create_exception(team, user):
    """If Task.create_and_run blows up, the run row gets failure_reason=task_create_failed
    so the durable record reflects the attempt. Pipeline stays ACTIVE."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="retrain_task_fail")

    with patch.object(Task, "create_and_run", side_effect=RuntimeError("temporal down")):
        with pytest.raises(RuntimeError, match="temporal down"):
            api.retrain(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    # Find the failed retrain run on the pipeline.
    runs = api.list_runs_for_pipeline(team_id=team.id, pipeline_id=pipeline_dto.id)
    retrain_runs = [r for r in runs if r.run_kind == RunKind.RETRAIN]
    assert len(retrain_runs) == 1
    assert retrain_runs[0].status == RunStatus.FAILED
    assert retrain_runs[0].failure_reason == "task_create_failed"
    assert retrain_runs[0].completed_at is not None

    # Pipeline stays ACTIVE — champion keeps serving.
    pipeline_refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_refreshed is not None
    assert pipeline_refreshed.status == PipelineStatus.ACTIVE


@pytest.mark.django_db
def test_record_bootstrap_outcome_does_not_transition_pipeline_on_retrain_run(team):
    """Retrain run failures + successes must NOT touch pipeline state. The
    pipeline is already ACTIVE; champion keeps serving regardless."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id, name="retrain_no_pipe_transition")

    retrain_run = logic.create_pipeline_run(
        team_id=team.id,
        pipeline_id=pipeline_dto.id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.RETRAIN,
            task_slug="retrain_no_pipe_transition",
            task_workspace_root="s3://automl/tasks/retrain_no_pipe_transition",
            parent_run_id=winning_run.id,
        ),
    )
    # Flip the retrain run to FAILED — pipeline must NOT move.
    api.record_bootstrap_outcome(
        team_id=team.id,
        run_id=retrain_run.id,
        params=contracts.RecordBootstrapOutcomeInput(
            status=RunStatus.FAILED,
            outcome_report="# Retrain bailed",
            failure_reason="training_crash",
        ),
    )
    refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert refreshed is not None
    assert refreshed.status == PipelineStatus.ACTIVE, "retrain failure must NOT touch pipeline state"


def _extract_named_json_block(brief: str, label: str) -> dict:
    """Pull a labeled JSON block out of the brief (same helper shape as test_bootstrap)."""
    heading = re.compile(rf"^## {re.escape(label)}\b", re.MULTILINE)
    m = heading.search(brief)
    assert m is not None, f"Heading '## {label}' not found in brief"
    fence_start = brief.index("```json\n", m.end()) + len("```json\n")
    fence_end = brief.index("```", fence_start)
    return json.loads(brief[fence_start:fence_end])


@pytest.mark.django_db
def test_retrain_brief_has_run_context_parent_run_and_thin_pointer(team):
    """The retrain brief carries the canonical sections + the new Parent run block."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id, name="retrain_brief_unit")
    from products.automl.backend.logic import get_pipeline

    pipeline_orm = get_pipeline(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_orm is not None
    run_id = uuid.UUID("00000000-0000-0000-0000-0000000feed1")
    brief = retrain._build_retraining_brief(
        pipeline_orm,
        run_id=run_id,
        task_slug="retrain_brief_unit",
        task_workspace_root="s3://automl/tasks/retrain_brief_unit",
        parent_run=winning_run,
    )

    # The skill name is the load-bearing pointer.
    assert "automl-retrain" in brief
    # CLI cross-references must be present (thin-pointer contract).
    assert "automl-cli/skills/README.md" in brief
    for cli_skill in ("scope-modeling-task", "tune-hogql-query", "eda-on-features", "run-train-predict"):
        assert cli_skill in brief, f"retrain brief must mention CLI skill {cli_skill!r}"

    # All four canonical sections present.
    for required_heading in (
        "## Run context",
        "## Parent run",
        "## Pipeline spec",
        "## Promotion gates",
        "## Training-population HogQL",
    ):
        assert required_heading in brief, f"missing required section '{required_heading}'"

    # Run context includes parent_run_id (the retrain-specific addition).
    ctx = _extract_named_json_block(brief, "Run context")
    assert ctx["run_id"] == str(run_id)
    assert ctx["parent_run_id"] == str(winning_run.id)
    assert ctx["task_slug"] == "retrain_brief_unit"
    assert ctx["s3_endpoint"] == "http://host.docker.internal:19000"

    # Parent run summary has the keys the agent's decision tree consults.
    parent = _extract_named_json_block(brief, "Parent run")
    assert parent["run_id"] == str(winning_run.id)
    assert parent["run_kind"] == RunKind.BOOTSTRAP.value
    assert "training_summary" in parent
    assert "eda_summary" in parent
    assert parent["training_summary"]["metrics"] == {"accuracy": 0.7, "score_test": 0.7}


def test_retrain_skill_folder_exists_with_required_files():
    """The retrain skill is the canonical PostHog-side retraining contract."""
    assert _RETRAIN_SKILL_ROOT.is_dir(), f"skill folder missing: {_RETRAIN_SKILL_ROOT}"
    assert (_RETRAIN_SKILL_ROOT / "SKILL.md").is_file(), "SKILL.md missing"


def test_retrain_skill_md_has_required_anchors():
    """SKILL.md must carry the load-bearing pieces: frontmatter, CLI cross-ref,
    one-knob-per-iteration framing, three-gate logic."""
    body = (_RETRAIN_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert body.startswith("---\n"), "SKILL.md missing YAML frontmatter"
    assert "name: automl-retrain" in body
    assert "description:" in body

    # Cross-reference to CLI's decision tree + the four CLI skills.
    assert "automl-cli/skills/README.md" in body
    for cli_skill in ("scope-modeling-task", "tune-hogql-query", "eda-on-features", "run-train-predict"):
        assert cli_skill in body

    # The retrain-specific framing.
    assert "parent_run_id" in body
    assert "one knob" in body.lower() or "one knob per iteration" in body.lower()

    # Three-gate logic anchors.
    assert "Offline gate" in body
    assert "Realized gate" in body
    assert "Autonomy gate" in body

    # MCP tool checkpoints used by the retrain flow.
    for mcp_tool in (
        "automl-get-run",
        "automl-record-eda-result",
        "automl-record-training-result",
        "automl-promote-model-version",
        "automl-record-bootstrap-outcome",
    ):
        assert mcp_tool in body, f"SKILL.md missing MCP tool reference {mcp_tool!r}"
