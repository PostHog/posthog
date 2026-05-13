import pytest

from products.automl.backend import logic
from products.automl.backend.facade import contracts
from products.automl.backend.facade.enums import PipelineStatus, TaskType


@pytest.mark.django_db
def test_create_pipeline_persists(team):
    params = contracts.CreatePipelineInput(
        name="user_event_prediction_demo",
        task_type=TaskType.CLASSIFICATION,
        config={"target_event": "uploaded_file", "horizon_days": 14, "framing": "adoption"},
        training_population={"kind": "hogql", "query": "SELECT person_id FROM events WHERE 1=1"},
        inference_population={"kind": "hogql", "query": "SELECT person_id FROM events WHERE 1=1"},
        description="Predict who'll upload their first file in the next 14 days.",
    )
    obj = logic.create_pipeline(team_id=team.id, params=params)
    assert obj.name == "user_event_prediction_demo"
    assert obj.task_type == TaskType.CLASSIFICATION.value
    assert obj.config["target_event"] == "uploaded_file"
    assert obj.status == PipelineStatus.DRAFT.value


@pytest.mark.django_db
def test_list_pipelines_excludes_archived(team):
    active = logic.create_pipeline(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="active_pipeline",
            task_type=TaskType.CLUSTERING,
            config={},
            training_population={},
            inference_population={},
        ),
    )
    archived = logic.create_pipeline(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="archived_pipeline",
            task_type=TaskType.CLUSTERING,
            config={},
            training_population={},
            inference_population={},
        ),
    )
    archived.status = PipelineStatus.ARCHIVED.value
    archived.save()

    listed = logic.list_pipelines(team_id=team.id)
    listed_ids = {p.id for p in listed}
    assert active.id in listed_ids
    assert archived.id not in listed_ids


@pytest.mark.django_db
def test_update_pipeline_partial(team):
    pipeline = logic.create_pipeline(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="to_update",
            task_type=TaskType.REGRESSION,
            config={},
            training_population={},
            inference_population={},
        ),
    )
    updated = logic.update_pipeline(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=contracts.UpdatePipelineInput(description="new description"),
    )
    assert updated is not None
    assert updated.description == "new description"
    assert updated.name == "to_update"  # unchanged


@pytest.mark.django_db
def test_transition_pipeline_disallowed(team):
    pipeline = logic.create_pipeline(
        team_id=team.id,
        params=contracts.CreatePipelineInput(
            name="state_machine",
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={},
            inference_population={},
        ),
    )
    # DRAFT -> ACTIVE is not allowed
    with pytest.raises(contracts.PipelineStateTransitionError):
        logic.transition_pipeline(
            team_id=team.id,
            pipeline_id=pipeline.id,
            new_status=PipelineStatus.ACTIVE,
        )
    # DRAFT -> BOOTSTRAP_PENDING is allowed
    moved = logic.transition_pipeline(
        team_id=team.id,
        pipeline_id=pipeline.id,
        new_status=PipelineStatus.BOOTSTRAP_PENDING,
    )
    assert moved.status == PipelineStatus.BOOTSTRAP_PENDING.value
