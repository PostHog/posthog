"""AWS role/credential-based integrations (S3, Redshift, S3-compatible endpoints)."""

from collections.abc import Mapping
from typing import ClassVar, Literal

from django.db import transaction

from rest_framework.exceptions import ValidationError

from posthog.credentials import AWSKeyPair
from posthog.models.user import User
from posthog.models.utils import IntegrityError
from posthog.security.url_validation import is_url_allowed

from . import common, model

_AWSKindType = Literal[model.Integration.IntegrationKind.AWS_REDSHIFT, model.Integration.IntegrationKind.AWS_S3]


def _read_aws_credentials(integration: model.Integration) -> AWSKeyPair:
    try:
        # SAFETY: Safety is delegated to the integration which must guarantee
        # sensitive_config keys are correctly assigned.
        return AWSKeyPair.unsafe_from_strings(
            integration.sensitive_config["aws_access_key_id"], integration.sensitive_config["aws_secret_access_key"]
        )
    except KeyError as e:
        raise common.IntegrationError(f"Integration is not valid: {str(e)} missing")


def _create_unique_aws_integration(
    *,
    team_id: int,
    kind: _AWSKindType,
    name: str,
    account_id: str,
    credentials: AWSKeyPair,
    created_by: "User | None",
) -> model.Integration:
    """Create an AWS integration from credentials and an account."""
    return _create_unique_named_integration(
        team_id=team_id,
        kind=kind,
        name=name,
        config={"name": name, "aws_account_id": account_id},
        sensitive_config={
            "aws_access_key_id": credentials.access_key_id,
            "aws_secret_access_key": credentials.secret_access_key,
        },
        created_by=created_by,
    )


class DuplicateNameError(common.IntegrationError):
    pass


def _create_unique_named_integration(
    *,
    team_id: int,
    kind: str,
    name: str,
    config: dict[str, str],
    sensitive_config: dict[str, str],
    created_by: "User | None",
) -> model.Integration:
    """Create an integration, rejecting a name already taken for this team and kind.

    Unlike most integrations, `name` is a free-form user-supplied identifier rather than one derived
    from the external connection (an OAuth account id, service-account email, etc.). So we create
    rather than upsert and raise a 400 error, on conflicts.
    """
    try:
        # Savepoint so the unique-constraint IntegrityError aborts only this INSERT, not the
        # surrounding transaction (e.g. the test wrapper, or any outer atomic block).
        with transaction.atomic():
            return model.Integration.objects.create(
                team_id=team_id,
                kind=kind,
                integration_id=name,
                config=config,
                sensitive_config=sensitive_config,
                created_by=created_by,
            )
    except IntegrityError:
        raise DuplicateNameError(f"An integration named '{name}' already exists")


def is_unique_aws_role_by_organization_id(aws_role_arn: str, organization_id: str) -> bool:
    """Check if the AWS role is only in one organization.

    This is used as a security measure to block multiple organizations from
    assuming the same role.

    In the future we may lift this restriction, but initially we want to make sure about
    AWS role ownership with this check. This complements other runtime checks in
    batch exports; see `get_credentials_using_user_aws_role` in
    `s3_batch_export.py`.
    """
    has_same_aws_role_integrations = (
        model.Integration.objects.select_related("team__organization")
        .filter(
            kind__in=(model.Integration.IntegrationKind.AWS_S3, model.Integration.IntegrationKind.AWS_REDSHIFT),
            config__aws_role_arn=aws_role_arn,
        )
        .exclude(team__organization_id=organization_id)
    ).exists()

    if has_same_aws_role_integrations:
        return False

    return True


def _return_non_empty_str_from_config_for_aws(config: Mapping, key: str, friendly_name: str) -> str:
    return common._return_non_empty_str_from_config(config, key, friendly_name=friendly_name, kind="AWS")


