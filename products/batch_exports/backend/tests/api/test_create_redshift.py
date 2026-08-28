import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.models.integration import Integration

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
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
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
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
            },
            status.HTTP_201_CREATED,
        ),
        # Missing required 's3_bucket'
        (
            "COPY",
            {
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
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
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "default",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
        # Missing required 'aws_secret_access_key' in 'bucket_credentials
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123"},
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
        # Empty 'authorization'
        (
            "COPY",
            {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": {},
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
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": "",
            },
            status.HTTP_400_BAD_REQUEST,
        ),
    ],
)
def test_create_redshift_batch_export_validates_copy_inputs(
    client: HttpClient, mode, copy_inputs, expected_status, temporal, organization, team, user
):
    """Test creating a BatchExport with Redshift destination validates inputs for 'COPY'."""

    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "localhost",
            "schema": "public",
            "table_name": "my_events",
            "mode": mode,
            "copy_inputs": copy_inputs,
        },
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


@pytest.mark.parametrize("authorization", [["arn:aws:iam::123456789012:role/my-role"], True, 1.5])
def test_create_redshift_batch_export_rejects_invalid_authorization_type(
    client: HttpClient, authorization, temporal, organization, team, user
):
    """Test 'authorization' values that are neither credentials, a role, nor an id are a 400.

    These used to pass validation and crash with a TypeError when the export synced.
    """
    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "localhost",
            "mode": "COPY",
            "copy_inputs": {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": {"aws_access_key_id": "abc123", "aws_secret_access_key": "secret"},
                "authorization": authorization,
            },
        },
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


def create_aws_redshift_role_integration(team, user) -> Integration:
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AWS_REDSHIFT,
        integration_id="prod-redshift-role",
        config={
            "name": "prod-redshift-role",
            "aws_role_arn": "arn:aws:iam::123456789012:role/posthog-batch-exports",
            "user": "awsuser",
        },
        created_by=user,
    )


def test_create_redshift_batch_export_with_aws_integration(client: HttpClient, temporal, organization, team, user):
    integration = create_aws_redshift_role_integration(team, user)

    batch_export_data = {
        "name": "my-integration-backed-redshift-destination",
        "interval": "hour",
        "destination": {
            "type": "Redshift",
            # No user/password inline: credentials come from the integration. Only the
            # cluster endpoint stays in the config.
            "config": {"database": "my-db", "host": "8.8.8.8"},
            "integration": integration.pk,
        },
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == status.HTTP_201_CREATED, response.json()


def test_create_redshift_batch_export_with_plain_integration(client: HttpClient, temporal, organization, team, user):
    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.AWS_REDSHIFT,
        integration_id="prod-redshift-plain",
        config={"host": "8.8.8.8", "port": 5439, "user": "posthog", "ssl_mode": "require"},
        sensitive_config={"password": "very-secret"},
        created_by=user,
    )

    batch_export_data = {
        "name": "my-integration-backed-redshift-destination",
        "interval": "hour",
        "destination": {
            "type": "Redshift",
            # Plain Redshift integrations store the host themselves, so none is needed here.
            "config": {"database": "my-db"},
            "integration": integration.pk,
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
        ("no_integration_no_credentials", "missing required field"),
    ],
)
def test_create_redshift_batch_export_validates_integration(
    client: HttpClient, failure, expected_error, temporal, organization, team, user, aws_s3_integration
):
    config: dict = {"database": "my-db"}
    integration_pk = None

    if failure == "wrong_kind":
        integration_pk = aws_s3_integration.pk
    elif failure == "aws_integration_without_host":
        integration_pk = create_aws_redshift_role_integration(team, user).pk

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
    ["own_integration", "other_team_integration", "wrong_kind_integration", "nonexistent_integration"],
)
def test_create_redshift_batch_export_validates_copy_integration_ids(
    client: HttpClient, copy_credential_source, temporal, organization, team, user, aws_s3_integration
):
    # These ids live inside `config` rather than the team-scoped `integration` field, so
    # tenant scoping is enforced by validation: a foreign or wrong-kind id must 400, not 500.
    expected_status: int
    if copy_credential_source == "own_integration":
        integration_id = aws_s3_integration.pk
        expected_status = status.HTTP_201_CREATED
    elif copy_credential_source == "other_team_integration":
        other_organization = create_organization("Other Org")
        other_team = create_team(other_organization)
        other_user = create_user("other@user.com", "Other User", other_organization)
        other_integration = Integration.objects.create(
            team=other_team,
            kind=Integration.IntegrationKind.AWS_S3,
            integration_id="other-prod-aws",
            config={"name": "other-prod-aws", "aws_account_id": "999999999999"},
            sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
            created_by=other_user,
        )
        integration_id = other_integration.pk
        expected_status = status.HTTP_400_BAD_REQUEST
    elif copy_credential_source == "wrong_kind_integration":
        integration_id = create_aws_redshift_role_integration(team, user).pk
        expected_status = status.HTTP_400_BAD_REQUEST
    else:
        integration_id = 999999
        expected_status = status.HTTP_400_BAD_REQUEST

    destination_data = {
        "type": "Redshift",
        "config": {
            "user": "user",
            "password": "my-password",
            "database": "my-db",
            "host": "localhost",
            "mode": "COPY",
            "copy_inputs": {
                "s3_bucket": "my-production-s3-bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "posthog-events/",
                "bucket_credentials": integration_id,
                "authorization": integration_id,
            },
        },
    }

    batch_export_data = {
        "name": "my-production-redshift-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(client, team.pk, batch_export_data)

    assert response.status_code == expected_status, response.json()

    if expected_status == status.HTTP_400_BAD_REQUEST:
        assert "does not reference an AWS S3 integration" in response.json()["detail"]
    else:
        # EncryptedJSONField stringifies the stored ids; responses must restore them to ints
        # to honor the generated types.
        batch_export = get_batch_export_ok(client, team.pk, response.json()["id"])
        assert batch_export["destination"]["config"]["copy_inputs"]["bucket_credentials"] == integration_id
        assert batch_export["destination"]["config"]["copy_inputs"]["authorization"] == integration_id
