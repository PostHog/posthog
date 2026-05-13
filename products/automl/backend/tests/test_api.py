from uuid import UUID, uuid4

import pytest
from unittest.mock import patch

from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import AutonomyLevel, Cadence, PipelineStatus, TaskType


def _stub_hogql_results(rows: list[int]):
    class _Stub:
        results = [[row] for row in rows]

    return _Stub()


def _create_pipeline(team_id: int, *, name: str = "lifecycle_test") -> contracts.AutoMLPipelineDTO:
    return api.create(
        team_id=team_id,
        params=contracts.CreatePipelineInput(
            name=name,
            task_type=TaskType.CLASSIFICATION,
            config={},
            training_population={},
            inference_population={},
        ),
    )


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
def test_facade_start_and_archive(team, user):
    dto = _create_pipeline(team.id)
    fake_task_id = uuid4()
    with patch("products.automl.backend.facade.api.bootstrap.enqueue_bootstrap_training") as mock_enqueue:
        mock_enqueue.return_value = type("StubTask", (), {"id": fake_task_id})()
        started = api.start(team_id=team.id, pipeline_id=dto.id, user_id=user.id)

    assert started.status is PipelineStatus.BOOTSTRAP_PENDING
    assert started.runtime["bootstrap_task_id"] == str(fake_task_id)

    # Archive from BOOTSTRAP_PENDING is allowed
    archived = api.archive(team_id=team.id, pipeline_id=dto.id)
    assert archived.status is PipelineStatus.ARCHIVED


@pytest.mark.django_db
def test_facade_start_calls_bootstrap_with_pipeline_and_user(team, user):
    dto = _create_pipeline(team.id, name="bootstrap_args_test")
    fake_task_id = uuid4()
    with patch("products.automl.backend.facade.api.bootstrap.enqueue_bootstrap_training") as mock_enqueue:
        mock_enqueue.return_value = type("StubTask", (), {"id": fake_task_id})()
        api.start(team_id=team.id, pipeline_id=dto.id, user_id=user.id)

    mock_enqueue.assert_called_once()
    kwargs = mock_enqueue.call_args.kwargs
    assert kwargs["user_id"] == user.id
    # Pipeline passed in already has BOOTSTRAP_PENDING status applied — the bootstrap
    # call happens after the state transition.
    assert kwargs["pipeline"].id == dto.id
    assert kwargs["pipeline"].status == PipelineStatus.BOOTSTRAP_PENDING.value


@pytest.mark.django_db
def test_facade_start_marks_failed_when_enqueue_raises(team, user):
    dto = _create_pipeline(team.id, name="enqueue_failure_test")
    with patch(
        "products.automl.backend.facade.api.bootstrap.enqueue_bootstrap_training",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            api.start(team_id=team.id, pipeline_id=dto.id, user_id=user.id)

    after = api.get(team_id=team.id, pipeline_id=dto.id)
    assert after is not None
    assert after.status is PipelineStatus.FAILED
    assert after.runtime["bootstrap_error"] == "boom"
    assert "bootstrap_task_id" not in after.runtime


@pytest.mark.django_db
def test_facade_disallowed_transition_raises(team):
    dto = _create_pipeline(team.id, name="bad_transition")
    # DRAFT cannot be paused
    with pytest.raises(api.PipelineStateTransitionError):
        api.pause(team_id=team.id, pipeline_id=dto.id)


@pytest.mark.django_db
def test_facade_validate_returns_report(team):
    """Facade-level validate wires through to logic and returns a ValidationReport."""
    params = contracts.CreatePipelineInput(
        name="validate_facade_test",
        task_type=TaskType.CLASSIFICATION,
        config={"target_event": "uploaded_file", "horizon_days": 14},
        training_population={"kind": "hogql", "query": "SELECT person_id FROM events"},
        inference_population={"kind": "hogql", "query": "SELECT person_id FROM events"},
        output_property_name="automl_p_test",
    )
    # 3 HogQL calls expected: training pop, inference pop, classification positives.
    with patch(
        "products.automl.backend.logic.validation.execute_hogql_query",
        side_effect=[_stub_hogql_results([50_000]), _stub_hogql_results([20_000]), _stub_hogql_results([1_500])],
    ):
        report = api.validate(team_id=team.id, params=params)

    assert isinstance(report, contracts.ValidationReport)
    assert report.ok is True
    assert report.summary.estimated_training_rows == 50_000
    assert report.summary.target_event == "uploaded_file"


@pytest.mark.django_db
def test_facade_dto_carries_runtime(team):
    dto = _create_pipeline(team.id, name="runtime_dto_test")
    # Brand-new pipelines have empty runtime
    assert dto.runtime == {}
    # UUID type round-trips via the DTO
    assert isinstance(dto.id, UUID)
