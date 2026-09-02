from uuid import uuid4

import pytest
from posthog.test.base import setup_test_organization_team_and_user
from unittest.mock import patch

import dagster
from pydantic import ValidationError

from products.ai_observability.backend.dataset_service import (
    archive_dataset,
    archive_dataset_item,
    create_dataset,
    create_dataset_item,
    update_dataset_item,
)
from products.ai_observability.backend.models import Dataset
from products.posthog_ai.dags.run_evaluation import _evaluation_asset_key, prepare_dataset


@patch("products.posthog_ai.dags.run_evaluation._get_team_id")
@pytest.mark.django_db
def test_prepare_dataset_uses_the_current_active_snapshot(mock_get_team_id) -> None:
    _, _, team, user, _ = setup_test_organization_team_and_user(
        "test",
        str(uuid4()),
        "test_run_evaluation@test.com",
        "testpassword12345",
    )
    mock_get_team_id.return_value = team.id
    dataset = create_dataset(team=team, created_by=user, name="Evaluation cases")
    active_item = create_dataset_item(
        team_id=team.id,
        dataset_id=dataset.id,
        created_by=user,
        input={"question": "active input"},
        expected_output={"answer": "active expected"},
        metadata={"team_id": team.id},
    )
    archived_item = create_dataset_item(
        team_id=team.id,
        dataset_id=dataset.id,
        created_by=user,
        input={"archived": True},
        expected_output={"ignored": True},
        metadata={"team_id": team.id},
    )
    archive_dataset_item(
        team_id=team.id,
        dataset_id=dataset.id,
        item_id=archived_item.item.id,
        created_by=user,
        base_version=1,
    )
    Dataset.objects.for_team(team.id).filter(id=dataset.id).update(current_revision=None)

    context = dagster.build_op_context(op_config={"dataset_id": str(dataset.id)})
    result = prepare_dataset(context)

    assert result.dataset_id == dataset.id
    assert result.dataset_name == "Evaluation cases"
    assert result.dataset_revision == 3
    assert len(result.dataset_inputs) == 1
    assert result.dataset_inputs[0].input == {"question": "active input"}
    assert result.dataset_inputs[0].expected == {"answer": "active expected"}
    assert active_item.item.id != archived_item.item.id
    assert _evaluation_asset_key(result).path == [
        "evaluation_dataset",
        str(dataset.id),
        "revision-3",
    ]

    archive_dataset(team_id=team.id, dataset_id=dataset.id)
    with pytest.raises(Dataset.DoesNotExist):
        prepare_dataset(context)


@patch("products.posthog_ai.dags.run_evaluation._get_team_id")
@pytest.mark.django_db
def test_prepare_dataset_resolves_an_exact_revision(mock_get_team_id) -> None:
    _, _, team, user, _ = setup_test_organization_team_and_user(
        "test",
        str(uuid4()),
        "test_run_evaluation_revision@test.com",
        "testpassword12345",
    )
    mock_get_team_id.return_value = team.id
    dataset = create_dataset(team=team, created_by=user, name="Versioned evaluation cases")
    item = create_dataset_item(
        team_id=team.id,
        dataset_id=dataset.id,
        created_by=user,
        input={"question": "revision one"},
        expected_output={"answer": "revision one"},
        metadata={"team_id": team.id},
    )
    update_dataset_item(
        team_id=team.id,
        dataset_id=dataset.id,
        item_id=item.item.id,
        created_by=user,
        base_version=1,
        input={"question": "revision two"},
        expected_output={"answer": "revision two"},
    )

    context = dagster.build_op_context(op_config={"dataset_id": str(dataset.id), "revision": 1})
    result = prepare_dataset(context)

    assert result.dataset_revision == 1
    assert len(result.dataset_inputs) == 1
    assert result.dataset_inputs[0].input == {"question": "revision one"}
    assert result.dataset_inputs[0].expected == {"answer": "revision one"}
    assert _evaluation_asset_key(result).path == [
        "evaluation_dataset",
        str(dataset.id),
        "revision-1",
    ]

    unavailable_revision_context = dagster.build_op_context(op_config={"dataset_id": str(dataset.id), "revision": 3})
    with pytest.raises(ValueError):
        prepare_dataset(unavailable_revision_context)


@patch("products.posthog_ai.dags.run_evaluation._get_team_id")
@pytest.mark.django_db
def test_prepare_dataset_rejects_item_shapes_unsupported_by_the_evaluator(mock_get_team_id) -> None:
    _, _, team, user, _ = setup_test_organization_team_and_user(
        "test",
        str(uuid4()),
        "test_run_evaluation_shape@test.com",
        "testpassword12345",
    )
    mock_get_team_id.return_value = team.id
    dataset = create_dataset(team=team, created_by=user, name="Unsupported evaluation cases")
    create_dataset_item(
        team_id=team.id,
        dataset_id=dataset.id,
        created_by=user,
        input=["unsupported by this evaluator"],
        expected_output="unsupported by this evaluator",
        metadata={"team_id": team.id},
    )

    context = dagster.build_op_context(op_config={"dataset_id": str(dataset.id)})

    with pytest.raises(ValidationError):
        prepare_dataset(context)
