from uuid import uuid4

import pytest
from posthog.test.base import setup_test_organization_team_and_user
from unittest.mock import patch

import dagster

from products.llm_analytics.backend.models import Dataset, DatasetItem

from dags.max_ai.run_evaluation import prepare_dataset


@patch("dags.max_ai.run_evaluation._get_team_id")
@pytest.mark.django_db
def test_prepare_dataset_handles_deleted_field_correctly(mock_get_team_id):
    """Test that prepare_dataset correctly filters datasets and items with deleted=False or deleted=None"""
    _, _, team, user, _ = setup_test_organization_team_and_user(
        "test", str(uuid4()), "test_run_evaluation@test.com", "testpassword12345"
    )
    mock_get_team_id.return_value = team.id

    # Create datasets with different deleted states
    dataset_false = Dataset.objects.create(name="Dataset False", team=team, deleted=False, created_by=user)
    dataset_none = Dataset.objects.create(name="Dataset None", team=team, deleted=None, created_by=user)
    dataset_true = Dataset.objects.create(name="Dataset True", team=team, deleted=True, created_by=user)

    # Create dataset items with different deleted states for each dataset
    input = {"test": "data"}
    output = {"output": "data"}
    metadata = {"team_id": team.id}
    DatasetItem.objects.create(
        dataset=dataset_false, team=team, deleted=False, input=input, output=output, metadata=metadata
    )
    DatasetItem.objects.create(
        dataset=dataset_false, team=team, deleted=None, input=input, output=output, metadata=metadata
    )
    DatasetItem.objects.create(
        dataset=dataset_false, team=team, deleted=True, input=input, output=output, metadata=metadata
    )

    DatasetItem.objects.create(
        dataset=dataset_none, team=team, deleted=False, input=input, output=output, metadata=metadata
    )
    DatasetItem.objects.create(
        dataset=dataset_none, team=team, deleted=None, input=input, output=output, metadata=metadata
    )
    DatasetItem.objects.create(
        dataset=dataset_none, team=team, deleted=True, input=input, output=output, metadata=metadata
    )

    context = dagster.build_op_context(op_config={"dataset_id": str(dataset_false.id)})
    result = prepare_dataset(context)

    # Should find the dataset and only non-deleted items (deleted=False or deleted=None)
    assert result.dataset_id == dataset_false.id
    assert result.dataset_name == "Dataset False"
    assert len(result.dataset_inputs) == 2  # Only deleted=False and deleted=None items

    context = dagster.build_op_context(op_config={"dataset_id": str(dataset_none.id)})
    result = prepare_dataset(context)

    # Should find the dataset and only non-deleted items (deleted=False or deleted=None)
    assert result.dataset_id == dataset_none.id
    assert result.dataset_name == "Dataset None"
    assert len(result.dataset_inputs) == 2  # Only deleted=False and deleted=None items

    context = dagster.build_op_context(op_config={"dataset_id": str(dataset_true.id)})
    with pytest.raises(Dataset.DoesNotExist):
        prepare_dataset(context)
