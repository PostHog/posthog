"""Tests for the bootstrap bridge — `enqueue_bootstrap_training` and friends."""

import re
import json
from pathlib import Path

import pytest
from unittest.mock import patch

from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import TaskType
from products.automl.backend.training import bootstrap
from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import SandboxTemplate

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SKILL_ROOT = _REPO_ROOT / "products" / "automl" / "skills" / "automl-bootstrap"


def _make_pipeline(
    team_id: int,
    *,
    task_type: TaskType = TaskType.CLASSIFICATION,
    config: dict | None = None,
    name: str = "bootstrap_unit",
):
    dto = api.create(
        team_id=team_id,
        params=contracts.CreatePipelineInput(
            name=name,
            task_type=task_type,
            config=config if config is not None else {"target": "uploaded_file", "horizon_days": 14},
            training_population={"kind": "hogql", "query": "SELECT 1"},
            inference_population={"kind": "hogql", "query": "SELECT 2"},
            output_property_name="predicted_p_uploaded_file_14d",
        ),
    )
    # Pull the ORM instance so the bootstrap helpers receive the real model object.
    from products.automl.backend.logic import get_pipeline

    pipeline = get_pipeline(team_id=team_id, pipeline_id=dto.id)
    assert pipeline is not None
    return pipeline


def _extract_named_json_block(brief: str, label: str) -> dict:
    """Pull a labeled JSON block out of the brief.

    Each JSON block in the brief is preceded by a header that names it
    (``## Pipeline spec`` / ``## Gates``) so the agent can find them visually.
    The test does the same — grab everything between the heading and the
    matching ```` ```json ```` fence, then parse.
    """
    # Find the heading
    heading = re.compile(rf"^## {re.escape(label)}\b", re.MULTILINE)
    m = heading.search(brief)
    assert m is not None, f"Heading '## {label}' not found in brief"
    # First ```json block after the heading
    fence_start = brief.index("```json\n", m.end()) + len("```json\n")
    fence_end = brief.index("```", fence_start)
    return json.loads(brief[fence_start:fence_end])


@pytest.mark.django_db
def test_build_pipeline_spec_includes_config_and_populations(team):
    pipeline = _make_pipeline(team.id)
    spec = bootstrap._build_pipeline_spec(pipeline)

    # Public-facing fields the agent inside the sandbox needs to operate on.
    assert spec["pipeline_id"] == str(pipeline.id)
    assert spec["team_id"] == team.id
    assert spec["task_type"] == TaskType.CLASSIFICATION.value
    assert spec["config"]["target"] == "uploaded_file"
    assert spec["training_population"]["query"] == "SELECT 1"
    assert spec["inference_population"]["query"] == "SELECT 2"
    assert spec["output_property_name"] == "predicted_p_uploaded_file_14d"


@pytest.mark.django_db
def test_build_pipeline_spec_excludes_server_only_fields(team):
    pipeline = _make_pipeline(team.id)
    spec = bootstrap._build_pipeline_spec(pipeline)

    # Server-managed fields don't belong in the sandbox-visible spec.
    for forbidden in ("created_by_id", "created_at", "updated_at", "status", "runtime"):
        assert forbidden not in spec, f"{forbidden!r} leaked into pipeline spec"


@pytest.mark.django_db
def test_build_orchestration_brief_contains_serializable_pipeline_spec(team):
    pipeline = _make_pipeline(team.id)
    brief = bootstrap._build_orchestration_brief(pipeline)

    assert pipeline.name in brief
    assert pipeline.task_type in brief

    parsed = _extract_named_json_block(brief, "Pipeline spec")
    assert parsed["pipeline_id"] == str(pipeline.id)
    assert parsed["config"]["target"] == "uploaded_file"


@pytest.mark.django_db
def test_build_orchestration_brief_embeds_gates_block(team):
    pipeline = _make_pipeline(team.id)
    brief = bootstrap._build_orchestration_brief(pipeline)

    gates = _extract_named_json_block(brief, "Promotion gates")
    # Default classification gate — sensible permissive floor.
    assert gates == {
        "primary_metric": "accuracy",
        "direction": "higher_is_better",
        "floor": 0.6,
        "source": "task_type_default",
    }


