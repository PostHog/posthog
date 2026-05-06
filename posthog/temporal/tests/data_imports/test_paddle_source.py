from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.paddle.paddle import (
    PaddlePermissionError,
    PaddleResumeConfig,
    _format_paddle_datetime_query_value,
    get_rows,
    paddle_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.paddle.settings import ENDPOINTS
from posthog.temporal.data_imports.sources.paddle.source import PaddleSource

# We patch requests.Session.request to ensure NO real HTTP calls are made.
MOCK_PATH = "posthog.temporal.data_imports.sources.paddle.paddle.requests.Session.request"


class MockResponse:
    def __init__(self, json_data, status_code=200, headers=None):
        self.json_data = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from requests import Response
            from requests.exceptions import HTTPError

            raise HTTPError(f"HTTP Error {self.status_code}", response=Response())


def _get_mock_resumable_manager() -> ResumableSourceManager[PaddleResumeConfig]:
    mock_manager = MagicMock(spec=ResumableSourceManager)
    mock_manager.can_resume.return_value = False
    mock_manager.load_state.return_value = None
    return mock_manager


@patch(MOCK_PATH)
def test_get_rows_pagination(mock_request):
    page1 = {
        "data": [{"id": 1}],
        "meta": {"pagination": {"next": "https://api.paddle.com/customers?per_page=100&after=123"}},
    }
    page2 = {
        "data": [{"id": 2}],
        "meta": {"pagination": {"next": None}},
    }

    mock_request.side_effect = [MockResponse(page1), MockResponse(page2)]

    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    items = list(
        get_rows(
            api_key="fake",
            endpoint="customers",
            db_incremental_field_last_value=None,
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=False,
        )
    )

    assert mock_request.call_count == 2
    assert len(items) == 1
    table: pa.Table = items[0]

    assert table.num_rows == 2
    assert table.column("id").to_pylist() == [1, 2]


@patch(MOCK_PATH)
def test_get_rows_incremental(mock_request):
    mock_request.return_value = MockResponse({"data": [{"id": 1}], "meta": {"pagination": {"next": None}}})

    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    list(
        get_rows(
            api_key="fake",
            endpoint="transactions",
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=True,
        )
    )

    mock_request.assert_called_once()
    actual_params = mock_request.call_args[1]["params"]

    assert actual_params["billed_at[GT]"] == "2024-01-01T00:00:00Z"
    assert actual_params["order_by"] == "billed_at[ASC]"


@parameterized.expand(
    [
        ("utc_string", "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        ("offset_string", "2024-01-01T02:00:00+02:00", "2024-01-01T00:00:00Z"),
        ("naive_datetime", datetime(2024, 1, 1, 0, 0, 0), "2024-01-01T00:00:00Z"),
    ]
)
def test_format_paddle_datetime_query_value(_, value, expected):
    assert _format_paddle_datetime_query_value(value) == expected


@patch(MOCK_PATH)
def test_validate_credentials_success(mock_request):
    mock_request.return_value = MockResponse({"data": []}, status_code=200)
    assert validate_credentials("fake_key") is True
    assert mock_request.call_count == len(ENDPOINTS)


@patch(MOCK_PATH)
def test_validate_credentials_missing_permissions(mock_request):
    mock_request.return_value = MockResponse({"error": "forbidden"}, status_code=403)
    with pytest.raises(PaddlePermissionError):
        validate_credentials("fake_key")


@patch(MOCK_PATH)
@patch("posthog.temporal.data_imports.sources.paddle.paddle.get_dlt_mapping_for_external_table")
def test_paddle_source(mock_get_mapping, mock_request):
    mock_get_mapping.return_value = {"id": {"data_type": "text"}}
    logger = MagicMock()
    mock_manager = _get_mock_resumable_manager()

    response = paddle_source(
        api_key="fake",
        endpoint="products",
        db_incremental_field_last_value=None,
        should_use_incremental_field=False,
        logger=logger,
        resumable_source_manager=mock_manager,
    )

    assert response.name == "products"
    assert response.primary_keys == ["id"]
    assert response.column_hints == {"id": "text"}


@patch(MOCK_PATH)
def test_get_rows_resume(mock_request):
    mock_request.return_value = MockResponse({"data": [{"id": 3}], "meta": {"pagination": {"next": None}}})

    logger = MagicMock()
    mock_manager = MagicMock(spec=ResumableSourceManager)
    mock_manager.can_resume.return_value = True
    mock_manager.load_state.return_value = PaddleResumeConfig(next_url="https://api.paddle.com/customers?after=2")

    items = list(
        get_rows(
            api_key="fake",
            endpoint="customers",
            db_incremental_field_last_value=None,
            logger=logger,
            resumable_source_manager=mock_manager,
            should_use_incremental_field=False,
        )
    )

    assert mock_request.call_count == 1
    assert mock_request.call_args[0][1] == "https://api.paddle.com/customers?after=2"
    assert len(items) == 1
    assert items[0].column("id").to_pylist() == [3]


@patch(MOCK_PATH)
def test_paddle_request_fails_fast(mock_request):
    mock_request.return_value = MockResponse({"error": "rate_limited"}, status_code=429)

    from posthog.temporal.data_imports.sources.paddle.paddle import _get_paddle_session, paddle_request

    session = _get_paddle_session()

    response = paddle_request(
        session,
        "GET",
        "https://api.paddle.com/test",
        params={"per_page": 200},
    )

    assert mock_request.call_count == 1
    assert response.status_code == 429


@patch(MOCK_PATH)
def test_get_rows_stops_on_repeated_cursor(mock_request):
    repeated_url = "https://api.paddle.com/products?after=pro_1&order_by=id%5BASC%5D&per_page=200"
    mock_request.side_effect = [
        MockResponse(
            {
                "data": [{"id": "pro_1"}],
                "meta": {"pagination": {"next": repeated_url}},
            }
        ),
        MockResponse(
            {
                "data": [{"id": "pro_2"}],
                "meta": {"pagination": {"next": repeated_url}},
            }
        ),
    ]

    items = list(
        get_rows(
            api_key="fake",
            endpoint="products",
            db_incremental_field_last_value=None,
            logger=MagicMock(),
            resumable_source_manager=_get_mock_resumable_manager(),
            should_use_incremental_field=False,
        )
    )

    assert mock_request.call_count == 2
    assert len(items) == 1
    assert items[0].column("id").to_pylist() == ["pro_1", "pro_2"]


@parameterized.expand(
    [
        ("transactions", True),
        ("customers", False),
        ("discounts", False),
        ("prices", False),
        ("products", False),
        ("subscriptions", False),
        ("adjustments", False),
    ]
)
def test_get_schemas_incremental_flag(endpoint, expected_incremental):
    source = PaddleSource()
    schemas = {schema.name: schema for schema in source.get_schemas(config=MagicMock(), team_id=1)}
    assert schemas[endpoint].supports_incremental is expected_incremental
    assert schemas[endpoint].supports_append is expected_incremental
