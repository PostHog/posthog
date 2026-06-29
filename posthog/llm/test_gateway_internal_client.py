import pytest
from unittest.mock import patch

import httpx

from posthog.llm.gateway_internal_client import (
    IDEMPOTENCY_KEY_HEADER,
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    add_credit,
    get_wallet,
)


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
            result = add_credit(42, "25.00", "topping up", "key-123")

        url = mock_post.call_args.args[0]
        assert url == "http://gw/internal/teams/42/credits"
        assert mock_post.call_args.kwargs["json"] == {"amount_usd": "25.00", "reason": "topping up"}
        assert mock_post.call_args.kwargs["headers"][IDEMPOTENCY_KEY_HEADER] == "key-123"
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert result.entry_id == "entry-1"
        assert result.balance_usd == "35.000000"
        assert result.duplicate is False

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_duplicate_replay(self, mock_settings):
        _configured(mock_settings)
        payload = {"team_id": 42, "entry_id": "entry-1", "amount_usd": "25", "balance_usd": "35", "duplicate": True}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, payload)):
            result = add_credit(42, "25", "again", "key-123")
        assert result.duplicate is True

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_with_error_detail_on_4xx(self, mock_settings):
        _configured(mock_settings)
        body = {"error": "amount_usd: must be positive"}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(400, body)):
            with pytest.raises(AIGatewayInternalError, match="amount_usd: must be positive"):
                add_credit(42, "-1", "bad", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_non_json_success_body(self, mock_settings):
        _configured(mock_settings)
        non_json = httpx.Response(200, text="<html>not json</html>", request=httpx.Request("POST", "http://gw"))
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=non_json):
            with pytest.raises(AIGatewayInternalError, match="not valid JSON"):
                add_credit(42, "10", "x", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_success_body_missing_required_fields(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, {"team_id": 42})):
            with pytest.raises(AIGatewayInternalError, match="missing required fields"):
                add_credit(42, "10", "x", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_accepts_zero_balance(self, mock_settings):
        _configured(mock_settings)
        body = {"team_id": 42, "entry_id": "e1", "amount_usd": "10", "balance_usd": "0", "duplicate": False}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, body)):
            result = add_credit(42, "10", "x", "key-123")
        assert result.balance_usd == "0"


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
            add_credit(42, "10", "x", "key")
