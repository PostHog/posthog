import pytest

from django.test.client import Client as HttpClient

from rest_framework import status
from temporalio.client import ScheduleActionStartWorkflow

from posthog.models.integration import Integration

from products.batch_exports.backend.tests.api.conftest import describe_schedule
from products.batch_exports.backend.tests.api.fixtures import create_integration_backed_snowflake_export
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "auth_type,credentials,expected_status",
    [
        # Password auth type tests
        (
            "password",
            {"password": "abc123"},
            status.HTTP_201_CREATED,
        ),
        (
            "password",
            {},
            status.HTTP_400_BAD_REQUEST,
        ),
        # Key pair auth type tests
        (
            "keypair",
            {"private_key": "SECRET_KEY"},
            status.HTTP_201_CREATED,
        ),
        (
            "keypair",
            {},
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
def test_create_snowflake_batch_export_validates_credentials(
    client: HttpClient, auth_type, credentials, expected_status, temporal, organization, team, user
):
    """Test creating a BatchExport with Snowflake destination validates credentials based on auth type."""

    destination_data = {
        "type": "Snowflake",
        "config": {
            "account": "my-account",
            "user": "user",
            "database": "my-db",
            "warehouse": "COMPUTE_WH",
            "schema": "public",
            "table_name": "my_events",
            "authentication_type": auth_type,
            **credentials,
        },
    }

    batch_export_data = {
        "name": "my-production-snowflake-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status

    if expected_status == status.HTTP_400_BAD_REQUEST:
        if auth_type == "password":
            assert "Password is required if authentication type is password" in response.json()["detail"]
        else:
            assert "Private key is required if authentication type is key pair" in response.json()["detail"]


def test_create_snowflake_batch_export_using_integration(client: HttpClient, temporal, organization, team, user):
    """A Snowflake export authenticates via a matching integration, with no account/user/credentials in config."""
    _, data = create_integration_backed_snowflake_export(client, team, user)
    assert data["destination"]["type"] == "Snowflake"
    assert "password" not in data["destination"]["config"]

    schedule = describe_schedule(temporal, data["id"])
    assert isinstance(schedule.schedule.action, ScheduleActionStartWorkflow)
    assert schedule.schedule.action.workflow == "snowflake-export"


def test_create_snowflake_batch_export_rejects_mismatched_integration_kind(
    client: HttpClient, temporal, organization, team, user
):
    """A Snowflake export rejects an integration whose kind isn't snowflake."""
    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AWS_S3,
        integration_id="prod-aws",
        config={"name": "prod-aws", "aws_account_id": "123456789012"},
        sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        created_by=user,
    )
    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        {
            "name": "my-export",
            "interval": "hour",
            "destination": {
                "type": "Snowflake",
                "config": {"database": "my-db", "warehouse": "COMPUTE_WH", "schema": "public"},
                "integration": integration.id,
            },
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Integration is not a Snowflake integration."
