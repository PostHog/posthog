import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldOauthConfig

from posthog.temporal.data_imports.sources.generated_configs import PinterestAdsSourceConfig
from posthog.temporal.data_imports.sources.pinterest_ads.source import PinterestAdsSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestPinterestAdsSource:
    def setup_method(self):
        self.source = PinterestAdsSource()
        self.team_id = 123
        self.config = PinterestAdsSourceConfig(pinterest_ads_integration_id=456, ad_account_id="789")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PINTERESTADS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "PinterestAds"
        assert config.label == "Pinterest Ads"
        assert config.betaSource is True
        assert config.featureFlag == "pinterest-ads-source"
        assert len(config.fields) == 2

        account_field = config.fields[0]
        assert isinstance(account_field, SourceFieldInputConfig)
        assert account_field.name == "ad_account_id"
        assert account_field.required is True

        oauth_field = config.fields[1]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "pinterest_ads_integration_id"
        assert oauth_field.kind == "pinterest-ads"
        assert oauth_field.required is True

    def test_validate_credentials_missing_account_id(self):
        invalid_config = PinterestAdsSourceConfig(pinterest_ads_integration_id=456, ad_account_id="")
        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert "Ad Account ID and Pinterest Ads integration are required" in error_message

    def test_validate_credentials_missing_integration_id(self):
        invalid_config = PinterestAdsSourceConfig(pinterest_ads_integration_id=0, ad_account_id="789")
        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert "Ad Account ID and Pinterest Ads integration are required" in error_message

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.source.validate_ad_account")
    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    def test_validate_credentials_success(self, mock_get_oauth, mock_validate):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth.return_value = mock_integration
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.source.capture_exception")
    def test_validate_credentials_integration_error(self, mock_capture, mock_get_oauth):
        mock_get_oauth.side_effect = Exception("Integration not found")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Failed to validate Pinterest Ads credentials" in error_message
        mock_capture.assert_called_once()

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        expected_endpoints = [
            "campaigns",
            "ad_groups",
            "ads",
            "campaign_analytics",
            "ad_group_analytics",
            "ad_analytics",
        ]
        assert len(schemas) == len(expected_endpoints)

        schema_names = [schema.name for schema in schemas]
        for endpoint in expected_endpoints:
            assert endpoint in schema_names

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    def test_source_for_pipeline_success(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth.return_value = mock_integration

        with mock.patch(
            "posthog.temporal.data_imports.sources.pinterest_ads.source.pinterest_ads_source"
        ) as mock_pipeline:
            mock_response = mock.MagicMock()
            mock_pipeline.return_value = mock_response

            inputs = mock.MagicMock()
            inputs.team_id = self.team_id
            inputs.job_id = "test_job"
            inputs.schema_name = "campaigns"
            inputs.should_use_incremental_field = False
            inputs.db_incremental_field_last_value = None

            result = self.source.source_for_pipeline(self.config, inputs)

            assert result == mock_response
            mock_pipeline.assert_called_once_with(
                ad_account_id=self.config.ad_account_id,
                endpoint="campaigns",
                access_token="test_token",
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )

    @mock.patch("posthog.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    def test_source_for_pipeline_no_access_token(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_get_oauth.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test_job"
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        with pytest.raises(ValueError, match="Pinterest Ads access token not found for job test_job"):
            self.source.source_for_pipeline(self.config, inputs)
