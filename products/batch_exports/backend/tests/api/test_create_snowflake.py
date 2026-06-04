import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

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
