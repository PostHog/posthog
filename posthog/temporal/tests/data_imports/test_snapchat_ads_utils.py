from datetime import date, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import Mock

from parameterized import parameterized
from requests.exceptions import HTTPError, Timeout

from posthog.temporal.data_imports.sources.snapchat_ads.settings import EndpointType
from posthog.temporal.data_imports.sources.snapchat_ads.utils import (
    SNAPCHAT_DATE_FORMAT,
    SnapchatAdsAPIError,
    SnapchatAdsPaginator,
    SnapchatDateRangeManager,
    SnapchatErrorHandler,
    SnapchatStatsResource,
)

FROZEN_TIME = "2024-06-15T12:00:00"
FROZEN_DATETIME = datetime(2024, 6, 15, 12, 0, 0)
FROZEN_DATE = date(2024, 6, 15)


class TestSnapchatErrorHandler:
    @parameterized.expand(
        [
            ("snapchat_api_error", SnapchatAdsAPIError("error"), True),
            ("timeout", Timeout("timeout"), True),
            ("http_429", 429, True),
            ("http_500", 500, True),
            ("http_400", 400, False),
            ("http_401", 401, False),
        ]
    )
    def test_is_retryable(self, name, error_or_status, expected):
        if isinstance(error_or_status, int):
            mock_response = Mock()
            mock_response.status_code = error_or_status
            error = HTTPError(response=mock_response)
        else:
            error = error_or_status

        assert SnapchatErrorHandler.is_retryable(error) == expected


@freeze_time(FROZEN_TIME)
class TestSnapchatDateRangeManager:
    @parameterized.expand(
        [
            ("no_incremental", False, None, 365),
            ("incremental_datetime", True, FROZEN_DATETIME - timedelta(days=10), 10),
            ("incremental_date", True, FROZEN_DATE - timedelta(days=5), 5),
            ("incremental_string", True, (FROZEN_DATETIME - timedelta(days=7)).strftime("%Y-%m-%d"), 7),
            ("invalid_string_fallback", True, "invalid", 365),
        ]
    )
    def test_get_incremental_range(self, name, should_use_incremental, last_value, expected_max_days):
        start_date, end_date = SnapchatDateRangeManager.get_incremental_range(should_use_incremental, last_value)

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)

        assert end_dt.date() == (FROZEN_DATETIME + timedelta(days=1)).date()
        assert (end_dt - start_dt).days <= expected_max_days + 2
        assert start_date.endswith("T00:00:00")

    @parameterized.expand(
        [
            ("short_range", 20, 31, 1),
            ("exact", 31, 31, 1),
            ("one_more", 32, 31, 2),
            ("two_chunks", 60, 31, 2),
            ("three_chunks", 90, 31, 3),
        ]
    )
    def test_generate_chunks(self, name, days_back, chunk_days, expected_chunks):
        start = (FROZEN_DATETIME - timedelta(days=days_back)).strftime(SNAPCHAT_DATE_FORMAT)
        end = FROZEN_DATETIME.strftime(SNAPCHAT_DATE_FORMAT)

        chunks = SnapchatDateRangeManager.generate_chunks(start, end, chunk_days)

        assert len(chunks) == expected_chunks
        assert chunks[0][0] == start


