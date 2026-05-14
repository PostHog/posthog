"""Tests for the inference flow — facade, dispatch, brief, record-outcome.

Mirrors test_retrain.py's shape. Inference reuses the active-pipeline
fixture from test_retrain so we don't redefine the bootstrap-then-promote
ladder. The skill on disk is covered by the test_skill_* patterns at the
bottom; the in-process facade + brief + state-machine bits live up top.
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
from products.automl.backend.inference import dispatch as inference_dispatch
from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

from .test_retrain import _make_active_pipeline_with_winning_run

_REPO_ROOT = Path(__file__).resolve().parents[4]
_INFERENCE_SKILL_ROOT = _REPO_ROOT / "products" / "automl" / "skills" / "automl-inference"


def _extract_named_json_block(brief: str, label: str) -> dict:
    """Pull a labeled JSON block out of the brief (mirror of test_retrain helper)."""
    heading = re.compile(rf"^## {re.escape(label)}\b", re.MULTILINE)
    m = heading.search(brief)
    assert m is not None, f"Heading '## {label}' not found in brief"
    fence_start = brief.index("```json\n", m.end()) + len("```json\n")
    fence_end = brief.index("```", fence_start)
    return json.loads(brief[fence_start:fence_end])


# ---- Facade preconditions ----


@pytest.mark.django_db
def test_infer_rejects_non_active_pipelines(team):
    """Inference only runs against ACTIVE pipelines. Anything else (DRAFT,
    BOOTSTRAP_PENDING, FAILED, ARCHIVED) must raise InferenceNotApplicableError."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="infer_draft_unit",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    with pytest.raises(contracts.InferenceNotApplicableError, match="must be ACTIVE"):
        api.infer(team_id=team.id, pipeline_id=dto.id, user_id=1)


@pytest.mark.django_db
def test_infer_rejects_active_pipeline_with_no_winning_run(team):
    """ACTIVE pipeline but no champion to score with — explicit guard so the
    user knows to bootstrap first instead of getting a confusing CLI error."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="infer_active_no_winner",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
        ),
    )
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.BOOTSTRAP_PENDING)
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.ACTIVE)

    with pytest.raises(contracts.InferenceNotApplicableError, match="no champion"):
        api.infer(team_id=team.id, pipeline_id=dto.id, user_id=1)


# ---- Facade happy path + Task dispatch ----


@pytest.mark.django_db
def test_infer_opens_run_with_parent_id_and_enqueues_task(team, user):
    """The happy path: ACTIVE pipeline + winning run → infer opens a new
    INFERENCE run chained to the parent + dispatches a Task with the
    inference brief + AutoML sandbox template."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_happy")

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid.uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    # Run is INFERENCE-kind chained to the parent.
    assert run_dto.run_kind == RunKind.INFERENCE
    assert run_dto.status == RunStatus.RUNNING
    assert run_dto.parent_run_id == winning_run.id
    assert run_dto.task_slug == "infer_happy"
    assert run_dto.task_workspace_root == "s3://automl/tasks/infer_happy"
    assert run_dto.task_id is not None
    # No inference manifest yet — agent populates it via record_inference_outcome.
    assert run_dto.inference_result == {}

    # Task.create_and_run kwargs.
    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs["origin_product"] == Task.OriginProduct.AUTOML
    assert kwargs["mode"] == "background"
    assert kwargs["create_pr"] is False
    assert kwargs["sandbox_template"] == SandboxTemplate.AUTOML
    assert kwargs["title"].startswith("AutoML inference:")

    # Pipeline status stays ACTIVE.
    pipeline_refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_refreshed is not None
    assert pipeline_refreshed.status == PipelineStatus.ACTIVE


