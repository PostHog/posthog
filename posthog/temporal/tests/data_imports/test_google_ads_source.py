import os
import json

import pytest
from unittest import mock

from django.test import override_settings

import pyarrow as pa

from posthog.models import Team
from posthog.models.organization import Organization
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsIsMccAccountConfig, GoogleAdsSourceConfig
from posthog.temporal.data_imports.sources.google_ads.google_ads import (
    GoogleAdsServiceAccountSourceConfig,
    get_schemas,
    google_ads_source,
)
from posthog.temporal.data_imports.sources.google_ads.source import GoogleAdsSource

SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS = pytest.mark.skipif(
    "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS" not in os.environ
    and "GOOGLE_DEVELOPER_TOKEN" not in os.environ
    and "GOOGLE_ADS_CUSTOMER_ID" not in os.environ,
    reason="Google service account credentials and/or developer token not set in environment",
)


@pytest.fixture
def customer_id() -> str:
    """Return customer id if available in environment, otherwise a default."""
    customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", None)

    if not customer_id:
        return "1111111111"
    else:
        return customer_id


@pytest.fixture
def developer_token() -> str:
    """Return developer token if available in environment, otherwise a default."""
    developer_token = os.getenv("GOOGLE_DEVELOPER_TOKEN", None)

    if not developer_token:
        return "aaabbbccc111222333"
    else:
        return developer_token


@pytest.fixture
def service_account_config() -> dict[str, str]:
    """Return a Service Account configuration dictionary to use in tests."""
    credentials_file_path = os.environ["GOOGLE_SERVICE_ACCOUNT_CREDENTIALS"]
    with open(credentials_file_path) as f:
        credentials = json.load(f)

    return {
        "private_key": credentials["private_key"],
        "private_key_id": credentials["private_key_id"],
        "token_uri": credentials["token_uri"],
        "client_email": credentials["client_email"],
    }


def test_google_ads_source_config_loads(customer_id: str, developer_token: str):
    """Test basic case of source configuration loading."""
    private_key = "private_key"
    private_key_id = "id"
    client_email = "posthog@posthog.com"
    token_uri = "https://posthog.com"

    job_inputs = {
        "resource_name": "campaign",
        "customer_id": customer_id,
    }

    with override_settings(
        GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY=private_key,
        GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID=private_key_id,
        GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL=client_email,
        GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI=token_uri,
        GOOGLE_ADS_DEVELOPER_TOKEN=developer_token,
    ):
        cfg = GoogleAdsServiceAccountSourceConfig.from_dict(job_inputs)

    assert cfg.private_key == private_key
    assert cfg.private_key_id == private_key_id
    assert cfg.client_email == client_email
    assert cfg.token_uri == token_uri
    assert cfg.developer_token == developer_token
    assert cfg.customer_id == customer_id


def test_google_ads_source_config_handles_customer_id_with_dashes(developer_token: str):
    """Test source configuration handles clean up of customer id."""
    private_key = "private_key"
    private_key_id = "id"
    client_email = "posthog@posthog.com"
    token_uri = "https://posthog.com"

    job_inputs = {
        "resource_name": "campaign",
        "customer_id": "111-111-1111",
    }

    with override_settings(
        GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY=private_key,
        GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID=private_key_id,
        GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL=client_email,
        GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI=token_uri,
        GOOGLE_ADS_DEVELOPER_TOKEN=developer_token,
    ):
        cfg = GoogleAdsServiceAccountSourceConfig.from_dict(job_inputs)

    assert cfg.private_key == private_key
    assert cfg.private_key_id == private_key_id
    assert cfg.client_email == client_email
    assert cfg.token_uri == token_uri
    assert cfg.developer_token == developer_token
    assert cfg.customer_id == "1111111111"


@SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS
def test_get_schemas(customer_id: str, developer_token: str, service_account_config: dict[str, str]):
    """Test get_schemas returns well-known schemas.

    This test is not exhaustive and merely limits itself to asserting a handful
    of well-known schemas are returned.
    """
    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    cfg = GoogleAdsServiceAccountSourceConfig(
        customer_id=customer_id, developer_token=developer_token, **service_account_config
    )
    schemas = get_schemas(cfg, team_id=team.id)

    assert "campaign" in schemas
    assert "ad_group" in schemas
    assert "ad" in schemas

    campaign = schemas["campaign"]
    assert campaign["campaign_id"].to_arrow_field() == pa.field("campaign_id", pa.int64())
    assert campaign["campaign_name"].to_arrow_field() == pa.field("campaign_name", pa.string())
    assert campaign["campaign_status"].to_arrow_field() == pa.field("campaign_status", pa.string())
    assert campaign["campaign_start_date"].to_arrow_field() == pa.field("campaign_start_date", pa.date32())

    ad_group = schemas["ad_group"]
    assert ad_group["ad_group_id"].to_arrow_field() == pa.field("ad_group_id", pa.int64())
    assert ad_group["campaign_id"].to_arrow_field() == pa.field("campaign_id", pa.int64())
    assert ad_group["ad_group_name"].to_arrow_field() == pa.field("ad_group_name", pa.string())
    assert ad_group["ad_group_status"].to_arrow_field() == pa.field("ad_group_status", pa.string())
    assert ad_group["ad_group_type"].to_arrow_field() == pa.field("ad_group_type", pa.string())

    ad = schemas["ad"]
    assert ad["ad_group_ad_ad_id"].to_arrow_field() == pa.field("ad_group_ad_ad_id", pa.int64())
    assert ad["ad_group_ad_ad_name"].to_arrow_field() == pa.field("ad_group_ad_ad_name", pa.string())
    assert ad["ad_group_ad_ad_type"].to_arrow_field() == pa.field("ad_group_ad_ad_type", pa.string())


