import datetime as dt

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.bing_ads.bing_ads import bing_ads_source
from posthog.temporal.data_imports.sources.bing_ads.schemas import BingAdsResource
from posthog.temporal.data_imports.sources.bing_ads.utils import fetch_data_in_yearly_chunks, parse_csv_to_dicts

from products.data_warehouse.backend.types import IncrementalFieldType


class TestBingAdsHelperFunctions:
    """Test helper functions in bing_ads.py and utils.py."""

    def test_parse_csv_to_dicts_valid_data(self):
        """Test parsing valid CSV report data."""
        csv_data = """TimePeriod,CampaignId,CampaignName,Impressions,Clicks
2024-01-01,123,Test Campaign,1000,50
2024-01-02,123,Test Campaign,1200,60"""

        result = parse_csv_to_dicts(csv_data)

        assert len(result) == 2
        assert result[0]["TimePeriod"] == "2024-01-01"
        assert result[0]["CampaignId"] == "123"
        assert result[0]["Impressions"] == "1000"
        assert result[1]["TimePeriod"] == "2024-01-02"

    def test_parse_csv_to_dicts_with_null_values(self):
        """Test parsing CSV with null values (--) and empty strings."""
        csv_data = """TimePeriod,CampaignId,CampaignName,Impressions,Clicks
2024-01-01,123,Test Campaign,--,
2024-01-02,456,--,1000,50"""

        result = parse_csv_to_dicts(csv_data)

        assert len(result) == 2
        assert result[0]["Impressions"] is None
        assert result[0]["Clicks"] is None
        assert result[1]["CampaignName"] is None

    @patch("posthog.temporal.data_imports.sources.bing_ads.utils.logger")
    def test_fetch_data_in_yearly_chunks_single_chunk(self, mock_logger):
        """Test fetching data within a single year."""
        mock_client = Mock()
        mock_client.get_data_by_resource.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        start_date = dt.date(2024, 1, 1)
        end_date = dt.date(2024, 6, 30)

        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
            )
        )

        assert len(result) == 1
        assert result[0][0]["CampaignId"] == "123"
        mock_client.get_data_by_resource.assert_called_once()

    @patch("posthog.temporal.data_imports.sources.bing_ads.utils.logger")
    def test_fetch_data_in_yearly_chunks_multiple_chunks(self, mock_logger):
        """Test fetching data across multiple years."""
        mock_client = Mock()
        mock_client.get_data_by_resource.side_effect = [
            iter([[{"year": "2023"}]]),
            iter([[{"year": "2024"}]]),
            iter([[{"year": "2025"}]]),
        ]

        start_date = dt.date(2023, 1, 1)
        end_date = dt.date(2025, 6, 30)

        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
            )
        )

        assert len(result) == 3
        assert mock_client.get_data_by_resource.call_count == 3

    @patch("posthog.temporal.data_imports.sources.bing_ads.utils.logger")
    def test_fetch_data_in_yearly_chunks_with_errors(self, mock_logger):
        """Test fetching data with some chunks failing."""
        mock_client = Mock()
        mock_client.get_data_by_resource.side_effect = [
            iter([[{"year": "2023"}]]),
            Exception("API Error"),
            iter([[{"year": "2025"}]]),
        ]

        start_date = dt.date(2023, 1, 1)
        end_date = dt.date(2025, 6, 30)

        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
            )
        )

        assert len(result) == 2
        mock_logger.error.assert_called_once()


class TestBingAdsSource:
    """Test suite for main Bing Ads source function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.account_id = "12345"
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"

    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_campaigns(self, mock_integrations, mock_client_class):
        """Test source function for campaigns (non-report endpoint)."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        mock_client = Mock()
        mock_client.get_data_by_resource.return_value = iter([[{"Id": "123", "Name": "Test Campaign"}]])
        mock_client_class.return_value = mock_client

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaigns",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            should_use_incremental_field=False,
        )

        assert result.name == "campaigns"
        assert result.primary_keys == ["Id"]
        assert result.partition_mode is None

        data = list(result.items())
        assert len(data) == 1
        assert data[0][0]["Id"] == "123"

    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.fetch_data_in_yearly_chunks")
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_report_full_refresh(self, mock_integrations, mock_client_class, mock_fetch_chunks):
        """Test source function for report endpoint with full refresh."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_fetch_chunks.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            should_use_incremental_field=False,
        )

        assert result.name == "campaign_performance_report"
        assert result.primary_keys == ["CampaignId", "TimePeriod"]
        assert result.partition_mode == "datetime"

        data = list(result.items())
        assert len(data) == 1

    @parameterized.expand(
        [
            ("with_datetime", dt.datetime(2024, 6, 15, 14, 30)),
            ("with_date", dt.date(2024, 6, 15)),
            ("with_string", "2024-06-15T14:30:00"),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.fetch_data_in_yearly_chunks")
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_report_incremental(
        self, _name, last_value, mock_integrations, mock_client_class, mock_fetch_chunks
    ):
        """Test source function for report endpoint with incremental sync."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_fetch_chunks.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            should_use_incremental_field=True,
            incremental_field="TimePeriod",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=last_value,
        )

        assert result.name == "campaign_performance_report"
        data = list(result.items())
        assert len(data) == 1

        mock_fetch_chunks.assert_called_once()
        call_args = mock_fetch_chunks.call_args
        assert call_args.kwargs["start_date"] <= dt.date.today()

    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_missing_developer_token(self, mock_integrations):
        """Test source function raises error when developer token is missing."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = None

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaigns",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
        )

        with pytest.raises(ValueError, match="Bing Ads developer token not configured"):
            list(result.items())

    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("posthog.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_incremental_missing_field(self, mock_integrations, mock_client_class):
        """Test source function raises error when incremental field is missing."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 1, 1),
        )

        with pytest.raises(
            ValueError, match="incremental_field and incremental_field_type required for incremental sync"
        ):
            list(result.items())
