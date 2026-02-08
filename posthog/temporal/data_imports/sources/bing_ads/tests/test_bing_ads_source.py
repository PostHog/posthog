import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldOauthConfig

from posthog.temporal.data_imports.sources.bing_ads.source import BingAdsSource
from posthog.temporal.data_imports.sources.generated_configs import BingAdsSourceConfig

from products.data_warehouse.backend.types import ExternalDataSourceType, IncrementalFieldType


class TestBingAdsSource:
    """Test suite for BingAdsSource configuration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = BingAdsSource()
        self.team_id = 123
        self.valid_config = BingAdsSourceConfig(
            account_id="12345",
            bing_ads_integration_id=1,
        )

    def test_source_type(self):
        """Test source type is correctly set."""
        assert self.source.source_type == ExternalDataSourceType.BINGADS

    def test_get_source_config(self):
        """Test source configuration is properly structured."""
        config = self.source.get_source_config

        assert config.name.value == "BingAds"
        assert config.label == "Bing Ads"
        assert config.betaSource is True
        assert config.iconPath == "/static/services/bing-ads.svg"
        assert len(config.fields) == 2

        account_id_field = config.fields[0]
        assert isinstance(account_id_field, SourceFieldInputConfig)
        assert account_id_field.name == "account_id"
        assert account_id_field.required is True

        oauth_field = config.fields[1]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "bing_ads_integration_id"
        assert oauth_field.required is True
        assert oauth_field.kind == "bing-ads"

    def test_validate_credentials_missing_account_id(self):
        """Test validation fails when account ID is missing."""
        config = BingAdsSourceConfig(account_id="", bing_ads_integration_id=1)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Account ID and Bing Ads integration are required"

    def test_validate_credentials_missing_integration_id(self):
        """Test validation fails when integration ID is missing."""
        config = BingAdsSourceConfig(account_id="12345", bing_ads_integration_id=0)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error == "Account ID and Bing Ads integration are required"

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_validate_credentials_success(self, mock_get_oauth):
        """Test successful credential validation."""
        mock_integration = mock.MagicMock()
        mock_get_oauth.return_value = mock_integration

        is_valid, error = self.source.validate_credentials(self.valid_config, self.team_id)

        assert is_valid is True
        assert error is None
        mock_get_oauth.assert_called_once_with(1, self.team_id)

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_validate_credentials_oauth_error(self, mock_get_oauth):
        """Test validation fails when OAuth integration raises error."""
        mock_get_oauth.side_effect = Exception("OAuth error")

        is_valid, error = self.source.validate_credentials(self.valid_config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert "Failed to validate Bing Ads credentials" in error

    def test_get_schemas(self):
        """Test getting available schemas."""
        schemas = self.source.get_schemas(self.valid_config, self.team_id)

        assert len(schemas) > 0

        schema_names = [s.name for s in schemas]
        assert "campaigns" in schema_names
        assert "campaign_performance_report" in schema_names
        assert "ad_group_performance_report" in schema_names
        assert "ad_performance_report" in schema_names

        campaigns_schema = next(s for s in schemas if s.name == "campaigns")
        assert campaigns_schema.supports_incremental is False
        assert campaigns_schema.supports_append is False
        assert len(campaigns_schema.incremental_fields) == 0

        report_schema = next(s for s in schemas if s.name == "campaign_performance_report")
        assert report_schema.supports_incremental is True
        assert report_schema.supports_append is True
        assert len(report_schema.incremental_fields) == 1
        assert report_schema.incremental_fields[0]["field"] == "TimePeriod"
        assert report_schema.incremental_fields[0]["field_type"] == IncrementalFieldType.Date

    @mock.patch("posthog.temporal.data_imports.sources.bing_ads.source.bing_ads_source")
    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_campaigns(self, mock_get_oauth, mock_bing_ads_source):
        """Test creating source for pipeline with campaigns."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_access_token"
        mock_integration.refresh_token = "test_refresh_token"
        mock_get_oauth.return_value = mock_integration

        mock_source_response = mock.MagicMock()
        mock_bing_ads_source.return_value = mock_source_response

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.incremental_field_type = None
        inputs.db_incremental_field_last_value = None

        result = self.source.source_for_pipeline(self.valid_config, inputs)

        assert result == mock_source_response
        mock_bing_ads_source.assert_called_once_with(
            account_id="12345",
            resource_name="campaigns",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )

    @mock.patch("posthog.temporal.data_imports.sources.bing_ads.source.bing_ads_source")
    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_report_incremental(self, mock_get_oauth, mock_bing_ads_source):
        """Test creating source for pipeline with incremental report."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_access_token"
        mock_integration.refresh_token = "test_refresh_token"
        mock_get_oauth.return_value = mock_integration

        mock_source_response = mock.MagicMock()
        mock_bing_ads_source.return_value = mock_source_response

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaign_performance_report"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "TimePeriod"
        inputs.incremental_field_type = IncrementalFieldType.Date
        inputs.db_incremental_field_last_value = "2024-01-01"

        result = self.source.source_for_pipeline(self.valid_config, inputs)

        assert result == mock_source_response
        mock_bing_ads_source.assert_called_once_with(
            account_id="12345",
            resource_name="campaign_performance_report",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            should_use_incremental_field=True,
            incremental_field="TimePeriod",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value="2024-01-01",
        )

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_missing_access_token(self, mock_get_oauth):
        """Test source_for_pipeline raises error when access token is missing."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_integration.refresh_token = "test_refresh_token"
        mock_get_oauth.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaigns"

        with pytest.raises(ValueError, match="Bing Ads access token not found for job test-job-id"):
            self.source.source_for_pipeline(self.valid_config, inputs)

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_missing_refresh_token(self, mock_get_oauth):
        """Test source_for_pipeline raises error when refresh token is missing."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_access_token"
        mock_integration.refresh_token = None
        mock_get_oauth.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaigns"

        with pytest.raises(ValueError, match="Bing Ads refresh token not found for job test-job-id"):
            self.source.source_for_pipeline(self.valid_config, inputs)
