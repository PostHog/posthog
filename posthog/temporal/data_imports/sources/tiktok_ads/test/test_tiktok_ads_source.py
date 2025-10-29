"""Tests for TikTok Ads source integration."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import Mock, patch

import structlog
from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.sources.generated_configs import TikTokAdsSourceConfig
from posthog.temporal.data_imports.sources.tiktok_ads.source import TikTokAdsSource
from posthog.warehouse.types import ExternalDataSourceType, IncrementalFieldType


class TestTikTokAdsSource:
    """Test suite for TikTok Ads source integration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = TikTokAdsSource()
        self.team_id = 123
        self.advertiser_id = "123456789"
        self.integration_id = 456
        self.job_id = str(uuid4())

        self.config = TikTokAdsSourceConfig(advertiser_id=self.advertiser_id, tiktok_integration_id=self.integration_id)

        self.mock_integration = Mock(spec=Integration)
        self.mock_integration.access_token = "test_access_token"
        self.mock_integration.team_id = self.team_id

    def test_source_type(self):
        """Test that source type is correctly identified."""
        assert self.source.source_type == ExternalDataSourceType.TIKTOKADS

    def test_get_source_config(self):
        """Test source configuration generation."""
        config = self.source.get_source_config

        assert config.name.value == "TikTokAds"
        assert config.label == "TikTok Ads"
        assert config.betaSource is True
        assert len(config.fields) == 2

        advertiser_field = config.fields[0]
        assert advertiser_field.name == "advertiser_id"
        assert hasattr(advertiser_field, "required") and advertiser_field.required is True

        integration_field = config.fields[1]
        assert integration_field.name == "tiktok_integration_id"
        assert hasattr(integration_field, "kind") and integration_field.kind == "tiktok-ads"

    @parameterized.expand(
        [
            ("missing_advertiser_id", "", 123, False, "Advertiser ID and TikTok Ads integration are required"),
            (
                "missing_integration_id",
                "123456789",
                0,
                False,
                "Advertiser ID and TikTok Ads integration are required",
            ),
            ("valid_credentials", "test_advertiser", 123, True, None),
        ]
    )
    def test_validate_credentials(self, name, advertiser_id, integration_id, expected_valid, expected_error):
        """Test credential validation scenarios."""
        config = TikTokAdsSourceConfig(advertiser_id=advertiser_id, tiktok_integration_id=integration_id)

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            if expected_valid:
                mock_get_integration.return_value = self.mock_integration
            else:
                mock_get_integration.side_effect = Exception("Integration not found")

            is_valid, error = self.source.validate_credentials(config, self.team_id)

            assert is_valid == expected_valid
            if expected_error:
                assert expected_error in str(error)

    def test_get_schemas(self):
        """Test schema retrieval."""
        schemas = self.source.get_schemas(self.config, self.team_id)

        expected_schemas = {"campaigns", "ad_groups", "ads", "campaign_report", "ad_group_report", "ad_report"}
        actual_schema_names = {schema.name for schema in schemas}

        assert actual_schema_names == expected_schemas

        for schema in schemas:
            if "report" in schema.name:
                assert schema.supports_incremental is True
                field_names = [field["field"] for field in schema.incremental_fields]
                assert "stat_time_day" in field_names
            else:
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    @patch("posthog.temporal.data_imports.sources.tiktok_ads.source.tiktok_ads_source")
    def test_source_for_pipeline_success(self, mock_tiktok_source):
        """Test successful pipeline source creation."""
        inputs = SourceInputs(
            schema_name="campaigns",
            schema_id="campaigns_schema",
            team_id=self.team_id,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now() - timedelta(days=1),
            db_incremental_field_earliest_value=None,
            incremental_field="modify_time",
            incremental_field_type=IncrementalFieldType.DateTime,
            job_id=self.job_id,
            logger=structlog.get_logger(),
        )

        mock_response = Mock()
        mock_tiktok_source.return_value = mock_response

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.return_value = self.mock_integration

            result = self.source.source_for_pipeline(self.config, inputs)

            assert result == mock_response
            mock_tiktok_source.assert_called_once_with(
                advertiser_id=self.advertiser_id,
                endpoint="campaigns",
                team_id=self.team_id,
                job_id=self.job_id,
                access_token="test_access_token",
                should_use_incremental_field=True,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            )

    def test_source_for_pipeline_no_access_token(self):
        """Test pipeline source creation fails without access token."""
        inputs = SourceInputs(
            schema_name="campaigns",
            schema_id="campaigns_schema",
            team_id=self.team_id,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id=self.job_id,
            logger=structlog.get_logger(),
        )

        self.mock_integration.access_token = None

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.return_value = self.mock_integration

            with pytest.raises(ValueError, match="TikTok Ads access token not found"):
                self.source.source_for_pipeline(self.config, inputs)

    def test_validate_credentials_exception_handling(self):
        """Test credential validation handles exceptions properly."""
        config = TikTokAdsSourceConfig(advertiser_id="123456789", tiktok_integration_id=123)

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.side_effect = Exception("Network error")

            is_valid, error = self.source.validate_credentials(config, self.team_id)

            assert is_valid is False
            assert "Failed to validate TikTok Ads credentials" in str(error)
