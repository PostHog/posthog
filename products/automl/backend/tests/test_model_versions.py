"""Tests for the AutoMLModelVersion landing — record, list, get-active, promote."""

import uuid

import pytest

from django.db import IntegrityError

from products.automl.backend import logic
from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import ModelRole, TaskType
from products.automl.backend.models import AutoMLModelVersion


def _make_pipeline(team_id: int, name: str = "model_versions_unit"):
    """Create a pipeline via the facade and return its ORM instance."""
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
    pipeline = logic.get_pipeline(team_id=team_id, pipeline_id=dto.id)
    assert pipeline is not None
    return pipeline


def _record_input(**overrides) -> contracts.RecordTrainingResultInput:
    """Build a RecordTrainingResultInput with sensible defaults — overrides win."""
    defaults: dict = {
        "metrics": {"roc_auc": 0.85, "log_loss": 0.42},
        "leaderboard": [{"model": "WeightedEnsemble_L2", "score_val": 0.86}],
    }
    defaults.update(overrides)
    return contracts.RecordTrainingResultInput(**defaults)


@pytest.mark.django_db
def test_record_persists_all_fields(team):
    pipeline = _make_pipeline(team.id)
    training_task_id = uuid.uuid4()
    dto = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(
            training_params={"seed": 42, "presets": "medium_quality", "time_limit_s": 60},
            tracking_metadata={"note": "first run"},
            eval_metric="roc_auc",
            problem_type="binary",
            artifact_uri="s3://posthog-automl/models/abc",
            features_hash="sha256:deadbeef",
            rows_train=4200,
            rows_val=750,
            rows_test=750,
            training_task_id=training_task_id,
        ),
    )

    assert dto.pipeline_id == pipeline.id
    assert dto.team_id == team.id
    assert dto.role == ModelRole.CHALLENGER
    assert dto.metrics == {"roc_auc": 0.85, "log_loss": 0.42}
    assert dto.leaderboard[0]["model"] == "WeightedEnsemble_L2"
    assert dto.training_params["presets"] == "medium_quality"
    assert dto.tracking_metadata == {"note": "first run"}
    assert dto.eval_metric == "roc_auc"
    assert dto.problem_type == "binary"
    assert dto.artifact_uri == "s3://posthog-automl/models/abc"
    assert dto.features_hash == "sha256:deadbeef"
    assert dto.rows_train == 4200
    assert dto.rows_val == 750
    assert dto.rows_test == 750
    assert dto.training_task_id == training_task_id


@pytest.mark.django_db
def test_record_defaults_to_challenger(team):
    pipeline = _make_pipeline(team.id)
    dto = api.record_training_result(team_id=team.id, pipeline_id=pipeline.id, params=_record_input())
    assert dto.role == ModelRole.CHALLENGER


@pytest.mark.django_db
def test_record_accepts_explicit_role(team):
    pipeline = _make_pipeline(team.id)
    dto = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHAMPION),
    )
    assert dto.role == ModelRole.CHAMPION


@pytest.mark.django_db
def test_record_raises_for_missing_pipeline(team):
    with pytest.raises(contracts.PipelineNotFoundError):
        api.record_training_result(
            team_id=team.id,
            pipeline_id=uuid.uuid4(),
            params=_record_input(),
        )


@pytest.mark.django_db
def test_record_is_team_scoped(team):
    """A pipeline belongs to one team — a different team can't write versions to it."""
    pipeline = _make_pipeline(team.id)
    other_team_id = team.id + 9_999_999
    with pytest.raises(contracts.PipelineNotFoundError):
        api.record_training_result(
            team_id=other_team_id,
            pipeline_id=pipeline.id,
            params=_record_input(),
        )


@pytest.mark.django_db
def test_list_returns_newest_first_and_includes_archived(team):
    pipeline = _make_pipeline(team.id)
    v1 = api.record_training_result(team_id=team.id, pipeline_id=pipeline.id, params=_record_input())
    v2 = api.record_training_result(team_id=team.id, pipeline_id=pipeline.id, params=_record_input())
    # Archive the first one directly via ORM so we don't depend on promotion ordering.
    obj = AutoMLModelVersion.all_teams.get(id=v1.id)
    obj.role = ModelRole.ARCHIVED.value
    obj.save(update_fields=["role"])

    listed = api.list_model_versions(team_id=team.id, pipeline_id=pipeline.id)
    assert [v.id for v in listed] == [v2.id, v1.id]
    # Archived rows are part of the audit trail.
    assert any(v.role == ModelRole.ARCHIVED for v in listed)


@pytest.mark.django_db
def test_get_active_model_returns_none_when_no_version(team):
    pipeline = _make_pipeline(team.id)
    assert api.get_active_model(team_id=team.id, pipeline_id=pipeline.id, role=ModelRole.CHAMPION) is None
    assert api.get_active_model(team_id=team.id, pipeline_id=pipeline.id, role=ModelRole.CHALLENGER) is None


