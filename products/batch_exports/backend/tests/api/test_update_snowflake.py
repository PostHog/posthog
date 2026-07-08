import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from products.batch_exports.backend.tests.api.operations import (
    create_batch_export_ok,
    get_batch_export_ok,
    patch_batch_export,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


def test_can_patch_snowflake_batch_export_credentials(client: HttpClient, temporal, organization, team, user):
    """Test we can switch Snowflake authentication types while preserving credentials."""
    destination_data = {
        "type": "Snowflake",
        "config": {
            "account": "my-account",
            "user": "user",
            "password": "password123",
            "database": "my-db",
            "warehouse": "COMPUTE_WH",
            "schema": "public",
            "table_name": "my_events",
            "authentication_type": "password",
        },
    }

    batch_export_data = {
        "name": "my-snowflake-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # Test switching to key pair auth type
    new_destination_data = {
        "type": "Snowflake",
        "config": {
            "authentication_type": "keypair",
            "private_key": "SECRET_KEY",
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # Verify the auth type switch worked and other fields were preserved
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Snowflake"
    assert batch_export["destination"]["config"]["account"] == "my-account"
    assert batch_export["destination"]["config"]["authentication_type"] == "keypair"
    assert "private_key" not in batch_export["destination"]["config"]  # Private key should be hidden in response

    # Test switching back to password auth type without providing password (should keep original)
    new_destination_data = {
        "type": "Snowflake",
        "config": {
            "authentication_type": "password",
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_200_OK, response.json()

    # Verify switched back to password auth and kept original password
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Snowflake"
    assert batch_export["destination"]["config"]["account"] == "my-account"
    assert batch_export["destination"]["config"]["authentication_type"] == "password"
    assert "password" not in batch_export["destination"]["config"]  # Password should be hidden in response


def test_switching_snowflake_auth_type_to_keypair_requires_private_key(
    client: HttpClient, temporal, organization, team, user
):
    """Test that switching to keypair authentication requires a private key to be provided."""
    destination_data = {
        "type": "Snowflake",
        "config": {
            "account": "my-account",
            "user": "user",
            "password": "password123",
            "database": "my-db",
            "warehouse": "COMPUTE_WH",
            "schema": "public",
            "table_name": "my_events",
            "authentication_type": "password",
        },
    }

    batch_export_data = {
        "name": "my-snowflake-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    batch_export = create_batch_export_ok(
        client,
        team.pk,
        batch_export_data,
    )

    # Test switching to keypair auth type without providing a private key
    new_destination_data = {
        "type": "Snowflake",
        "config": {
            "authentication_type": "keypair",
        },
    }

    new_batch_export_data = {
        "destination": new_destination_data,
    }

    response = patch_batch_export(client, team.pk, batch_export["id"], new_batch_export_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Private key is required if authentication type is key pair" in response.json()["detail"]

    # Verify the auth type was not changed
    batch_export = get_batch_export_ok(client, team.pk, batch_export["id"])
    assert batch_export["destination"]["type"] == "Snowflake"
    assert batch_export["destination"]["config"]["authentication_type"] == "password"