@pytest.mark.django_db
def test_infer_marks_run_failed_on_task_create_exception(team, user):
    """If Task.create_and_run blows up, the inference run gets failure_reason=
    task_create_failed and the durable record reflects the attempt. Pipeline
    stays ACTIVE because inference failures don't fail the pipeline."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_task_fail")

    with patch.object(Task, "create_and_run", side_effect=RuntimeError("temporal down")):
        with pytest.raises(RuntimeError, match="temporal down"):
            api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    runs = api.list_runs_for_pipeline(team_id=team.id, pipeline_id=pipeline_dto.id)
    inference_runs = [r for r in runs if r.run_kind == RunKind.INFERENCE]
    assert len(inference_runs) == 1
    assert inference_runs[0].status == RunStatus.FAILED
    assert inference_runs[0].failure_reason == "task_create_failed"
    assert inference_runs[0].completed_at is not None

    pipeline_refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_refreshed is not None
    assert pipeline_refreshed.status == PipelineStatus.ACTIVE


# ---- record_inference_outcome behavior ----


@pytest.mark.django_db
def test_record_inference_outcome_stamps_manifest_and_terminalizes(team, user):
    """The agent's only MCP checkpoint: stamps the full CLI manifest into
    inference_result and flips status terminal. Pipeline stays ACTIVE."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_record")

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid.uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    manifest = {
        "task": "infer_record",
        "stage": "completed",
        "features_run_id": "20260514T120000Z",
        "features_uri": "s3://automl/tasks/infer_record/runs/20260514T120000Z/features.parquet",
        "features_rows": 287,
        "model_run_id": "20260513T214213Z",
        "inference_run_id": "20260514T120100Z",
        "predictions_uri": "s3://automl/tasks/infer_record/predictions/20260514T120100Z.parquet",
        "predictions_count": 287,
        "manifest_uri": "s3://automl/tasks/infer_record/predictions/20260514T120100Z.manifest.yaml",
        "estimate": {"verdict": "ok", "event_rows": 247437, "approx_persons": 287},
    }
    refreshed = api.record_inference_outcome(
        team_id=team.id,
        run_id=run_dto.id,
        params=contracts.RecordInferenceOutcomeInput(
            status=RunStatus.SUCCEEDED,
            outcome_report="## Inference complete\n\nScored 287 rows.",
            inference_result=manifest,
            agent_session_id="ses-abc",
        ),
    )

    assert refreshed.status == RunStatus.SUCCEEDED
    assert refreshed.completed_at is not None
    assert refreshed.outcome_report.startswith("## Inference complete")
    assert refreshed.inference_result == manifest
    assert refreshed.agent_session_id == "ses-abc"

    # Pipeline still ACTIVE.
    pipeline_refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_refreshed is not None
    assert pipeline_refreshed.status == PipelineStatus.ACTIVE


@pytest.mark.django_db
def test_record_inference_outcome_idempotent_on_second_call(team, user):
    """Second call on a terminal run is a no-op (returns existing row).
    Friendlier than 409 — agent retries after transient blips are safe."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_idem")

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid.uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    first = api.record_inference_outcome(
        team_id=team.id,
        run_id=run_dto.id,
        params=contracts.RecordInferenceOutcomeInput(
            status=RunStatus.SUCCEEDED,
            outcome_report="first",
            inference_result={"predictions_count": 100},
        ),
    )
    second = api.record_inference_outcome(
        team_id=team.id,
        run_id=run_dto.id,
        params=contracts.RecordInferenceOutcomeInput(
            status=RunStatus.SUCCEEDED,
            outcome_report="SECOND attempt — should not overwrite",
            inference_result={"predictions_count": 999},
        ),
    )
    assert second.outcome_report == "first"
    assert second.inference_result == {"predictions_count": 100}
    assert second.completed_at == first.completed_at


@pytest.mark.django_db
def test_record_inference_outcome_rejects_running_status(team, user):
    """Terminal status required — running is an open-state hint, not a finish."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_running_reject")

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid.uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    with pytest.raises(ValueError, match="terminal status"):
        api.record_inference_outcome(
            team_id=team.id,
            run_id=run_dto.id,
            params=contracts.RecordInferenceOutcomeInput(
                status=RunStatus.RUNNING,
                outcome_report="",
            ),
        )


@pytest.mark.django_db
def test_record_inference_outcome_rejects_non_inference_runs(team):
    """Bootstrap and retrain runs have their own outcome handler; this one is
    INFERENCE-only so an accidental wiring mistake is loud, not silent."""
    _pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_kind_guard")

    # winning_run is a BOOTSTRAP run.
    with pytest.raises(ValueError, match="record_bootstrap_outcome"):
        api.record_inference_outcome(
            team_id=team.id,
            run_id=winning_run.id,
            params=contracts.RecordInferenceOutcomeInput(
                status=RunStatus.SUCCEEDED,
                outcome_report="should not work",
            ),
        )


