import json
from typing import Any

import pytest

from django.test import override_settings
from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models import Team, User
from posthog.security.url_validation import INVALID_HOST_MESSAGE, UNREACHABLE_HOST_MESSAGE

from products.batch_exports.backend.tests.api.fixtures import create_organization, create_team, create_user
from products.batch_exports.backend.tests.api.operations import create_batch_export, get_batch_export_ok

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.mark.parametrize(
    "mode,copy_inputs,expected_status",
    [
        (
            "INSERT",
            {},
            status.HTTP_201_CREATED,
        ),
        (
            "INSERT",
            None,
            status.HTTP_201_CREATED,
        ),
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": "integration",
                "authorization": "default",
            },
            status.HTTP_201_CREATED,
        ),
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": "integration",
                "authorization": "integration",
            },
            status.HTTP_201_CREATED,
        ),
        # Missing required 's3_bucket'
        (
            "COPY",
            {
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": "integration",
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Missing required 'region_name'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": "integration",
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'bucket_credentials'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Empty 'authorization' as IAMRole
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": "integration",
                "authorization": "",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
def test_create_redshift_batch_export_validates_copy_inputs(
    client: HttpClient,
    mode: str,
    copy_inputs: dict[str, Any] | None,
    expected_status: int,
    team: Team,
    user: User,
    aws_redshift_integration: IntegrationRecord,
    aws_s3_integration: IntegrationRecord,
) -> None:
    if copy_inputs:
        copy_inputs = {
            key: aws_s3_integration.id if value == "integration" else value for key, value in copy_inputs.items()
        }

    destination_data: dict[str, Any] = {
        "type": "Redshift",
        "config": {
            "database": "my-db",
            "host": "localhost",
            "schema": "public",
            "table_name": "my_events",
            "mode": mode,
            "copy_inputs": copy_inputs,
        },
        "integration": aws_redshift_integration.id,
    }

    batch_export_data = {
        "name": "my-production-redshiftn-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == expected_status, response.json()

    if expected_status == status.HTTP_400_BAD_REQUEST:
        assert "Missing required" in response.json()["detail"]


@pytest.mark.parametrize(
    "authorization", [["arn:aws:iam::123456789012:role/my-role"], {}, True, 1.5, "not-an-arn", "my-role"]
)
def test_create_redshift_batch_export_rejects_invalid_authorization_type(
    client: HttpClient,
    authorization: object,
    team: Team,
    user: User,
    aws_redshift_integration: IntegrationRecord,
    aws_s3_integration: IntegrationRecord,
) -> None:
    destination_data: dict[str, Any] = {
        "type": "Redshift",
        "config": {
            "database": "my-db",
            "host": "localhost",
            "mode": "COPY",
            "copy_inputs": {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": aws_s3_integration.id,
                "authorization": authorization,
            },
        },
        "integration": aws_redshift_integration.id,
    }

    batch_export_data = {
        "name": "my-production-redshift-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "Authorization for 'COPY'" in response.json()["detail"]


@pytest.mark.parametrize(
    "host, expected_message",
    [
        # A blocked name and a name that does not resolve report the same thing, so the error
        # cannot be used to find which addresses exist inside our network.
        ("192.168.1.1", UNREACHABLE_HOST_MESSAGE),
        ("127.0.0.1", UNREACHABLE_HOST_MESSAGE),
        ("10.0.0.1", UNREACHABLE_HOST_MESSAGE),
        ("169.254.0.0", UNREACHABLE_HOST_MESSAGE),
        ("localhost", UNREACHABLE_HOST_MESSAGE),
        # These two are settled by form before any lookup, so they say what to fix. A bare
        # IPv6 literal is a host, but the brackets a URL wraps it in are not.
        ("[::1]", INVALID_HOST_MESSAGE),
        ("postgres://alice:hunter2@db.example.com/app", INVALID_HOST_MESSAGE),
    ],
)
def test_create_redshift_batch_export_fails_with_invalid_host(
    client: HttpClient, temporal, organization, team, user, host, expected_message, aws_redshift_integration
):
    """Test creating a BatchExport with a Redshift destination rejects an internal host.

    Postgres host validation is covered separately in test_create_postgres.py, where the host
    comes from the linked Integration rather than from inline config.
    """

    destination_data: dict[str, Any] = {
        "type": "Redshift",
        "config": {
            "database": "my-db",
            "host": host,
            "schema": "public",
            "table_name": "my_events",
        },
        "integration": aws_redshift_integration.id,
    }

    batch_export_data = {
        "name": "my-production-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)

    with override_settings(TEST=0, DEBUG=0):
        response = create_batch_export(
            client,
            team.pk,
            batch_export_data,
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == expected_message
    assert host not in response.content.decode()
    assert "hunter2" not in response.content.decode()


def test_create_redshift_batch_export_with_aws_integration(
    client: HttpClient, temporal, organization, team, user, aws_redshift_integration
):
    batch_export_data = {
        "name": "my-integration-backed-redshift-destination",
        "interval": "hour",
        "destination": {
            "type": "Redshift",
            # No user/password inline: credentials come from the integration. Only the
            # cluster endpoint stays in the config.
            "config": {"database": "my-db", "host": "8.8.8.8"},
            "integration": aws_redshift_integration.id,
        },
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_201_CREATED, response.json()


def test_create_redshift_batch_export_with_plain_integration(client: HttpClient, temporal, organization, team, user):
    integration = IntegrationManager.aws_redshift.credentials.create(
        team_id=team.id,
        external_id="prod-redshift-plain",
        config={"host": "8.8.8.8", "port": 5439, "user": "posthog", "ssl_mode": "require"},
        sensitive_config={"password": "very-secret"},
        created_by_id=user.id,
    )

    batch_export_data = {
        "name": "my-integration-backed-redshift-destination",
        "interval": "hour",
        "destination": {
            "type": "Redshift",
            # Plain Redshift integrations store the host themselves, so none is needed here.
            "config": {"database": "my-db"},
            "integration": integration.id,
        },
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_201_CREATED, response.json()


@pytest.mark.parametrize(
    "failure,expected_error",
    [
        ("wrong_kind", "not a Redshift integration"),
        ("aws_integration_without_host", "host"),
        ("no_integration", "Integration is required for Redshift batch exports"),
    ],
)
def test_create_redshift_batch_export_validates_integration(
    client: HttpClient,
    failure,
    expected_error,
    temporal,
    organization,
    team,
    user,
    aws_s3_integration,
    aws_redshift_integration,
):
    config: dict = {"database": "my-db"}
    integration_pk = None

    if failure == "wrong_kind":
        integration_pk = aws_s3_integration.id
    elif failure == "aws_integration_without_host":
        integration_pk = aws_redshift_integration.id

    destination_data: dict = {"type": "Redshift", "config": config}
    if integration_pk is not None:
        destination_data["integration"] = integration_pk

    batch_export_data = {
        "name": "my-integration-backed-redshift-destination",
        "interval": "hour",
        "destination": destination_data,
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert expected_error in response.json()["detail"]


@pytest.mark.parametrize(
    "copy_credential_source",
    [
        "own_integration",
        "iam_role",
        "inline_bucket_credentials",
        "inline_authorization",
        "other_team_integration",
        "wrong_kind_integration",
        "nonexistent_integration",
    ],
)
def test_create_redshift_batch_export_validates_copy_integration_ids(
    client: HttpClient,
    copy_credential_source: str,
    team: Team,
    user: User,
    aws_s3_integration: IntegrationRecord,
    aws_redshift_integration: IntegrationRecord,
) -> None:
    # These ids live inside `config` rather than the team-scoped `integration` field, so
    # tenant scoping is enforced by validation: a foreign or wrong-kind id must 400, not 500.
    expected_status: int
    if copy_credential_source in {"own_integration", "iam_role"}:
        integration_id = aws_s3_integration.id
        expected_status = status.HTTP_201_CREATED
    elif copy_credential_source.startswith("inline_"):
        integration_id = aws_s3_integration.id
        expected_status = status.HTTP_400_BAD_REQUEST
    elif copy_credential_source == "other_team_integration":
        other_organization = create_organization("Other Org")
        other_team = create_team(other_organization)
        other_user = create_user("other@example.com", "Other User", other_organization)
        other_integration = IntegrationManager.aws_s3.credentials.create(
            team_id=other_team.id,
            external_id="other-test-aws",
            config={"name": "other-test-aws"},
            sensitive_config={"aws_access_key_id": "test-key", "aws_secret_access_key": "test-secret"},
            created_by_id=other_user.id,
        )
        integration_id = other_integration.id
        expected_status = status.HTTP_400_BAD_REQUEST
    elif copy_credential_source == "wrong_kind_integration":
        integration_id = aws_redshift_integration.id
        expected_status = status.HTTP_400_BAD_REQUEST
    else:
        integration_id = 999999
        expected_status = status.HTTP_400_BAD_REQUEST

    copy_inputs: dict[str, Any] = {
        "s3_bucket": "my-production-s3-bucket",
        "region_name": "us-east-1",
        "s3_key_prefix": "posthog-events/",
        "bucket_credentials": integration_id,
        "authorization": integration_id,
    }
    destination_data: dict[str, Any] = {
        "type": "Redshift",
        "config": {
            "database": "my-db",
            "host": "localhost",
            "mode": "COPY",
            "copy_inputs": copy_inputs,
        },
        "integration": aws_redshift_integration.id,
    }

    if copy_credential_source == "iam_role":
        copy_inputs["authorization"] = "arn:aws:iam::000000000000:role/test-copy"
    elif copy_credential_source.startswith("inline_"):
        copy_inputs[copy_credential_source.removeprefix("inline_")] = {
            "aws_access_key_id": "test-access-key",
            "aws_secret_access_key": "test-secret-key",
        }

    batch_export_data = {
        "name": "my-production-redshift-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == expected_status, response.json()

    if copy_credential_source.startswith("inline_"):
        assert "must be an AWS S3 integration" in response.json()["detail"]
        assert "Inline AWS access keys are no longer accepted" in response.json()["detail"]
        assert "test-access-key" not in response.json()["detail"]
        assert "test-secret-key" not in response.json()["detail"]
    elif expected_status == status.HTTP_400_BAD_REQUEST:
        assert "does not reference an AWS S3 integration" in response.json()["detail"]
    else:
        # EncryptedJSONField stringifies the stored ids; responses must restore them to ints
        # to honor the generated types.
        batch_export = get_batch_export_ok(client, team.pk, response.json()["id"])
        assert batch_export["destination"]["config"]["copy_inputs"]["bucket_credentials"] == integration_id
        assert (
            batch_export["destination"]["config"]["copy_inputs"]["authorization"]
            == destination_data["config"]["copy_inputs"]["authorization"]
        )


@pytest.mark.parametrize("field_name", ["bucket_credentials", "authorization"])
@pytest.mark.parametrize(
    "credentials",
    [
        {"aws_access_key_id": "test-access-key", "aws_secret_access_key": "test-secret-key"},
        {"aws_access_key_id": "test-access-key"},
    ],
    ids=["full_pair", "partial"],
)
def test_create_redshift_batch_export_rejects_inline_copy_keys_in_insert_mode(
    client: HttpClient,
    field_name: str,
    credentials: dict[str, str],
    team: Team,
    user: User,
    aws_s3_integration: IntegrationRecord,
    aws_redshift_integration: IntegrationRecord,
) -> None:
    copy_inputs: dict[str, Any] = {
        "s3_bucket": "my-production-s3-bucket",
        "region_name": "us-east-1",
        "s3_key_prefix": "posthog-events/",
        "bucket_credentials": aws_s3_integration.id,
        "authorization": aws_s3_integration.id,
    }
    copy_inputs[field_name] = credentials
    batch_export_data = {
        "name": "my-production-redshift-destination",
        "destination": {
            "type": "Redshift",
            "config": {"database": "my-db", "host": "localhost", "mode": "INSERT", "copy_inputs": copy_inputs},
            "integration": aws_redshift_integration.id,
        },
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "Inline AWS access keys are no longer accepted" in response.json()["detail"]


@pytest.mark.parametrize("mode", ["INSERT", "COPY"])
def test_create_redshift_batch_export_rejects_json_string_copy_inputs(
    client: HttpClient,
    mode: str,
    team: Team,
    user: User,
    aws_redshift_integration: IntegrationRecord,
) -> None:
    copy_inputs = json.dumps(
        {
            "s3_bucket": "my-production-s3-bucket",
            "region_name": "us-east-1",
            "bucket_credentials": {"aws_access_key_id": "test-access-key", "aws_secret_access_key": "test-secret-key"},
            "authorization": "default",
        }
    )
    batch_export_data = {
        "name": "my-production-redshift-destination",
        "destination": {
            "type": "Redshift",
            "config": {"database": "my-db", "host": "localhost", "mode": mode, "copy_inputs": copy_inputs},
            "integration": aws_redshift_integration.id,
        },
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert "'copy_inputs' must be an object." in response.json()["detail"]
    assert "test-secret-key" not in response.json()["detail"]
