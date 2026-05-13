from uuid import uuid4

import pytest

from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import AutonomyLevel, Cadence, PipelineStatus, TaskType


@pytest.mark.django_db
def test_facade_create_returns_dto(team):
    params = contracts.CreatePipelineInput(
        name="facade_test",
        task_type=TaskType.REGRESSION,
        config={"target_expression": "sum(properties.value)", "horizon_days": 30},
        training_population={"kind": "hogql", "query": "SELECT 1"},
        inference_population={"kind": "hogql", "query": "SELECT 1"},
    )
    dto = api.create(team_id=team.id, params=params)
    assert isinstance(dto, contracts.AutoMLPipelineDTO)
    assert dto.name == "facade_test"
    assert dto.task_type is TaskType.REGRESSION
    assert dto.status is PipelineStatus.DRAFT
    assert dto.autonomy is AutonomyLevel.CHAMPION_ONLY
    assert dto.inference_cadence is Cadence.DAILY


@pytest.mark.django_db
def test_facade_get_returns_none_for_missing(team):
    assert api.get(team_id=team.id, pipeline_id=uuid4()) is None


@pytest.mark.django_db
def test_facade_start_and_archive(team):
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="lifecycle_test",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={},
            inference_population={},
        ),
    )
    started = api.start(team_id=team.id, pipeline_id=dto.id)
    assert started.status is PipelineStatus.BOOTSTRAP_PENDING

    # Archive from BOOTSTRAP_PENDING is allowed
    archived = api.archive(team_id=team.id, pipeline_id=dto.id)
    assert archived.status is PipelineStatus.ARCHIVED


@pytest.mark.django_db
def test_facade_disallowed_transition_raises(team):
    dto = api.create(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="bad_transition",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={},
            inference_population={},
        ),
    )
    # DRAFT cannot be paused
    with pytest.raises(api.PipelineStateTransitionError):
        api.pause(team_id=team.id, pipeline_id=dto.id)