@pytest.mark.django_db
def test_brief_is_a_thin_pointer_to_the_skill(team):
    """The brief no longer carries the full workflow — it points at the skill.

    Workflow content (install commands, MCP tool names, error-handling
    framework) lives in `products/automl/skills/automl-bootstrap/SKILL.md` so
    the agent can iterate via its skill-discovery mechanism rather than
    following a frozen contract embedded in the task description.
    """
    pipeline = _make_pipeline(team.id)
    brief = bootstrap._build_orchestration_brief(pipeline)

    # The skill name is the load-bearing pointer.
    assert "automl-bootstrap" in brief
    # The three per-pipeline data sections are still inlined.
    for required_heading in ("## Pipeline spec", "## Promotion gates", "## Training-population HogQL"):
        assert required_heading in brief, f"missing required section '{required_heading}'"
    # Iteration guidance — the brief tells the agent not to bail at the first non-zero exit.
    assert "Iterate on recoverable errors" in brief or "iterate" in brief.lower()
    # The thin pointer must NOT re-stamp the workflow content that now lives in the skill.
    workflow_anchors_now_in_skill = [
        "uv pip install --system -e",
        "automl --help",
        "automl prepare-from-hogql",
        "automl train",
        "automl-record-training-result",
        "automl-get-active-model",
        "automl-promote-model-version",
    ]
    leaked = [a for a in workflow_anchors_now_in_skill if a in brief]
    assert not leaked, f"workflow anchors leaked back into the brief — they belong in SKILL.md: {leaked}"


@pytest.mark.django_db
def test_brief_inlines_training_query_as_hogql_block(team):
    """The training-population HogQL is substituted inline as a labeled code block."""
    pipeline = _make_pipeline(team.id)
    brief = bootstrap._build_orchestration_brief(pipeline)
    # The query lands in a fenced `hogql` block under the Training-population HogQL heading.
    assert "```hogql\nSELECT 1\n```" in brief


@pytest.mark.django_db
def test_extract_training_query_falls_back_to_empty_for_non_hogql(team):
    """Non-HogQL training populations emit an empty query block — skill's step 2 surfaces the failure."""
    pipeline = _make_pipeline(team.id)
    # Simulate a non-HogQL population shape (cohort id, saved-recipe pointer, etc.).
    pipeline.training_population = {"kind": "cohort", "id": 42}
    extracted = bootstrap._extract_training_query(pipeline)
    assert extracted == ""


def test_skill_folder_exists_with_required_files():
    """The bootstrap skill is the canonical workflow location.

    Sanity-check the folder structure so a refactor that accidentally moves
    or renames the skill is caught here, not at runtime in the sandbox.
    """
    assert _SKILL_ROOT.is_dir(), f"skill folder missing: {_SKILL_ROOT}"
    assert (_SKILL_ROOT / "SKILL.md").is_file(), "SKILL.md missing"
    for ref in ("cli-surface.md", "common-pitfalls.md", "failure-recovery.md"):
        assert (_SKILL_ROOT / "references" / ref).is_file(), f"reference {ref} missing"


def test_skill_md_has_required_frontmatter_and_iteration_guidance():
    """The SKILL.md is what the agent actually consumes — guard the load-bearing pieces."""
    body = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    # YAML frontmatter with name + description (required by the skill build pipeline).
    assert body.startswith("---\n"), "SKILL.md missing YAML frontmatter"
    assert "name: automl-bootstrap" in body
    assert "description:" in body
    # The skill must steer the agent toward iteration on recoverable failures —
    # the whole reason we converted from the frozen brief.
    assert "Iterate, don't bail" in body or "iterate on recoverable" in body.lower()
    # Workflow steps the agent has to walk through must be discoverable.
    for required_anchor in (
        "Verify the CLI is installed",
        "Fetch the training snapshot",
        "Train",
        "Record as challenger",
        "Evaluate the gates",
        "Promote (conditional)",
        "Outcome report",
    ):
        assert required_anchor in body, f"SKILL.md missing required workflow anchor: {required_anchor!r}"