@SKIP_IF_MISSING_GOOGLE_ADS_CREDENTIALS
def test_google_ads_source(customer_id: str, developer_token: str, service_account_config: dict[str, str]):
    """Test google_ads_source can iterate rows.

    This test is not exhaustive and merely limits itself to attempting to
    iterate a few sources.
    """

    org = Organization.objects.create(name="org")
    team = Team.objects.create(organization=org)

    cfg = GoogleAdsServiceAccountSourceConfig(
        customer_id=customer_id, developer_token=developer_token, **service_account_config
    )
    for resource in (
        "campaign",
        "campaign_stats",
        "ad_group",
        "ad_group_stats",
        "ad",
        "ad_stats",
        "keyword",
        "keyword_stats",
        "video",
        "video_stats",
    ):
        source = google_ads_source(cfg, resource_name=resource, team_id=team.id)

        _ = list(source.items())


class TestGoogleAdsSourceValidation:
    def setup_method(self):
        self.source = GoogleAdsSource()
        self.team_id = 1

    @pytest.mark.parametrize(
        "customer_id,expected_valid",
        [
            ("123-456-7890", True),
            ("000-000-0000", True),
            ("999-999-9999", True),
            ("1234567890", False),
            ("123-456-789", False),
            ("123-4567-890", False),
            ("12-3456-7890", False),
            ("abc-def-ghij", False),
            ("", True),  # Empty is valid at config level, caught by required field validation
        ],
    )
    def test_validate_config_customer_id_format(self, customer_id, expected_valid):
        job_inputs = {"customer_id": customer_id, "google_ads_integration_id": "1"}

        is_valid, errors = self.source.validate_config(job_inputs)

        if expected_valid:
            assert "Please enter a valid Google Ads customer ID" not in " ".join(errors)
        else:
            assert any("Please enter a valid Google Ads customer ID" in error for error in errors)
            assert is_valid is False

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_success(self, mock_client):
        mock_customer_service = mock.MagicMock()
        mock_customer_service.list_accessible_customers.return_value.resource_names = ["customers/1234567890"]
        mock_client.return_value.get_service.return_value = mock_customer_service

        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert error is None

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_invalid_customer_id(self, mock_client):
        mock_customer_service = mock.MagicMock()
        mock_customer_service.list_accessible_customers.return_value.resource_names = ["customers/9999999999"]
        mock_client.return_value.get_service.return_value = mock_customer_service

        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "is not correct" in error

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_access_token_scope_insufficient(self, mock_client):
        mock_client.return_value.get_service.side_effect = Exception(
            "ACCESS_TOKEN_SCOPE_INSUFFICIENT: Request had insufficient authentication scopes"
        )

        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "Insufficient permissions" in error

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_not_ads_user(self, mock_client):
        mock_client.return_value.get_service.side_effect = Exception(
            "NOT_ADS_USER: The Google account is not associated with any Ads accounts"
        )

        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "not associated with any Google Ads accounts" in error

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_generic_error(self, mock_client):
        mock_client.return_value.get_service.side_effect = Exception("Some unexpected error occurred")

        config = GoogleAdsSourceConfig(customer_id="123-456-7890", google_ads_integration_id=1)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "Error validating credentials" in error

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_mcc_success(self, mock_client):
        mock_ga_service = mock.MagicMock()
        mock_response = [mock.MagicMock()]
        mock_ga_service.search.return_value = mock_response
        mock_client.return_value.get_service.return_value = mock_ga_service

        config = GoogleAdsSourceConfig(
            customer_id="123-456-7890",
            google_ads_integration_id=1,
            is_mcc_account=GoogleAdsIsMccAccountConfig(enabled=True, mcc_client_id="999-888-7777"),
        )

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert error is None
        mock_ga_service.search.assert_called_once()
        call_kwargs = mock_ga_service.search.call_args[1]
        assert call_kwargs["customer_id"] == "1234567890"

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_mcc_customer_not_found(self, mock_client):
        mock_ga_service = mock.MagicMock()
        mock_ga_service.search.side_effect = Exception("CUSTOMER_NOT_FOUND: Customer not found")
        mock_client.return_value.get_service.return_value = mock_ga_service

        config = GoogleAdsSourceConfig(
            customer_id="123-456-7890",
            google_ads_integration_id=1,
            is_mcc_account=GoogleAdsIsMccAccountConfig(enabled=True, mcc_client_id="999-888-7777"),
        )

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "is not accessible" in error

    @mock.patch("posthog.temporal.data_imports.sources.google_ads.source.google_ads_client")
    def test_validate_credentials_mcc_permission_denied(self, mock_client):
        mock_ga_service = mock.MagicMock()
        mock_ga_service.search.side_effect = Exception("USER_PERMISSION_DENIED: User does not have permission")
        mock_client.return_value.get_service.return_value = mock_ga_service

        config = GoogleAdsSourceConfig(
            customer_id="123-456-7890",
            google_ads_integration_id=1,
            is_mcc_account=GoogleAdsIsMccAccountConfig(enabled=True, mcc_client_id="999-888-7777"),
        )

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "is not accessible" in error
