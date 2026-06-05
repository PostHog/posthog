import pytest

from django.test.client import Client as HttpClient

from rest_framework import status
from temporalio.client import ScheduleActionStartWorkflow

from posthog.models.integration import Integration

from products.batch_exports.backend.tests.api.conftest import describe_schedule
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.fixture
def azure_blob_integration(team, user):
    """Create an Azure Blob integration."""
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AZURE_BLOB,
        integration_id="my-storage-account",
        config={},
        sensitive_config={
            "connection_string": "DefaultEndpointsProtocol=https;AccountName=my-storage-account;AccountKey=my-key;EndpointSuffix=core.windows.net"
        },
        created_by=user,
    )


def test_creating_azure_blob_batch_export_using_integration(
    client: HttpClient, temporal, organization, team, user, azure_blob_integration
):
    """Test that we can create an Azure Blob batch export using an integration."""
    destination_data = {
        "type": "AzureBlob",
        "config": {
            "container_name": "test-container",
            "prefix": "test-prefix/",
        },
        "integration": azure_blob_integration.id,
    }

    batch_export_data = {
        "name": "my-azure-blob-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    data = response.json()
    assert data["destination"]["type"] == "AzureBlob"
    assert data["destination"]["config"]["container_name"] == "test-container"
    assert data["destination"]["config"]["prefix"] == "test-prefix/"
    assert data["interval"] == "hour"

    temporal_schedule = describe_schedule(temporal, data["id"])
    assert temporal_schedule is not None
    assert temporal_schedule.schedule is not None
    assert isinstance(temporal_schedule.schedule.action, ScheduleActionStartWorkflow)
    assert temporal_schedule.schedule.action.workflow == "azure-blob-export"
