import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldOauthConfig

from posthog.temporal.data_imports.sources.generated_configs import RedditAdsSourceConfig
from posthog.temporal.data_imports.sources.reddit_ads.source import RedditAdsSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestRedditAdsSource:
    """Test suite for RedditAdsSource class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = RedditAdsSource()
        self.team_id = 123
        self.config = RedditAdsSourceConfig(reddit_integration_id=456, account_id="789")

    def test_source_type(self):
        """Test source type property."""
        assert self.source.source_type == ExternalDataSourceType.REDDITADS

    def test_get_source_config(self):
        """Test get_source_config returns proper configuration."""
        config = self.source.get_source_config

        assert config.name.value == "RedditAds"
        assert config.label == "Reddit Ads"
        assert config.betaSource is True
        assert len(config.fields) == 2

        # Check account_id field
        account_field = config.fields[0]
        assert isinstance(account_field, SourceFieldInputConfig)
        assert account_field.name == "account_id"
        assert account_field.label == "Reddit Ads Account ID"
        assert account_field.required is True
        assert account_field.placeholder == "Your Reddit Ads account ID"

        # Check oauth field
        oauth_field = config.fields[1]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "reddit_integration_id"
        assert oauth_field.label == "Reddit Ads account"
        assert oauth_field.required is True
        assert oauth_field.kind == "reddit-ads"

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation with missing account ID."""
        invalid_config = RedditAdsSourceConfig(reddit_integration_id=456, account_id="")

        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Account ID and Reddit Ads integration are required" in error_message

    def test_validate_credentials_missing_integration_id(self):
        """Test credential validation with missing integration ID."""
        invalid_config = RedditAdsSourceConfig(reddit_integration_id=0, account_id="789")

        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Account ID and Reddit Ads integration are required" in error_message

    @mock.patch("posthog.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration")
    def test_validate_credentials_success(self, mock_get_oauth_integration):
        """Test successful credential validation."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth_integration.return_value = mock_integration

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_get_oauth_integration.assert_called_once_with(self.config.reddit_integration_id, self.team_id)

    @mock.patch("posthog.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration")
    @mock.patch("posthog.temporal.data_imports.sources.reddit_ads.source.capture_exception")
    def test_validate_credentials_integration_error(self, mock_capture_exception, mock_get_oauth_integration):
        """Test credential validation with integration error."""
        mock_get_oauth_integration.side_effect = Exception("Integration not found")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Failed to validate Reddit Ads credentials" in error_message
        assert "Integration not found" in error_message
        mock_capture_exception.assert_called_once()

    def test_get_schemas(self):
        """Test get_schemas returns all endpoint schemas."""
        schemas = self.source.get_schemas(self.config, self.team_id)

        # Should have schemas for all endpoints in REDDIT_ADS_CONFIG
        expected_endpoints = ["campaigns", "ad_groups", "ads", "campaign_report", "ad_group_report", "ad_report"]
        assert len(schemas) == len(expected_endpoints)

        schema_names = [schema.name for schema in schemas]
        for endpoint in expected_endpoints:
            assert endpoint in schema_names

    @mock.patch("posthog.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration")
    def test_source_for_pipeline_success(self, mock_get_oauth_integration):
        """Test source_for_pipeline with valid integration."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth_integration.return_value = mock_integration

        # Mock the reddit_ads_source function
        with mock.patch(
            "posthog.temporal.data_imports.sources.reddit_ads.source.reddit_ads_source"
        ) as mock_reddit_ads_source:
            mock_response = mock.MagicMock()
            mock_reddit_ads_source.return_value = mock_response

            inputs = mock.MagicMock()
            inputs.team_id = self.team_id
            inputs.job_id = "test_job"
            inputs.schema_name = "campaigns"
            inputs.should_use_incremental_field = False
            inputs.db_incremental_field_last_value = None

            result = self.source.source_for_pipeline(self.config, inputs)

            assert result == mock_response
            mock_get_oauth_integration.assert_called_once_with(self.config.reddit_integration_id, self.team_id)
            mock_reddit_ads_source.assert_called_once_with(
                account_id=self.config.account_id,
                endpoint="campaigns",
                team_id=self.team_id,
                job_id="test_job",
                access_token="test_token",
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )

    @mock.patch("posthog.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration")
    def test_source_for_pipeline_no_access_token(self, mock_get_oauth_integration):
        """Test source_for_pipeline with no access token raises error."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_get_oauth_integration.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test_job"
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        with pytest.raises(ValueError, match="Reddit Ads access token not found for job test_job"):
            self.source.source_for_pipeline(self.config, inputs)

    @mock.patch("posthog.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration")
    def test_source_for_pipeline_with_incremental(self, mock_get_oauth_integration):
        """Test source_for_pipeline with incremental field."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth_integration.return_value = mock_integration

        with mock.patch(
            "posthog.temporal.data_imports.sources.reddit_ads.source.reddit_ads_source"
        ) as mock_reddit_ads_source:
            mock_response = mock.MagicMock()
            mock_reddit_ads_source.return_value = mock_response

            inputs = mock.MagicMock()
            inputs.team_id = self.team_id
            inputs.job_id = "test_job"
            inputs.schema_name = "campaign_report"
            inputs.should_use_incremental_field = True
            inputs.db_incremental_field_last_value = "2024-03-15"

            result = self.source.source_for_pipeline(self.config, inputs)

            assert result == mock_response
            mock_reddit_ads_source.assert_called_once_with(
                account_id=self.config.account_id,
                endpoint="campaign_report",
                team_id=self.team_id,
                job_id="test_job",
                access_token="test_token",
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-03-15",
            )