def test_common_pitfalls_reference_covers_known_failure_modes():
    """The pitfalls catalog has to cover the bugs we've actually surfaced —
    otherwise the agent has no chance of recovering from them in the loop."""
    body = (_SKILL_ROOT / "references" / "common-pitfalls.md").read_text(encoding="utf-8")
    # The HogQL precedence bug surfaced by session-16's end-to-end run.
    assert "BETWEEN" in body and "precedence" in body.lower()
    # The target_event vs target distinction surfaced by session-14's smoke test.
    assert "target_event" in body and "config.target" in body


@pytest.mark.django_db
def test_brief_carries_user_success_criteria_over_defaults(team):
    """`success_criteria` on the pipeline config wins over task-type defaults."""
    pipeline = _make_pipeline(
        team.id,
        config={
            "target": "uploaded_file",
            "horizon_days": 14,
            "success_criteria": {
                "primary_metric": "roc_auc",
                "direction": "higher_is_better",
                "floor": 0.75,
            },
        },
    )
    brief = bootstrap._build_orchestration_brief(pipeline)

    gates = _extract_named_json_block(brief, "Promotion gates")
    assert gates == {
        "primary_metric": "roc_auc",
        "direction": "higher_is_better",
        "floor": 0.75,
        "source": "pipeline_config",
    }


@pytest.mark.django_db
def test_default_gates_per_task_type(team):
    """Each task type gets its own permissive default when no success_criteria is set."""
    cases = [
        (
            TaskType.REGRESSION,
            {"target_expression": "sum(amount)", "horizon_days": 30},
            {"primary_metric": "r2", "direction": "higher_is_better", "floor": 0.3, "source": "task_type_default"},
        ),
        (
            TaskType.CLUSTERING,
            {"feature_pool": ["events_7d"], "cluster_count": "auto"},
            {
                "primary_metric": "silhouette",
                "direction": "higher_is_better",
                "floor": 0.2,
                "source": "task_type_default",
            },
        ),
        (
            TaskType.FORECASTING,
            {"series_expression": "count()", "grain": "day", "horizon_steps": 14},
            {
                "primary_metric": "smape",
                "direction": "lower_is_better",
                "ceiling": 0.3,
                "source": "task_type_default",
            },
        ),
    ]
    for task_type, config, expected in cases:
        pipeline = _make_pipeline(team.id, task_type=task_type, config=config, name=f"defaults_{task_type.value}")
        gates = _extract_named_json_block(bootstrap._build_orchestration_brief(pipeline), "Promotion gates")
        assert gates == expected, f"unexpected default gates for {task_type.value}"


@pytest.mark.django_db
def test_enqueue_bootstrap_training_passes_canonical_args(team, user):
    pipeline = _make_pipeline(team.id)
    with patch.object(Task, "create_and_run") as mock_create:
        bootstrap.enqueue_bootstrap_training(pipeline=pipeline, user_id=user.id)

    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    # Origin product is the AutoML-specific enum value we added to Task.OriginProduct.
    assert kwargs["origin_product"] == Task.OriginProduct.AUTOML
    assert kwargs["origin_product"].value == "automl"
    # Background mode for batch training (no live Slack thread).
    assert kwargs["mode"] == "background"
    # Full MCP scopes during stub phase — narrowing is a security-audit follow-up.
    assert kwargs["posthog_mcp_scopes"] == "full"
    # No PR — model artifacts go to object storage, not git.
    assert kwargs["create_pr"] is False
    # Team + user threading.
    assert kwargs["team"].id == team.id
    assert kwargs["user_id"] == user.id
    # Title surfaces the pipeline name so operators can identify the run.
    assert pipeline.name in kwargs["title"]
    # Description is the orchestration brief.
    assert "AutoML bootstrap" in kwargs["description"]
    assert pipeline.task_type in kwargs["description"]
    # Routed onto the dedicated AutoML sandbox image — heavy ML deps preinstalled
    # so the bind-mounted CLI's editable install resolves in seconds, not minutes.
    assert kwargs["sandbox_template"] == SandboxTemplate.AUTOML