class TestSnapchatStatsResourceTransforms:
    def test_transform_stats_reports_flattens_breakdown_structure(self):
        reports = [
            {
                "timeseries_stat": {
                    "id": "account_123",
                    "type": "AD_ACCOUNT",
                    "breakdown_stats": {
                        "campaign": [
                            {
                                "id": "campaign_123",
                                "type": "CAMPAIGN",
                                "timeseries": [
                                    {
                                        "start_time": "2024-01-01T00:00:00.000Z",
                                        "end_time": "2024-01-02T00:00:00.000Z",
                                        "stats": {"impressions": 1234, "swipes": 56},
                                    },
                                    {
                                        "start_time": "2024-01-02T00:00:00.000Z",
                                        "end_time": "2024-01-03T00:00:00.000Z",
                                        "stats": {"impressions": 2000, "swipes": 80},
                                    },
                                ],
                            }
                        ]
                    },
                }
            }
        ]

        result = SnapchatStatsResource.transform_stats_reports(reports)

        assert len(result) == 2
        assert result[0]["id"] == "campaign_123"
        assert result[0]["type"] == "CAMPAIGN"
        assert result[0]["impressions"] == 1234
        assert result[1]["impressions"] == 2000

    def test_transform_stats_reports_handles_multiple_entities_in_breakdown(self):
        reports = [
            {
                "timeseries_stat": {
                    "id": "account_123",
                    "type": "AD_ACCOUNT",
                    "breakdown_stats": {
                        "campaign": [
                            {
                                "id": "campaign_1",
                                "type": "CAMPAIGN",
                                "timeseries": [
                                    {
                                        "start_time": "2024-01-01T00:00:00.000Z",
                                        "end_time": "2024-01-02T00:00:00.000Z",
                                        "stats": {"impressions": 100},
                                    },
                                ],
                            },
                            {
                                "id": "campaign_2",
                                "type": "CAMPAIGN",
                                "timeseries": [
                                    {
                                        "start_time": "2024-01-01T00:00:00.000Z",
                                        "end_time": "2024-01-02T00:00:00.000Z",
                                        "stats": {"impressions": 200},
                                    },
                                ],
                            },
                        ]
                    },
                }
            }
        ]

        result = SnapchatStatsResource.transform_stats_reports(reports)

        assert len(result) == 2
        assert result[0]["id"] == "campaign_1"
        assert result[0]["impressions"] == 100
        assert result[1]["id"] == "campaign_2"
        assert result[1]["impressions"] == 200

    def test_transform_stats_reports_handles_non_breakdown_fallback(self):
        reports = [
            {
                "timeseries_stat": {
                    "id": "campaign_123",
                    "type": "CAMPAIGN",
                    "timeseries": [
                        {
                            "start_time": "2024-01-01T00:00:00",
                            "end_time": "2024-01-01T23:59:59",
                            "stats": {"impressions": 1234, "swipes": 56},
                        },
                    ],
                }
            }
        ]

        result = SnapchatStatsResource.transform_stats_reports(reports)

        assert len(result) == 1
        assert result[0]["id"] == "campaign_123"
        assert result[0]["impressions"] == 1234

    def test_transform_entity_reports_unwraps_entities(self):
        reports = [
            {"campaign": {"id": "1", "name": "Campaign"}},
            {"adsquad": {"id": "2", "name": "Ad Squad"}},
            {"ad": {"id": "3", "name": "Ad"}},
        ]

        result = SnapchatStatsResource.transform_entity_reports(reports)

        assert len(result) == 3
        assert result[0]["name"] == "Campaign"
        assert result[1]["name"] == "Ad Squad"
        assert result[2]["name"] == "Ad"

    @parameterized.expand(
        [
            ("stats", EndpointType.STATS),
            ("entity", EndpointType.ENTITY),
            ("account", EndpointType.ACCOUNT),
        ]
    )
    def test_apply_stream_transformations_routes_correctly(self, name, endpoint_type):
        reports: list[dict[str, Any]]
        if endpoint_type == EndpointType.STATS:
            reports = [
                {
                    "timeseries_stat": {
                        "id": "account_1",
                        "type": "AD_ACCOUNT",
                        "breakdown_stats": {"campaign": []},
                    }
                }
            ]
        elif endpoint_type == EndpointType.ENTITY:
            reports = [{"campaign": {"id": "1"}}]
        else:
            reports = [{"id": "1"}]

        result = SnapchatStatsResource.apply_stream_transformations(endpoint_type, reports)
        assert isinstance(result, list)


class TestSnapchatAdsPaginator:
    def _create_mock_response(self, data: dict[Any, Any], status_code: int = 200) -> Mock:
        mock = Mock()
        mock.status_code = status_code
        mock.json.return_value = data
        return mock

    def test_updates_state_with_next_link(self):
        paginator = SnapchatAdsPaginator()
        response = self._create_mock_response(
            {
                "request_status": "SUCCESS",
                "paging": {"next_link": "https://api.snapchat.com?cursor=abc123"},
            }
        )

        paginator.update_state(response)

        assert paginator.has_next_page is True
        assert paginator._next_link == "https://api.snapchat.com?cursor=abc123"

    def test_extracts_cursor_for_next_request(self):
        paginator = SnapchatAdsPaginator()
        paginator._next_link = "https://api.snapchat.com?cursor=abc123&limit=100"

        mock_request = Mock()
        mock_request.params = {}

        paginator.update_request(mock_request)

        assert mock_request.params["cursor"] == "abc123"

    def test_raises_retryable_error_on_rate_limit(self):
        paginator = SnapchatAdsPaginator()
        response = self._create_mock_response(
            {"request_status": "ERROR", "debug_message": "Rate limited"},
            status_code=429,
        )

        with pytest.raises(SnapchatAdsAPIError):
            paginator.update_state(response)

    def test_raises_value_error_on_client_error(self):
        paginator = SnapchatAdsPaginator()
        response = self._create_mock_response(
            {"request_status": "ERROR", "debug_message": "Bad request"},
            status_code=400,
        )

        with pytest.raises(ValueError, match="non-retryable"):
            paginator.update_state(response)