def validate_aws_credentials(aws_access_key_id: str, aws_secret_access_key: str) -> str:
    """Validate AWS credentials via STS GetCallerIdentity, returning the AWS account id.

    GetCallerIdentity requires no IAM permissions, so it verifies the credentials are valid
    without assuming any particular S3 policy. It hits the fixed global AWS STS endpoint, so
    there is no user-controlled endpoint and no SSRF surface (unlike S3-compatible).

    This runs synchronously on the request thread, so the timeout budget is kept tight:
    a single attempt (no retry) bounds the worst case at ~10s (connect + read) if STS is
    unreachable, rather than blocking the worker while botocore retries.
    """
    import boto3  # noqa: PLC0415 — keeps botocore off the module import path (startup time)
    from botocore.config import Config  # noqa: PLC0415
    from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

    client = boto3.client(
        "sts",
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 1}),
    )
    try:
        identity = client.get_caller_identity()
    except ClientError as e:
        message = e.response.get("Error", {}).get("Message") or str(e)
        raise common.IntegrationError(f"AWS credentials are not valid: {message}")
    except BotoCoreError as e:
        raise common.IntegrationError(f"Could not validate AWS credentials: {e}")

    return identity["Account"]


class AWSRoleBasedIntegration:
    """An AWS integration storing a customer's AWS role."""

    integration: model.Integration
    aws_role_arn: str

    integration_kind: ClassVar[_AWSKindType]

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != self.integration_kind:
            raise common.IntegrationError(
                "Integration provided is not the expected AWS integration "
                f"(got kind='{integration.kind}', expected kind='{self.integration_kind}')"
            )
        self.integration = integration
        try:
            self.aws_role_arn = integration.config["aws_role_arn"]
        except KeyError:
            raise common.IntegrationError("AWS integration is not valid: 'aws_role_arn' missing")

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        organization_id: str,
        created_by: "User | None" = None,
        **config,
    ) -> model.Integration:
        name = _return_non_empty_str_from_config_for_aws(config, "name", "A name")
        aws_role_arn = _return_non_empty_str_from_config_for_aws(config, "aws_role_arn", "A valid role ARN")

        if not is_unique_aws_role_by_organization_id(aws_role_arn, organization_id):
            raise ValidationError("Cannot create AWS integration: Invalid role")

        return _create_unique_named_integration(
            team_id=team_id,
            kind=cls.integration_kind,
            name=name,
            config={"name": name, "aws_role_arn": aws_role_arn},
            sensitive_config={},
            created_by=created_by,
        )


class AWSS3RoleBasedIntegration(AWSRoleBasedIntegration):
    """An AWS S3 integration storing a customer's AWS role."""

    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.AWS_S3]] = (
        model.Integration.IntegrationKind.AWS_S3
    )


class AWSRedshiftRoleBasedIntegration(AWSRoleBasedIntegration):
    """An AWS Redshift integration storing a customer's AWS role."""

    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.AWS_REDSHIFT]] = (
        model.Integration.IntegrationKind.AWS_REDSHIFT
    )


class AWSCredentialsIntegration:
    """AWS integration for any service that requires storing long-lived AWS credentials.

    Unlike `S3CompatibleIntegration` it has no `endpoint_url` because an AWS
    integration must never be pointed at an arbitrary endpoint (SSRF boundary).
    """

    integration: model.Integration
    credentials: AWSKeyPair

    integration_kind: ClassVar[_AWSKindType]

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != self.integration_kind:
            raise common.IntegrationError(
                "Integration provided is not the expected AWS integration "
                f"(got kind='{integration.kind}', expected kind='{self.integration_kind}')"
            )
        self.integration = integration
        self.credentials = _read_aws_credentials(integration)

    @property
    def aws_account_id(self) -> str | None:
        """The AWS account id resolved from the credentials at create time, if available."""
        return self.integration.config.get("aws_account_id")

    @property
    def aws_access_key_id(self) -> str:
        return self.credentials.access_key_id

    @property
    def aws_secret_access_key(self) -> str:
        return self.credentials.secret_access_key

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        created_by: "User | None" = None,
        **config,
    ) -> model.Integration:
        name = _return_non_empty_str_from_config_for_aws(config, "name", "A name")
        aws_access_key_id = _return_non_empty_str_from_config_for_aws(
            config,
            "aws_access_key_id",
            "Access key ID",
        )
        aws_secret_access_key = _return_non_empty_str_from_config_for_aws(
            config, "aws_secret_access_key", "Secret access key"
        )

        # Fail fast on invalid/expired credentials, and capture the (non-sensitive) account id.
        account_id = validate_aws_credentials(aws_access_key_id, aws_secret_access_key)

        # SAFETY: We check that each value is non-empty and str type, and, by
        # validating the credentials directly with AWS, we ensure each of these
        # values is what they say they are. This call is safe.
        credentials = AWSKeyPair.unsafe_from_strings(aws_access_key_id, aws_secret_access_key)

        # `name` is the unencrypted, frontend-visible identifier — never an AWS credential, which is
        # treated as a secret. The account id is non-sensitive and kept for display/debugging.
        return _create_unique_aws_integration(
            team_id=team_id,
            kind=cls.integration_kind,
            name=name,
            account_id=account_id,
            credentials=credentials,
            created_by=created_by,
        )


