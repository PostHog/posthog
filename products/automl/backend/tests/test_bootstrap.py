"""Tests for the bootstrap bridge — `enqueue_bootstrap_training` and friends."""

import json

import pytest
from unittest.mock import patch

from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import TaskType
from products.automl.backend.training import bootstrap
from products.tasks.backend.models import Task


def _make_pipeline(team_id: int):
    dto = api.create(
        team_id=team_id,
        params=contracts.CreatePipelineInput(
            name="bootstrap_unit",
            task_type=TaskType.CLASSIFICATION,
            config={"target": "uploaded_file", "horizon_days": 14},
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
def test_build_orchestration_brief_contains_serializable_spec(team):
    pipeline = _make_pipeline(team.id)
    brief = bootstrap._build_orchestration_brief(pipeline)

    assert pipeline.name in brief
    assert pipeline.task_type in brief

    # Pull the JSON block out and confirm it's well-formed.
    start = brief.index("```json\n") + len("```json\n")
    end = brief.index("```", start)
    parsed = json.loads(brief[start:end])
    assert parsed["pipeline_id"] == str(pipeline.id)


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
