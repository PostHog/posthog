from collections.abc import AsyncGenerator

import pytest

import pytest_asyncio
from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.batch_exports.backend.service import AWSCredentials
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    ConnectionParameters,
    RedshiftIntegrationError,
    RedshiftIntegrationNotFoundError,
    _resolve_redshift_connection_parameters,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
]


@pytest_asyncio.fixture
async def redshift_team(db) -> AsyncGenerator[Team]:
    organization = await sync_to_async(Organization.objects.create)(name="Redshift integration test org")
    team = await sync_to_async(Team.objects.create)(organization=organization, name="Redshift integration test team")

    yield team

    await sync_to_async(team.delete)()
    await sync_to_async(organization.delete)()


async def test_resolve_redshift_connection_parameters_from_password_integration(redshift_team: Team) -> None:
    integration = await Integration.objects.acreate(
        team_id=redshift_team.pk,
        kind=Integration.IntegrationKind.REDSHIFT,
        integration_id="prod-redshift",
        config={
            "name": "prod-redshift",
            "authentication_type": "password",
            "user": "batch_exporter",
        },
        sensitive_config={"password": "secret"},
    )

    connection = await _resolve_redshift_connection_parameters(
        ConnectionParameters(
            database="analytics",
            host="example-redshift.abc123.us-east-1.redshift.amazonaws.com",
            port=5439,
            integration_id=integration.id,
        ),
        team_id=redshift_team.pk,
        batch_export_id="batch-export-id",
    )

    assert connection.user == "batch_exporter"
    assert connection.password == "secret"
    assert connection.host == "example-redshift.abc123.us-east-1.redshift.amazonaws.com"
    assert connection.port == 5439
    assert connection.database == "analytics"


async def test_resolve_redshift_connection_parameters_from_iam_role_integration(
    monkeypatch, redshift_team: Team
) -> None:
    integration = await Integration.objects.acreate(
        team_id=redshift_team.pk,
        kind=Integration.IntegrationKind.REDSHIFT,
        integration_id="serverless-prod",
        config={
            "name": "serverless-prod",
            "authentication_type": "iam_role",
            "aws_role_arn": "arn:aws:iam::123456789012:role/posthog-redshift",
        },
    )
    calls: dict[str, object] = {}

    async def fake_get_credentials_using_user_aws_role(
        aws_role_arn: str,
        external_id: str,
        *,
        session_name: str,
        policy_statements: list[dict],
    ) -> AWSCredentials:
        calls["assume_role"] = {
            "aws_role_arn": aws_role_arn,
            "external_id": external_id,
            "session_name": session_name,
            "policy_statements": policy_statements,
        }
        return AWSCredentials(
            aws_access_key_id="aws-access-key",
            aws_secret_access_key="aws-secret-key",
            aws_session_token="aws-session-token",
        )

    async def fake_get_redshift_serverless_connection_parameters(
        *,
        credentials: AWSCredentials,
        region: str,
        workgroup_name: str,
        database: str,
    ) -> ConnectionParameters:
        calls["serverless"] = {
            "credentials": credentials,
            "region": region,
            "workgroup_name": workgroup_name,
            "database": database,
        }
        return ConnectionParameters(
            user="IAM:batch_exporter",
            password="temporary-password",
            host="workgroup.123.us-east-1.redshift-serverless.amazonaws.com",
            port=5439,
            database=database,
        )

    monkeypatch.setattr(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.get_credentials_using_user_aws_role",
        fake_get_credentials_using_user_aws_role,
    )
    monkeypatch.setattr(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export._get_redshift_serverless_connection_parameters",
        fake_get_redshift_serverless_connection_parameters,
    )

    connection = await _resolve_redshift_connection_parameters(
        ConnectionParameters(
            database="analytics",
            host="analytics-workgroup.123456789012.us-east-1.redshift-serverless.amazonaws.com",
            integration_id=integration.id,
        ),
        team_id=redshift_team.pk,
        batch_export_id="batch-export-id",
    )

    assert connection.user == "IAM:batch_exporter"
    assert connection.password == "temporary-password"
    assert connection.host == "workgroup.123.us-east-1.redshift-serverless.amazonaws.com"
    assert calls["assume_role"] == {
        "aws_role_arn": "arn:aws:iam::123456789012:role/posthog-redshift",
        "external_id": f"posthog-{redshift_team.organization_id}",
        "session_name": "PostHog-redshift-batch-export-batch-export-id",
        "policy_statements": [
            {
                "Effect": "Allow",
                "Action": ["redshift-serverless:GetCredentials", "redshift-serverless:GetWorkgroup"],
                "Resource": "*",
            }
        ],
    }
    assert calls["serverless"] == {
        "credentials": AWSCredentials("aws-access-key", "aws-secret-key", "aws-session-token"),
        "region": "us-east-1",
        "workgroup_name": "analytics-workgroup",
        "database": "analytics",
    }


async def test_resolve_redshift_connection_parameters_rejects_missing_integration(redshift_team: Team) -> None:
    with pytest.raises(RedshiftIntegrationNotFoundError):
        await _resolve_redshift_connection_parameters(
            ConnectionParameters(database="analytics", integration_id=999999),
            team_id=redshift_team.pk,
            batch_export_id="batch-export-id",
        )


async def test_resolve_redshift_connection_parameters_rejects_non_serverless_host(
    monkeypatch, redshift_team: Team
) -> None:
    integration = await Integration.objects.acreate(
        team_id=redshift_team.pk,
        kind=Integration.IntegrationKind.REDSHIFT,
        integration_id="serverless-prod",
        config={
            "name": "serverless-prod",
            "authentication_type": "iam_role",
            "aws_role_arn": "arn:aws:iam::123456789012:role/posthog-redshift",
        },
    )

    async def fail_get_credentials_using_user_aws_role(*args: object, **kwargs: object) -> AWSCredentials:
        raise AssertionError("AWS credentials should not be requested for unsupported hosts")

    monkeypatch.setattr(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.get_credentials_using_user_aws_role",
        fail_get_credentials_using_user_aws_role,
    )

    with pytest.raises(RedshiftIntegrationError, match="IAM role authentication requires a Redshift Serverless host"):
        await _resolve_redshift_connection_parameters(
            ConnectionParameters(
                database="analytics",
                host="cluster.abc123.us-east-1.redshift.amazonaws.com",
                integration_id=integration.id,
            ),
            team_id=redshift_team.pk,
            batch_export_id="batch-export-id",
        )