@pytest.mark.django_db
def test_get_active_model_returns_role_holder(team):
    pipeline = _make_pipeline(team.id)
    api.record_training_result(team_id=team.id, pipeline_id=pipeline.id, params=_record_input(role=ModelRole.CHAMPION))
    challenger_dto = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHALLENGER),
    )

    got_challenger = api.get_active_model(team_id=team.id, pipeline_id=pipeline.id, role=ModelRole.CHALLENGER)
    assert got_challenger is not None
    assert got_challenger.id == challenger_dto.id


@pytest.mark.django_db
def test_promote_challenger_with_no_prior_champion(team):
    pipeline = _make_pipeline(team.id)
    challenger = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHALLENGER),
    )

    promoted = api.promote_to_champion(team_id=team.id, model_version_id=challenger.id)
    assert promoted.id == challenger.id
    assert promoted.role == ModelRole.CHAMPION


@pytest.mark.django_db
def test_promote_archives_existing_champion_atomically(team):
    pipeline = _make_pipeline(team.id)
    old_champ = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHAMPION),
    )
    challenger = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHALLENGER),
    )

    promoted = api.promote_to_champion(team_id=team.id, model_version_id=challenger.id)
    assert promoted.id == challenger.id
    assert promoted.role == ModelRole.CHAMPION

    # The old champion is archived in the same transaction.
    old_after = AutoMLModelVersion.all_teams.get(id=old_champ.id)
    assert old_after.role == ModelRole.ARCHIVED.value

    # The pipeline still has exactly one champion.
    champion_ids = list(
        AutoMLModelVersion.all_teams.filter(pipeline_id=pipeline.id, role=ModelRole.CHAMPION.value).values_list(
            "id", flat=True
        )
    )
    assert champion_ids == [challenger.id]


@pytest.mark.django_db
def test_promote_is_idempotent(team):
    pipeline = _make_pipeline(team.id)
    champ = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHAMPION),
    )

    again = api.promote_to_champion(team_id=team.id, model_version_id=champ.id)
    assert again.id == champ.id
    assert again.role == ModelRole.CHAMPION


@pytest.mark.django_db
def test_promote_works_from_archived_state(team):
    pipeline = _make_pipeline(team.id)
    v = api.record_training_result(team_id=team.id, pipeline_id=pipeline.id, params=_record_input())
    obj = AutoMLModelVersion.all_teams.get(id=v.id)
    obj.role = ModelRole.ARCHIVED.value
    obj.save(update_fields=["role"])

    promoted = api.promote_to_champion(team_id=team.id, model_version_id=v.id)
    assert promoted.role == ModelRole.CHAMPION


@pytest.mark.django_db
def test_promote_raises_for_missing_version(team):
    with pytest.raises(contracts.ModelVersionNotFoundError):
        api.promote_to_champion(team_id=team.id, model_version_id=uuid.uuid4())


@pytest.mark.django_db
def test_promote_is_team_scoped(team):
    pipeline = _make_pipeline(team.id)
    challenger = api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHALLENGER),
    )
    other_team_id = team.id + 9_999_999
    with pytest.raises(contracts.ModelVersionNotFoundError):
        api.promote_to_champion(team_id=other_team_id, model_version_id=challenger.id)


@pytest.mark.django_db
def test_partial_unique_constraint_blocks_second_champion(team):
    """Two champions on the same pipeline are a DB-level error, not just app-level."""
    pipeline = _make_pipeline(team.id)
    api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHAMPION),
    )
    with pytest.raises(IntegrityError):
        # Bypass the facade so the constraint is the only thing in our way.
        AutoMLModelVersion.all_teams.create(
            team_id=team.id,
            pipeline_id=pipeline.id,
            role=ModelRole.CHAMPION.value,
            metrics={},
            leaderboard=[],
        )


@pytest.mark.django_db
def test_partial_unique_constraint_blocks_second_challenger(team):
    pipeline = _make_pipeline(team.id)
    api.record_training_result(
        team_id=team.id,
        pipeline_id=pipeline.id,
        params=_record_input(role=ModelRole.CHALLENGER),
    )
    with pytest.raises(IntegrityError):
        AutoMLModelVersion.all_teams.create(
            team_id=team.id,
            pipeline_id=pipeline.id,
            role=ModelRole.CHALLENGER.value,
            metrics={},
            leaderboard=[],
        )


@pytest.mark.django_db
def test_partial_unique_constraint_allows_multiple_archived(team):
    """Archived rows stack — they're the audit trail."""
    pipeline = _make_pipeline(team.id)
    for _ in range(3):
        AutoMLModelVersion.all_teams.create(
            team_id=team.id,
            pipeline_id=pipeline.id,
            role=ModelRole.ARCHIVED.value,
            metrics={},
            leaderboard=[],
        )
    archived = AutoMLModelVersion.all_teams.filter(pipeline_id=pipeline.id, role=ModelRole.ARCHIVED.value)
    assert archived.count() == 3
