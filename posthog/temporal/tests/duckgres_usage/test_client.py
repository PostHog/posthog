"""Tests for the duckgres billing pull API client.

The wire contract is duckgres PR #893 (`docs/design/billing-pull-api.md`):
`GET /api/v1/billing/usage` returns `{watermark_low, watermark_high, usage: [...]}`
with one row per (org, team, query_source, worker size) per UTC day, and
`POST /api/v1/billing/ack` advances the server-side cursor.
"""

import json
import datetime as dt
from decimal import Decimal

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.duckgres_usage.client import (
    DuckgresBillingAPIError,
    DuckgresBillingNotConfigured,
    ack_usage,
    fetch_usage,
    is_configured,
)

USAGE_URL = "https://duckgres.example.com/api/v1/billing/usage"
ACK_URL = "https://duckgres.example.com/api/v1/billing/ack"


def _response(status_code: int = 200, body: dict | None = None, raw_text: str | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = raw_text if raw_text is not None else json.dumps(body if body is not None else {})
    return response


USAGE_BODY = {
    "watermark_low": "2026-07-06T00:00:00Z",
    "watermark_high": "2026-07-07T12:39:00Z",
    "usage": [
        {
            "date": "2026-07-06",
            "org_id": "018f0000-0000-0000-0000-000000000000",
            "team_id": "42",
            "query_source": "standard",
            "cpu": 8,
            "mem_gib": 16,
            "cpu_seconds": 3600,
            "memory_seconds": 7200,
        },
        {
            "date": "2026-07-07",
            "org_id": "018f0000-0000-0000-0000-000000000000",
            "team_id": "42",
            "query_source": "endpoints",
            "cpu": 1.5,
            "mem_gib": 0.5,
            "cpu_seconds": 90,
            "memory_seconds": 30,
        },
    ],
    "storage": [
        {
            "date": "2026-07-06",
            "org_id": "018f0000-0000-0000-0000-000000000000",
            "team_id": 42,
            "gib_seconds": 360000,
        },
    ],
}


@pytest.fixture
def duckgres_configured(settings) -> None:
    settings.DUCKGRES_API_URL = "https://duckgres.example.com"
    settings.DUCKGRES_INTERNAL_SECRET = "shh"


@pytest.mark.usefixtures("duckgres_configured")
class TestFetchUsage:
    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_parses_rows_and_watermarks(self, mock_requests: MagicMock) -> None:
        mock_requests.request.return_value = _response(200, USAGE_BODY)

        result = fetch_usage()

        assert result.watermark_low == dt.datetime(2026, 7, 6, tzinfo=dt.UTC)
        assert result.watermark_high == dt.datetime(2026, 7, 7, 12, 39, tzinfo=dt.UTC)
        assert len(result.rows) == 2
        first = result.rows[0]
        assert first.date == dt.date(2026, 7, 6)
        assert first.org_id == "018f0000-0000-0000-0000-000000000000"
        assert first.team_id == 42
        assert first.query_source == "standard"
        assert first.cpu == Decimal("8")
        assert first.mem_gib == Decimal("16")
        assert first.cpu_seconds == 3600
        assert first.memory_seconds == 7200
        second = result.rows[1]
        assert second.query_source == "endpoints"
        assert second.cpu == Decimal("1.5")
        assert second.mem_gib == Decimal("0.5")

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_parses_storage_rows(self, mock_requests: MagicMock) -> None:
        mock_requests.request.return_value = _response(200, USAGE_BODY)

        result = fetch_usage()

        assert len(result.storage_rows) == 1
        row = result.storage_rows[0]
        assert row.date == dt.date(2026, 7, 6)
        assert row.org_id == "018f0000-0000-0000-0000-000000000000"
        assert row.team_id == 42  # storage serves team_id as a JSON number
        assert row.gib_seconds == Decimal("360000")

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_gib_seconds_survive_exactly_never_float(self, mock_requests: MagicMock) -> None:
        # duckgres serves exact-decimal GiB-seconds with up to ~27 fractional
        # digits (byte-seconds / 2^30). float64 keeps ~16 significant digits,
        # so a default json parse silently corrupts the value — proven against
        # the real server. The client must decimal-parse the raw body.
        raw = (
            '{"watermark_low": "2026-07-06T23:59:59Z", "watermark_high": "2026-07-08T12:00:00Z",'
            ' "usage": [],'
            ' "storage": [{"date": "2026-07-08", "org_id": "018f0000-0000-0000-0000-000000000000",'
            ' "team_id": 42, "gib_seconds": 8381903.171539306640625}]}'
        )
        mock_requests.request.return_value = _response(200, raw_text=raw)

        result = fetch_usage()

        assert result.storage_rows[0].gib_seconds == Decimal("8381903.171539306640625")

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_missing_storage_key_means_no_storage_rows(self, mock_requests: MagicMock) -> None:
        # Pre-#913 servers have no storage array; the client must not require it.
        body = {k: v for k, v in USAGE_BODY.items() if k != "storage"}
        mock_requests.request.return_value = _response(200, body)

        result = fetch_usage()

        assert result.storage_rows == []

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_sends_internal_secret_header_to_usage_url(self, mock_requests: MagicMock) -> None:
        mock_requests.request.return_value = _response(200, USAGE_BODY)

        fetch_usage()

        method, url = mock_requests.request.call_args.args[:2]
        assert method == "GET"
        assert url == USAGE_URL
        headers = mock_requests.request.call_args.kwargs["headers"]
        assert headers["X-Duckgres-Internal-Secret"] == "shh"

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_skips_rows_with_unparseable_team_id(self, mock_requests: MagicMock) -> None:
        body = {
            **USAGE_BODY,
            "usage": [{**USAGE_BODY["usage"][0], "team_id": "not-a-team"}, USAGE_BODY["usage"][1]],
        }
        mock_requests.request.return_value = _response(200, body)

        result = fetch_usage()

        assert len(result.rows) == 1
        assert result.rows[0].query_source == "endpoints"

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_empty_window_returns_no_rows(self, mock_requests: MagicMock) -> None:
        body = {
            "watermark_low": "2026-07-07T00:00:00Z",
            "watermark_high": "2026-07-07T00:00:00Z",
            "usage": [],
        }
        mock_requests.request.return_value = _response(200, body)

        result = fetch_usage()

        assert result.rows == []
        assert result.watermark_low == result.watermark_high

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_raises_on_http_error(self, mock_requests: MagicMock) -> None:
        mock_requests.request.return_value = _response(500, {"error": "boom"})

        with pytest.raises(DuckgresBillingAPIError):
            fetch_usage()


@pytest.mark.usefixtures("duckgres_configured")
class TestAckUsage:
    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_posts_watermark_as_rfc3339(self, mock_requests: MagicMock) -> None:
        mock_requests.request.return_value = _response(200, {"acked": True})

        ack_usage(dt.datetime(2026, 7, 7, tzinfo=dt.UTC))

        method, url = mock_requests.request.call_args.args[:2]
        assert method == "POST"
        assert url == ACK_URL
        assert mock_requests.request.call_args.kwargs["json"] == {"watermark_high": "2026-07-07T00:00:00Z"}
        headers = mock_requests.request.call_args.kwargs["headers"]
        assert headers["X-Duckgres-Internal-Secret"] == "shh"

    @patch("posthog.temporal.duckgres_usage.client.internal_requests")
    def test_raises_on_http_error(self, mock_requests: MagicMock) -> None:
        mock_requests.request.return_value = _response(400, {"error": "beyond latest closed bucket"})

        with pytest.raises(DuckgresBillingAPIError):
            ack_usage(dt.datetime(2026, 7, 7, tzinfo=dt.UTC))

    def test_rejects_naive_watermark(self) -> None:
        with pytest.raises(ValueError):
            ack_usage(dt.datetime(2026, 7, 7))  # noqa: DTZ001


class TestConfiguration:
    def test_not_configured_without_url(self, settings) -> None:
        settings.DUCKGRES_API_URL = None
        settings.DUCKGRES_INTERNAL_SECRET = None
        assert is_configured() is False
        with pytest.raises(DuckgresBillingNotConfigured):
            fetch_usage()
        with pytest.raises(DuckgresBillingNotConfigured):
            ack_usage(dt.datetime(2026, 7, 7, tzinfo=dt.UTC))

    def test_not_configured_without_secret(self, settings) -> None:
        # Unlike provisioning (which optionally omits the header), billing pulls
        # are admin-authed: a missing secret means every call would 401, so
        # treat it as unconfigured rather than hammering the control plane.
        settings.DUCKGRES_API_URL = "https://duckgres.example.com"
        settings.DUCKGRES_INTERNAL_SECRET = None
        assert is_configured() is False

    def test_configured_with_url_and_secret(self, settings) -> None:
        settings.DUCKGRES_API_URL = "https://duckgres.example.com"
        settings.DUCKGRES_INTERNAL_SECRET = "shh"
        assert is_configured() is True
