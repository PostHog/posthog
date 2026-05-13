"""Tests for the bootstrap bridge — `enqueue_bootstrap_training` and friends."""

import re
import json

import pytest
from unittest.mock import patch

from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import TaskType
from products.automl.backend.training import bootstrap
from products.tasks.backend.models import Task


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

    gates = _extract_named_json_block(brief, "Gates")
    # Default classification gate — sensible permissive floor.
    assert gates == {
        "primary_metric": "accuracy",
        "direction": "higher_is_better",
        "floor": 0.6,
        "source": "task_type_default",
    }


@pytest.mark.django_db
def test_brief_mentions_each_canonical_contract_step(team):
    """The frozen-contract steps are load-bearing — regress us if any goes missing."""
    pipeline = _make_pipeline(team.id)
    brief = bootstrap._build_orchestration_brief(pipeline)

    # The agent has to (a) fetch via execute-sql, (b) train, (c) record, (d) gate, (e) promote.
    expected_anchors = [
        "execute-sql",
        "products.automl.backend.training.trainer",
        "record_training_result",
        "get_active_model",
        "promote_to_champion",
        "BOOTSTRAP_ERROR:",
    ]
    missing = [a for a in expected_anchors if a not in brief]
    assert not missing, f"brief is missing canonical contract anchors: {missing}"


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

    gates = _extract_named_json_block(brief, "Gates")
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
        gates = _extract_named_json_block(bootstrap._build_orchestration_brief(pipeline), "Gates")
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