@pytest.mark.django_db
def test_record_inference_outcome_does_not_change_pipeline_status(team, user):
    """Failed inference must NOT touch pipeline state. Champion keeps serving."""
    pipeline_dto, _, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_no_pipe_transition")

    with patch.object(Task, "create_and_run") as mock_create:
        mock_create.return_value.id = uuid.uuid4()
        run_dto = api.infer(team_id=team.id, pipeline_id=pipeline_dto.id, user_id=user.id)

    api.record_inference_outcome(
        team_id=team.id,
        run_id=run_dto.id,
        params=contracts.RecordInferenceOutcomeInput(
            status=RunStatus.FAILED,
            outcome_report="bailed",
            failure_reason="snapshot_fetch_failed",
        ),
    )
    refreshed = api.get(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert refreshed is not None
    assert refreshed.status == PipelineStatus.ACTIVE


# ---- Brief construction ----


@pytest.mark.django_db
def test_inference_brief_has_run_context_and_thin_pointer(team):
    """The inference brief carries the canonical sections + thin-pointer to skill."""
    pipeline_dto, winning_run, _ = _make_active_pipeline_with_winning_run(team.id, name="infer_brief_unit")
    from products.automl.backend.logic import get_pipeline

    pipeline_orm = get_pipeline(team_id=team.id, pipeline_id=pipeline_dto.id)
    assert pipeline_orm is not None
    run_id = uuid.UUID("00000000-0000-0000-0000-0000000feed2")
    brief = inference_dispatch._build_inference_brief(
        pipeline_orm,
        run_id=run_id,
        task_slug="infer_brief_unit",
        task_workspace_root="s3://automl/tasks/infer_brief_unit",
        parent_run=winning_run,
    )

    assert "automl-inference" in brief, "brief must point at the inference skill"
    # Single-shot framing — explicit cross-reference to the CLI contract.
    assert "automl refresh-task" in brief
    assert "schedule-refresh.md" in brief, "brief must link to CLI's integration-contract skill"

    for required_heading in (
        "## Run context",
        "## Pipeline spec",
        "## Inference-population HogQL",
    ):
        assert required_heading in brief, f"missing required section '{required_heading}'"

    # Run context carries the inference-specific keys.
    ctx = _extract_named_json_block(brief, "Run context")
    assert ctx["run_id"] == str(run_id)
    assert ctx["parent_run_id"] == str(winning_run.id)
    assert ctx["task_slug"] == "infer_brief_unit"
    assert ctx["s3_endpoint"] == "http://host.docker.internal:19000"


@pytest.mark.django_db
def test_inference_brief_uses_inference_population_query(team):
    """The brief must carry the *inference* HogQL, not the training one."""
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="infer_query_unit",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={"kind": "hogql", "query": "SELECT 1 AS train"},
            inference_population={"kind": "hogql", "query": "SELECT 2 AS infer"},
        ),
    )
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.BOOTSTRAP_PENDING)
    logic.transition_pipeline(team_id=team.id, pipeline_id=dto.id, new_status=PipelineStatus.ACTIVE)

    from products.automl.backend.logic import get_pipeline

    pipeline_orm = get_pipeline(team_id=team.id, pipeline_id=dto.id)
    assert pipeline_orm is not None
    # Build a fake parent run just for the brief's parent_run_id field.
    fake_parent = logic.create_pipeline_run(
        team_id=team.id,
        pipeline_id=dto.id,
        params=contracts.CreatePipelineRunInput(
            run_kind=RunKind.BOOTSTRAP,
            task_slug="infer_query_unit",
            task_workspace_root="s3://automl/tasks/infer_query_unit",
        ),
    )
    brief = inference_dispatch._build_inference_brief(
        pipeline_orm,
        run_id=uuid.uuid4(),
        task_slug="infer_query_unit",
        task_workspace_root="s3://automl/tasks/infer_query_unit",
        parent_run=fake_parent,
    )
    # The inference HogQL must land inside the dedicated section's code fence,
    # not (just) inside the spec JSON. Pin the section.
    section = brief.split("## Inference-population HogQL", 1)[1]
    assert "```hogql" in section
    fenced = section.split("```hogql", 1)[1].split("```", 1)[0]
    assert "SELECT 2 AS infer" in fenced
    assert "SELECT 1 AS train" not in fenced, "training query must not appear in the inference HogQL fence"


# ---- Skill on disk ----


def test_inference_skill_folder_exists_with_required_files():
    """The inference skill is the canonical PostHog-side scoring contract."""
    assert _INFERENCE_SKILL_ROOT.is_dir(), f"skill folder missing: {_INFERENCE_SKILL_ROOT}"
    assert (_INFERENCE_SKILL_ROOT / "SKILL.md").is_file(), "SKILL.md missing"


def test_inference_skill_md_has_required_anchors():
    """SKILL.md must carry the load-bearing pieces: frontmatter, single-shot
    framing, the one CLI invocation, the one MCP checkpoint."""
    body = (_INFERENCE_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert body.startswith("---\n"), "SKILL.md missing YAML frontmatter"
    assert "name: automl-inference" in body
    assert "description:" in body

    # CLI cross-reference — single-shot via refresh-task.
    assert "automl refresh-task" in body
    assert "schedule-refresh.md" in body

    # The one MCP checkpoint.
    assert "automl-record-inference-outcome" in body

    # Single-shot framing — explicit "no training" / "no displacement".
    assert "no training" in body.lower() or "doesn't iterate" in body.lower()

    # Failure-reason tags surfaced for the agent to use.
    for failure_tag in ("snapshot_fetch_failed", "model_load_failed", "predict_crashed"):
        assert failure_tag in body, f"SKILL.md missing failure_reason tag {failure_tag!r}"