class AWSS3Integration(AWSCredentialsIntegration):
    """An AWS S3 integration storing reusable AWS credentials.

    Holds only credentials; bucket, region, prefix and other export-specific settings stay on the
    batch export destination config, so one credential can be reused across many buckets/regions.
    """

    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.AWS_S3]] = (
        model.Integration.IntegrationKind.AWS_S3
    )


class AWSRedshiftIntegration(AWSCredentialsIntegration):
    """An AWS Redshift integration storing reusable AWS credentials."""

    integration_kind: ClassVar[Literal[model.Integration.IntegrationKind.AWS_REDSHIFT]] = (
        model.Integration.IntegrationKind.AWS_REDSHIFT
    )


def _return_non_empty_str_from_config_for_s3_compatible(config: Mapping, key: str, friendly_name: str) -> str:
    return common._return_non_empty_str_from_config(config, key, friendly_name=friendly_name, kind="S3-compatible")


class S3CompatibleIntegration:
    """An S3-compatible storage integration (Cloudflare R2, DigitalOcean Spaces, Hetzner, etc.).

    Holds the same credentials as `AwsS3Integration` plus the provider `endpoint_url` (non-sensitive),
    since credentials are bound to a specific S3-compatible provider. `integration_from_config`
    SSRF-validates `endpoint_url`, so callers don't have to.

    bucket, region, prefix and other export-specific settings stay on the batch export destination
    config, so one credential can be reused across many buckets/regions.
    """

    integration: model.Integration
    credentials: AWSKeyPair
    endpoint_url: str

    def __init__(self, integration: model.Integration) -> None:
        if integration.kind != model.Integration.IntegrationKind.S3_COMPATIBLE:
            raise common.IntegrationError(
                f"Integration provided is not an S3-compatible integration (got kind='{integration.kind}')"
            )
        self.integration = integration
        self.credentials = _read_aws_credentials(integration)
        try:
            self.endpoint_url = integration.config["endpoint_url"]
        except KeyError:
            raise common.IntegrationError("S3-compatible integration is missing required field: 'endpoint_url'")

    @property
    def aws_access_key_id(self) -> str:
        return self.credentials.access_key_id

    @property
    def aws_secret_access_key(self) -> str:
        return self.credentials.secret_access_key

    @classmethod
    def integration_from_config(
        cls,
        team_id: int,
        created_by: "User | None" = None,
        **config,
    ) -> model.Integration:
        name = _return_non_empty_str_from_config_for_s3_compatible(
            config,
            "name",
            friendly_name="A name",
        )
        aws_access_key_id = _return_non_empty_str_from_config_for_s3_compatible(
            config, "aws_access_key_id", "Access key ID"
        )
        aws_secret_access_key = _return_non_empty_str_from_config_for_s3_compatible(
            config, "aws_secret_access_key", "Secret access key"
        )
        endpoint_url = _return_non_empty_str_from_config_for_s3_compatible(config, "endpoint_url", "Endpoint URL")

        # SSRF protection — credentials must not be testable against an attacker-controlled endpoint.
        allowed, error = is_url_allowed(endpoint_url)
        if not allowed:
            raise common.IntegrationError(f"Invalid endpoint URL: {error}")

        return _create_unique_named_integration(
            team_id=team_id,
            kind=model.Integration.IntegrationKind.S3_COMPATIBLE,
            name=name,
            config={"name": name, "endpoint_url": endpoint_url},
            sensitive_config={
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key,
            },
            created_by=created_by,
        )
