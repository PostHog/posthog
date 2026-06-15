from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.cloudflare.cloudflare import (
    PAGE_SIZE,
    cloudflare_source,
    get_rows,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.cloudflare.settings import CLOUDFLARE_ENDPOINTS, ENDPOINTS

_MODULE = "posthog.temporal.data_imports.sources.cloudflare.cloudflare"


def _response(result: list[dict[str, Any]], total_pages: int | None = None, success: bool = True) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"success": success, "result": result}
    if total_pages is not None:
        body["result_info"] = {"total_pages": total_pages}
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_on_verify_success(self, mock_session):
        mock_session.return_value.get.return_value = _response([], success=True)
        assert validate_credentials("token") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_success_false(self, mock_session):
        mock_session.return_value.get.return_value = _response([], success=False)
        assert validate_credentials("token") is False

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_error_status(self, mock_session, status_code):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response
        assert validate_credentials("token") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_zones_paginate_via_total_pages(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "z1"}], total_pages=2),
            _response([{"id": "z2"}], total_pages=2),
        ]

        batches = list(get_rows("token", "zones", mock.MagicMock()))

        assert [item["id"] for batch in batches for item in batch] == ["z1", "z2"]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert parse_qs(urlparse(urls[0]).query)["page"] == ["1"]
        assert parse_qs(urlparse(urls[1]).query)["page"] == ["2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_missing_result_info_falls_back_to_short_page(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "a1"}])

        batches = list(get_rows("token", "accounts", mock.MagicMock()))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_dns_records_fan_out_over_zones_and_inject_zone_id(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "z1"}, {"id": "z2"}], total_pages=1),
            _response([{"id": "r1"}], total_pages=1),
            _response([{"id": "r2"}], total_pages=1),
        ]

        batches = list(get_rows("token", "dns_records", mock.MagicMock()))

        flat = [item for batch in batches for item in batch]
        assert [(r["id"], r["_zone_id"]) for r in flat] == [("r1", "z1"), ("r2", "z2")]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urlparse(urls[1]).path == "/client/v4/zones/z1/dns_records"
        assert urlparse(urls[2]).path == "/client/v4/zones/z2/dns_records"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_page_without_result_info_continues(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response(full_page),
            _response([{"id": "tail"}]),
        ]

        batches = list(get_rows("token", "accounts", mock.MagicMock()))

        assert len(batches) == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response([], total_pages=0)

        assert list(get_rows("token", "zones", mock.MagicMock())) == []


class TestCloudflareSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CLOUDFLARE_ENDPOINTS[endpoint]
        response = cloudflare_source("token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
