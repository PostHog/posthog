from uuid import uuid4

import pytest

from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import AutonomyLevel, Cadence, PipelineStatus, TaskType


@pytest.mark.django_db
def test_facade_create_returns_dto(team):
    params = contracts.CreatePipelineInput(
        team_id=team.id,
        name="facade_test",
        task_type=TaskType.REGRESSION,
        config={"target_expression": "sum(properties.value)", "horizon_days": 30},
        training_population={"kind": "hogql", "query": "SELECT 1"},
        inference_population={"kind": "hogql", "query": "SELECT 1"},
    )
    dto = api.create(params)
    assert isinstance(dto, contracts.AutoMLPipelineDTO)
    assert dto.name == "facade_test"
    assert dto.task_type is TaskType.REGRESSION
    assert dto.status is PipelineStatus.DRAFT
    assert dto.autonomy is AutonomyLevel.CHAMPION_ONLY
    assert dto.inference_cadence is Cadence.DAILY


@pytest.mark.django_db
def test_facade_get_returns_none_for_missing(team):
    assert api.get(team_id=team.id, pipeline_id=uuid4()) is None
