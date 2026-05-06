import json

import pytest
from unittest import mock

import requests

from posthog.temporal.data_imports.sources.linkedin_ads.client import (
    LinkedinAdsClient,
    LinkedinAdsPivot,
    LinkedinAdsRetryableError,
)


class TestLinkedinAdsClient:
    """Test suite for LinkedinAdsClient."""

    def setup_method(self):
        """Set up test fixtures."""
        self.access_token = "test_access_token"
        self.account_id = "12345"

    def test_init_with_empty_token_raises_error(self):
        """Test client initialization with empty token raises ValueError."""
        with pytest.raises(ValueError, match="Access token required"):
            LinkedinAdsClient("")

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_accounts_success(self, mock_restli_client):
        """Test successful accounts retrieval."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"id": "123", "name": "Test Account"}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "123", "name": "Test Account"}]
        mock_client_instance.finder.assert_called_once()

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_accounts_api_error(self, mock_restli_client):
        """Test accounts retrieval with API error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_response.response.text = "Unauthorized"

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(Exception, match="LinkedIn API error \\(401\\): Unauthorized"):
            client.get_accounts()

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_campaigns_pagination(self, mock_restli_client):
        """Test successful campaigns retrieval with pagination."""
        # First page response
        mock_response1 = mock.MagicMock()
        mock_response1.status_code = 200
        mock_response1.elements = [{"id": "camp1", "name": "Campaign 1"}]
        mock_response1.response.text = json.dumps({"metadata": {"nextPageToken": "token123"}})

        # Second page response
        mock_response2 = mock.MagicMock()
        mock_response2.status_code = 200
        mock_response2.elements = [{"id": "camp2", "name": "Campaign 2"}]
        mock_response2.response.text = json.dumps({"metadata": {}})

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [mock_response1, mock_response2]

        client = LinkedinAdsClient(self.access_token)
        pages = list(client.get_campaigns(self.account_id))

        assert len(pages) == 2
        assert pages[0] == ([{"id": "camp1", "name": "Campaign 1"}], "token123")
        assert pages[1] == ([{"id": "camp2", "name": "Campaign 2"}], None)
        assert mock_client_instance.finder.call_count == 2

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_campaigns_resumes_from_starting_page_token(self, mock_restli_client):
        """Starting page token must be passed as pageToken on the first request."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"id": "camp2", "name": "Campaign 2"}]
        mock_response.response.text = json.dumps({"metadata": {}})

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        pages = list(client.get_campaigns(self.account_id, starting_page_token="resume-token-abc"))

        assert len(pages) == 1
        assert pages[0] == ([{"id": "camp2", "name": "Campaign 2"}], None)
        assert mock_client_instance.finder.call_count == 1
        call_params = mock_client_instance.finder.call_args[1]["query_params"]
        assert call_params["pageToken"] == "resume-token-abc"

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_success(self, mock_restli_client):
        """Single weekly chunk yields the API's elements unchanged."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [
            {
                "impressions": 1000,
                "clicks": 50,
                "costInUsd": 25.50,
                "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}},
            }
        ]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        # Date range fits within a single weekly chunk → exactly one finder call.
        pages = list(
            client.get_analytics(
                account_id=self.account_id,
                pivot=LinkedinAdsPivot.CAMPAIGN,
                date_start="2024-01-01",
                date_end="2024-01-05",
            )
        )

        assert len(pages) == 1
        elements, next_page_token = pages[0]
        assert next_page_token is None
        assert len(elements) == 1
        assert elements[0]["impressions"] == 1000
        assert elements[0]["clicks"] == 50
        assert elements[0]["costInUsd"] == 25.50
        assert mock_client_instance.finder.call_count == 1

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_chunks_long_date_range_weekly(self, mock_restli_client):
        """Date ranges longer than a week are sliced into weekly chunks (LinkedIn caps
        analytics responses at 15k records, so we have to slice rather than paginate).
        Each chunk produces its own finder call, yielding one tuple per chunk."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"impressions": 100}]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        # 22-day range → ceil(22/7) = 4 weekly chunks (Jan 1–7, 8–14, 15–21, 22).
        pages = list(
            client.get_analytics(
                account_id=self.account_id,
                pivot=LinkedinAdsPivot.CREATIVE,
                date_start="2024-01-01",
                date_end="2024-01-22",
            )
        )

        assert len(pages) == 4
        assert mock_client_instance.finder.call_count == 4
        # Each call should pass a dateRange that doesn't exceed 7 days.
        for call_args in mock_client_instance.finder.call_args_list:
            params = call_args[1]["query_params"]
            assert params["pivot"] == LinkedinAdsPivot.CREATIVE.value
            assert "dateRange" in params

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_get_analytics_logs_warning_when_chunk_hits_response_cap(self, mock_restli_client, caplog):
        """When a chunk response is exactly the 15k cap we log a warning so we can
        revisit chunk size — the chunk is still yielded (partial data > no data)."""
        from posthog.temporal.data_imports.sources.linkedin_ads.client import ANALYTICS_RESPONSE_CAP

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.elements = [{"impressions": i} for i in range(ANALYTICS_RESPONSE_CAP)]

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)
        with caplog.at_level("WARNING", logger="posthog.temporal.data_imports.sources.linkedin_ads.client"):
            pages = list(
                client.get_analytics(
                    account_id=self.account_id,
                    pivot=LinkedinAdsPivot.CREATIVE,
                    date_start="2024-01-01",
                    date_end="2024-01-05",
                )
            )

        assert len(pages) == 1
        assert any("analytics_chunk_capped" in record.message for record in caplog.records)

    def test_format_date_range(self):
        """Test date range formatting for LinkedIn API."""
        client = LinkedinAdsClient(self.access_token)
        result = client._format_date_range("2024-01-15", "2024-02-20")

        expected = {"start": {"year": 2024, "month": 1, "day": 15}, "end": {"year": 2024, "month": 2, "day": 20}}
        assert result == expected

    # Retry behavior: tenacity's exponential backoff sleeps are patched out to keep tests instant.

    @pytest.mark.parametrize(
        "transient_factory,expected_calls",
        [
            pytest.param(
                lambda: requests.exceptions.SSLError("UNEXPECTED_EOF_WHILE_READING"),
                3,
                id="ssl_error",
            ),
            pytest.param(
                lambda: requests.exceptions.ConnectionError("RemoteDisconnected"),
                3,
                id="connection_error",
            ),
            pytest.param(
                lambda: requests.exceptions.Timeout("read timed out"),
                3,
                id="timeout",
            ),
            pytest.param(
                lambda: _status_response(504, "Gateway Timeout"),
                2,
                id="http_504",
            ),
            pytest.param(
                lambda: _status_response(500, "Internal Server Error"),
                2,
                id="http_500",
            ),
            pytest.param(
                lambda: _status_response(429, "Too Many Requests"),
                2,
                id="http_429",
            ),
        ],
    )
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_transient_errors_are_retried_then_succeed(
        self, mock_restli_client, _mock_sleep, transient_factory, expected_calls
    ):
        mock_success = mock.MagicMock()
        mock_success.status_code = 200
        mock_success.elements = [{"id": "ok"}]

        transient_failures = [transient_factory() for _ in range(expected_calls - 1)]
        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = [*transient_failures, mock_success]

        client = LinkedinAdsClient(self.access_token)
        result = client.get_accounts()

        assert result == [{"id": "ok"}]
        assert mock_client_instance.finder.call_count == expected_calls

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_retries_exhausted_reraises_last_error(self, mock_restli_client, _mock_sleep):
        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.side_effect = requests.exceptions.ConnectionError("boom")

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(requests.exceptions.ConnectionError, match="boom"):
            client.get_accounts()

        assert mock_client_instance.finder.call_count == 5

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_no_retry_on_4xx(self, mock_restli_client, _mock_sleep):
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_response.response.text = "Unauthorized"

        mock_client_instance = mock_restli_client.return_value
        mock_client_instance.finder.return_value = mock_response

        client = LinkedinAdsClient(self.access_token)

        with pytest.raises(Exception, match="LinkedIn API error \\(401\\): Unauthorized"):
            client.get_accounts()

        assert mock_client_instance.finder.call_count == 1

    def test_retryable_error_is_exported(self):
        assert issubclass(LinkedinAdsRetryableError, Exception)


def _status_response(status_code: int, text: str) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.response.text = text
    return response
