"""Tests for AWS role/credential-based integrations."""

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models.integration import (
    AWSS3Integration,
    DuplicateNameError,
    Integration,
    IntegrationError,
    S3CompatibleIntegration,
    validate_aws_credentials,
)


class TestAWSS3IntegrationModel(BaseTest):
    @patch("posthog.models.integration.aws.validate_aws_credentials", return_value="123456789012")
    def test_integration_from_config_with_valid_config(self, mock_validate):
        integration = AWSS3Integration.integration_from_config(
            team_id=self.team.pk,
            name="prod-aws",
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            created_by=self.user,
        )
        assert integration.team == self.team
        assert integration.created_by == self.user
        assert integration.kind == Integration.IntegrationKind.AWS_S3
        # The identifier is the user-supplied name, never a credential.
        assert integration.integration_id == "prod-aws"
        # The account id resolved from STS is stored in non-sensitive config.
        assert integration.config == {"name": "prod-aws", "aws_account_id": "123456789012"}
        assert integration.sensitive_config == {
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": "secret",
        }
        # display_name surfaces AWS account so users can tell integrations apart.
        assert integration.display_name == "prod-aws (AWS account 123456789012)"
        assert AWSS3Integration(integration).aws_account_id == "123456789012"

    def test_integration_from_config_requires_name(self):
        with pytest.raises(IntegrationError, match="A name is required"):
            AWSS3Integration.integration_from_config(
                team_id=self.team.pk,
                name="",
                aws_access_key_id="AKIAEXAMPLE",
                aws_secret_access_key="secret",
            )

    @patch("posthog.models.integration.aws.validate_aws_credentials", return_value="123456789012")
    def test_integration_from_config_rejects_duplicate_name(self, mock_validate):
        AWSS3Integration.integration_from_config(
            team_id=self.team.pk,
            name="prod-aws",
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
        )
        with pytest.raises(DuplicateNameError, match="An integration named 'prod-aws' already exists"):
            AWSS3Integration.integration_from_config(
                team_id=self.team.pk,
                name="prod-aws",
                aws_access_key_id="AKIAOTHER",
                aws_secret_access_key="other-secret",
            )
        assert Integration.objects.filter(team=self.team, integration_id="prod-aws").count() == 1

    @patch("boto3.client")
    def test_validate_aws_credentials_returns_account_id(self, mock_boto_client):
        mock_boto_client.return_value.get_caller_identity.return_value = {"Account": "123456789012"}
        assert validate_aws_credentials("key", "secret") == "123456789012"

    @patch("boto3.client")
    def test_validate_aws_credentials_raises_on_invalid_credentials(self, mock_boto_client):
        from botocore.exceptions import ClientError

        mock_boto_client.return_value.get_caller_identity.side_effect = ClientError(
            {"Error": {"Code": "InvalidClientTokenId", "Message": "The security token is invalid."}},
            "GetCallerIdentity",
        )
        with pytest.raises(IntegrationError, match="AWS credentials are not valid: The security token is invalid."):
            validate_aws_credentials("key", "secret")

    def test_wrapping_wrong_kind_raises(self):
        integration = Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.S3_COMPATIBLE, integration_id="x"
        )
        with pytest.raises(IntegrationError, match="is not the expected AWS integration"):
            AWSS3Integration(integration)

    def test_wrapping_missing_credentials_raises(self):
        integration = Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.AWS_S3, integration_id="x", sensitive_config={}
        )
        with pytest.raises(IntegrationError, match="missing"):
            AWSS3Integration(integration)


class TestS3CompatibleIntegrationModel(BaseTest):
    def test_integration_from_config_with_valid_config(self):
        integration = S3CompatibleIntegration.integration_from_config(
            team_id=self.team.pk,
            name="my-r2",
            endpoint_url="https://account.r2.cloudflarestorage.com",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            created_by=self.user,
        )
        assert integration.kind == Integration.IntegrationKind.S3_COMPATIBLE
        assert integration.integration_id == "my-r2"
        # endpoint_url is non-sensitive and lives in config.
        assert integration.config == {"name": "my-r2", "endpoint_url": "https://account.r2.cloudflarestorage.com"}
        assert integration.sensitive_config == {"aws_access_key_id": "key", "aws_secret_access_key": "secret"}
        wrapped = S3CompatibleIntegration(integration)
        assert wrapped.endpoint_url == "https://account.r2.cloudflarestorage.com"
        # display_name surfaces auth type and endpoint so users can tell integrations apart.
        assert integration.display_name == "my-r2 (access key, https://account.r2.cloudflarestorage.com)"

    def test_integration_from_config_requires_endpoint_url(self):
        with pytest.raises(IntegrationError, match="Endpoint URL is required"):
            S3CompatibleIntegration.integration_from_config(
                team_id=self.team.pk,
                name="my-r2",
                endpoint_url="",
                aws_access_key_id="key",
                aws_secret_access_key="secret",
            )

    def test_integration_from_config_rejects_duplicate_name(self):
        S3CompatibleIntegration.integration_from_config(
            team_id=self.team.pk,
            name="my-r2",
            endpoint_url="https://account.r2.cloudflarestorage.com",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
        )
        with pytest.raises(DuplicateNameError, match="An integration named 'my-r2' already exists"):
            S3CompatibleIntegration.integration_from_config(
                team_id=self.team.pk,
                name="my-r2",
                endpoint_url="https://other.r2.cloudflarestorage.com",
                aws_access_key_id="key2",
                aws_secret_access_key="secret2",
            )
        assert Integration.objects.filter(team=self.team, integration_id="my-r2").count() == 1

    # is_url_allowed bypasses validation in DEBUG/test mode, so force the production path to exercise rejection.
    @override_settings(FORCE_URL_VALIDATION=True)
    def test_integration_from_config_rejects_internal_endpoint(self):
        with pytest.raises(IntegrationError, match="Invalid endpoint URL"):
            S3CompatibleIntegration.integration_from_config(
                team_id=self.team.pk,
                name="my-r2",
                endpoint_url="https://169.254.169.254",
                aws_access_key_id="key",
                aws_secret_access_key="secret",
            )

    def test_wrapping_missing_endpoint_url_raises(self):
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.S3_COMPATIBLE,
            integration_id="x",
            config={"name": "x"},
            sensitive_config={"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
        )
        with pytest.raises(IntegrationError, match="missing required field: 'endpoint_url'"):
            S3CompatibleIntegration(integration)
