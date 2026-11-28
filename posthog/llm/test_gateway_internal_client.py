from datetime import UTC, datetime

import pytest
from unittest.mock import patch

import httpx

from posthog.llm.gateway_internal_client import (
    ADMIN_ACTOR,
    IDEMPOTENCY_KEY_HEADER,
    INTERNAL_ACTOR_HEADER,
    USAGE_REPORT_TIMEOUT_SECONDS,
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    AIGatewayRouteNotFound,
    BillingUsageRow,
    add_credit,
    get_billing_usage,
    get_usage_report,
    get_usage_report_rows,
    get_wallet,
)

ORG_ID = "0190b3a1-1111-7000-8000-000000000001"
OTHER_ORG_ID = "0190b3a1-2222-7000-8000-000000000002"
DAY_START = datetime(2026, 11, 4, tzinfo=UTC)
DAY_END = datetime(2026, 11, 5, tzinfo=UTC)


def _response(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", "http://gw"))


def _configured(mock_settings) -> None:
    mock_settings.AI_GATEWAY_INTERNAL_URL = "http://gw"
    mock_settings.AI_GATEWAY_INTERNAL_TOKEN = "tok"


class TestGetWallet:
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_parses_known_team_with_ledger_and_recent(self, mock_settings):
        _configured(mock_settings)
        payload = {
            "team_id": 42,
            "known": True,
            "wallet": {"has_ledger": True, "balance": "9.500000"},
            "recent": [
                {
                    "when": "2026-06-01T00:00:00Z",
                    "kind": "topup",
                    "source": "funding",
                    "destination": "prepaid",
                    "amount": "10.000000",
                    "reference": "admin-topup:42:abc",
                }
            ],
        }
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(200, payload)) as mock_get:
            wallet = get_wallet(42)

        url = mock_get.call_args.args[0]
        assert url == "http://gw/internal/admin/api/teams/42"
        assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert wallet.team_id == 42
        assert wallet.known is True
        assert wallet.has_ledger is True
        assert wallet.balance == "9.500000"
        assert len(wallet.recent) == 1
        assert wallet.recent[0].kind == "topup"
        assert wallet.recent[0].amount == "10.000000"

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_no_ledger_backend(self, mock_settings):
        _configured(mock_settings)
        payload = {"team_id": 42, "known": False, "wallet": {"has_ledger": False}}
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(200, payload)):
            wallet = get_wallet(42)
        assert wallet.has_ledger is False
        assert wallet.balance is None
        assert wallet.recent == []

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_unknown_team(self, mock_settings):
        _configured(mock_settings)
        payload = {"team_id": 42, "known": False, "wallet": {"has_ledger": True}}
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(200, payload)):
            wallet = get_wallet(42)
        assert wallet.has_ledger is True
        assert wallet.known is False
        assert wallet.balance is None

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_http_error(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(500)):
            with pytest.raises(AIGatewayInternalError, match="wallet read failed"):
                get_wallet(42)

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_non_json_success_body(self, mock_settings):
        _configured(mock_settings)
        non_json = httpx.Response(200, text="<html>not json</html>", request=httpx.Request("GET", "http://gw"))
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=non_json):
            with pytest.raises(AIGatewayInternalError, match="wallet read failed"):
                get_wallet(42)


class TestAddCredit:
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_posts_body_and_idempotency_header(self, mock_settings):
        _configured(mock_settings)
        payload = {
            "team_id": 42,
            "entry_id": "entry-1",
            "amount_usd": "25.000000",
            "balance_usd": "35.000000",
            "duplicate": False,
        }
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, payload)) as mock_post:
            result = add_credit(42, ORG_ID, "25.00", "topping up", "key-123")

        url = mock_post.call_args.args[0]
        assert url == f"http://gw/internal/accounts/{ORG_ID}/credits"
        assert mock_post.call_args.kwargs["json"] == {"amount_usd": "25.00", "reason": "topping up"}
        assert mock_post.call_args.kwargs["headers"][IDEMPOTENCY_KEY_HEADER] == "key-123"
        assert mock_post.call_args.kwargs["headers"][INTERNAL_ACTOR_HEADER] == ADMIN_ACTOR
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert result.entry_id == "entry-1"
        assert result.balance_usd == "35.000000"
        assert result.duplicate is False

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_duplicate_replay(self, mock_settings):
        _configured(mock_settings)
        payload = {"team_id": 42, "entry_id": "entry-1", "amount_usd": "25", "balance_usd": "35", "duplicate": True}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, payload)):
            result = add_credit(42, ORG_ID, "25", "again", "key-123")
        assert result.duplicate is True

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_with_error_detail_on_4xx(self, mock_settings):
        _configured(mock_settings)
        body = {"error": "amount_usd: must be positive"}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(400, body)):
            with pytest.raises(AIGatewayInternalError, match="amount_usd: must be positive"):
                add_credit(42, ORG_ID, "-1", "bad", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_non_json_success_body(self, mock_settings):
        _configured(mock_settings)
        non_json = httpx.Response(200, text="<html>not json</html>", request=httpx.Request("POST", "http://gw"))
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=non_json):
            with pytest.raises(AIGatewayInternalError, match="not valid JSON"):
                add_credit(42, ORG_ID, "10", "x", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_success_body_missing_required_fields(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, {"team_id": 42})):
            with pytest.raises(AIGatewayInternalError, match="missing required fields"):
                add_credit(42, ORG_ID, "10", "x", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_accepts_zero_balance(self, mock_settings):
        _configured(mock_settings)
        body = {"team_id": 42, "entry_id": "e1", "amount_usd": "10", "balance_usd": "0", "duplicate": False}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, body)):
            result = add_credit(42, ORG_ID, "10", "x", "key-123")
        assert result.balance_usd == "0"


