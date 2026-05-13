import pytest

from products.automl.backend.facade.enums import AutonomyLevel, Cadence, PipelineStatus, TaskType
from products.automl.backend.models import AutoMLPipeline


@pytest.mark.django_db
def test_create_pipeline_defaults(team):
    pipeline = AutoMLPipeline.objects.create(
        team_id=team.id,
        name="insight_created_14d_adoption",
        task_type=TaskType.CLASSIFICATION.value,
        config={"target_event": "insight created", "horizon_days": 14},
    )
    assert pipeline.id is not None
    assert pipeline.status == PipelineStatus.DRAFT.value
    assert pipeline.autonomy == AutonomyLevel.CHAMPION_ONLY.value
    assert pipeline.inference_cadence == Cadence.DAILY.value
    assert pipeline.retraining_cadence == Cadence.DAILY.value


@pytest.mark.django_db
def test_pipeline_str(team):
    pipeline = AutoMLPipeline.objects.create(
        team_id=team.id,
        name="test_pipeline",
        task_type=TaskType.FORECASTING.value,
        config={},
    )
    assert "test_pipeline" in str(pipeline)
    assert "forecasting" in str(pipeline)


@pytest.mark.django_db
def test_unique_name_per_team(team):
    AutoMLPipeline.objects.create(
        team_id=team.id,
        name="dup",
        task_type=TaskType.CLASSIFICATION.value,
        config={},
    )
    with pytest.raises(Exception):
        AutoMLPipeline.objects.create(
            team_id=team.id,
            name="dup",
            task_type=TaskType.CLASSIFICATION.value,
            config={},
        )