class TestGetUsageReport:
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_parses_a_page_and_uses_the_report_timeout(self, mock_settings):
        _configured(mock_settings)
        payload = {"rows": [{"keys": {"obo": "1"}}], "truncated": False}
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(200, payload)) as mock_get:
            page = get_usage_report({"group_by": "obo"})

        assert page.rows == [{"keys": {"obo": "1"}}]
        assert page.truncated is False
        assert page.next_cursor is None
        assert mock_get.call_args.kwargs["timeout"] == USAGE_REPORT_TIMEOUT_SECONDS

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_follows_the_cursor_to_the_last_page(self, mock_settings):
        _configured(mock_settings)
        first = _response(200, {"rows": [{"keys": {"obo": "1"}}], "truncated": True, "next_cursor": "c1"})
        second = _response(200, {"rows": [{"keys": {"obo": "2"}}], "truncated": False})
        with patch("posthog.llm.gateway_internal_client.httpx.get", side_effect=[first, second]) as mock_get:
            rows = get_usage_report_rows({"group_by": "obo", "team_id": "2"})

        assert [row["keys"]["obo"] for row in rows] == ["1", "2"]
        first_params = mock_get.call_args_list[0].kwargs["params"]
        second_params = mock_get.call_args_list[1].kwargs["params"]
        assert first_params["order_by"] == "key"
        assert "cursor" not in first_params
        assert second_params["order_by"] == "key"
        assert second_params["cursor"] == "c1"
        assert second_params["team_id"] == "2"

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_when_truncated_without_a_cursor(self, mock_settings):
        _configured(mock_settings)
        payload = {"rows": [], "truncated": True}
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(200, payload)):
            with pytest.raises(AIGatewayInternalError, match="truncated but returned no cursor"):
                get_usage_report_rows({"group_by": "obo"})

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_a_repeated_cursor(self, mock_settings):
        _configured(mock_settings)
        page = _response(200, {"rows": [], "truncated": True, "next_cursor": "c1"})
        with patch("posthog.llm.gateway_internal_client.httpx.get", side_effect=[page, page]):
            with pytest.raises(AIGatewayInternalError, match="repeated cursor"):
                get_usage_report_rows({"group_by": "obo"})

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_when_the_gateway_rejects_the_page_params(self, mock_settings):
        _configured(mock_settings)
        body = {"error": 'unknown query parameter "order_by"'}
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(400, body)):
            with pytest.raises(AIGatewayInternalError, match="unknown query parameter"):
                get_usage_report_rows({"group_by": "obo"})

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_without_a_truncated_flag(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.get", return_value=_response(200, {"rows": []})):
            with pytest.raises(AIGatewayInternalError, match="no truncated flag"):
                get_usage_report({"group_by": "obo"})


def _usage_row(org_id: str = ORG_ID, product: str = "posthog_ai", **amounts: object) -> dict:
    return {
        "org_id": org_id,
        "product": product,
        "interval_start": "2026-11-04T00:00:00Z",
        "credit_paid_micros": 12_000_000,
        "overage_micros": 0,
        "free_micros": 500,
        **amounts,
    }


def _usage_page(rows: list[dict], final_through: str = "2026-11-05T00:10:00Z", next_cursor: str | None = None) -> dict:
    return {
        "interval": "day",
        "from": "2026-11-04T00:00:00Z",
        "to": "2026-11-05T00:00:00Z",
        "final_through": final_through,
        "usage": rows,
        "next_cursor": next_cursor,
    }


class TestGetBillingUsage:
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_follows_the_cursor_and_returns_every_row_with_final_through(self, mock_settings):
        _configured(mock_settings)
        first = _response(200, _usage_page([_usage_row()], next_cursor="c1"))
        second = _response(200, _usage_page([_usage_row(OTHER_ORG_ID, "replay_vision", overage_micros=7)]))
        with patch("posthog.llm.gateway_internal_client.httpx.get", side_effect=[first, second]) as mock_get:
            usage = get_billing_usage(
                interval="day", start=DAY_START, end=DAY_END, org_ids=[ORG_ID, OTHER_ORG_ID], limit=1
            )

        assert usage.final_through == datetime(2026, 11, 5, 0, 10, tzinfo=UTC)
        assert usage.rows == [
            BillingUsageRow(
                org_id=ORG_ID,
                product="posthog_ai",
                interval_start=DAY_START,
                credit_paid_micros=12_000_000,
                overage_micros=0,
                free_micros=500,
            ),
            BillingUsageRow(
                org_id=OTHER_ORG_ID,
                product="replay_vision",
                interval_start=DAY_START,
                credit_paid_micros=12_000_000,
                overage_micros=7,
                free_micros=500,
            ),
        ]
        assert mock_get.call_args_list[0].args[0] == "http://gw/internal/billing/v1/usage"
        assert mock_get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer tok"
        expected_params = {
            "interval": "day",
            "from": "2026-11-04T00:00:00Z",
            "to": "2026-11-05T00:00:00Z",
            "org_id": [ORG_ID, OTHER_ORG_ID],
            "limit": "1",
        }
        assert mock_get.call_args_list[0].kwargs["params"] == expected_params
        assert mock_get.call_args_list[1].kwargs["params"] == {**expected_params, "cursor": "c1"}

    @pytest.mark.parametrize(
        "responses,error,match",
        [
            (
                [
                    _response(200, _usage_page([_usage_row()], next_cursor="c1")),
                    _response(200, _usage_page([], final_through="2026-11-05T00:20:00Z")),
                ],
                AIGatewayInternalError,
                "different final_through",
            ),
            (
                [
                    _response(200, _usage_page([], next_cursor="c1")),
                    _response(200, _usage_page([], next_cursor="c1")),
                ],
                AIGatewayInternalError,
                "repeated cursor",
            ),
            ([_response(404, {"error": "not found"})], AIGatewayRouteNotFound, "HTTP 404"),
            ([_response(503, {"error": "ledger unavailable"})], AIGatewayInternalError, "ledger unavailable"),
            ([httpx.ReadTimeout("timed out")], AIGatewayInternalError, "ReadTimeout"),
            ([_response(200, _usage_page([_usage_row(free_micros=None)]))], AIGatewayInternalError, "free_micros"),
            ([_response(200, _usage_page([_usage_row(overage_micros=-1)]))], AIGatewayInternalError, "overage_micros"),
            ([_response(200, _usage_page([_usage_row(org_id="team-2")]))], AIGatewayInternalError, "org_id"),
            ([_response(200, {"usage": [], "next_cursor": None})], AIGatewayInternalError, "final_through"),
        ],
        ids=[
            "final_through_changes_between_pages",
            "repeated_cursor",
            "route_not_found",
            "server_error",
            "timeout",
            "missing_amount",
            "negative_amount",
            "org_id_not_a_uuid",
            "no_final_through",
        ],
    )
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_fails_the_whole_read(self, mock_settings, responses, error, match):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.get", side_effect=responses):
            with pytest.raises(error, match=match):
                get_billing_usage(interval="day", start=DAY_START, end=DAY_END)


class TestNotConfigured:
    @pytest.mark.parametrize("url,token", [("", "tok"), ("http://gw", ""), ("", "")])
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_get_wallet_raises_when_unconfigured(self, mock_settings, url, token):
        mock_settings.AI_GATEWAY_INTERNAL_URL = url
        mock_settings.AI_GATEWAY_INTERNAL_TOKEN = token
        with pytest.raises(AIGatewayNotConfigured):
            get_wallet(42)

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_add_credit_raises_when_unconfigured(self, mock_settings):
        mock_settings.AI_GATEWAY_INTERNAL_URL = ""
        mock_settings.AI_GATEWAY_INTERNAL_TOKEN = ""
        with pytest.raises(AIGatewayNotConfigured):
            add_credit(42, ORG_ID, "10", "x", "key")
