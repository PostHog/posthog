import pytest
from unittest.mock import patch

import httpx

from posthog.llm.gateway_internal_client import (
    ADMIN_ACTOR,
    BILLING_ACTOR,
    IDEMPOTENCY_KEY_HEADER,
    INTERNAL_ACTOR_HEADER,
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    AIGatewayRequestRejected,
    add_credit,
    get_wallet,
    grant_org_credit,
    reverse_org_credit,
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


ORG_ID = "0190b3a1-1111-7000-8000-000000000001"
ORG_LEDGER_RESPONSE = {
    "org_id": ORG_ID,
    "entry_id": "entry-1",
    "amount_usd": "20.00",
    "balance_usd": "118.40",
    "duplicate": False,
}


class TestOrgLedger:
    @pytest.mark.parametrize(
        "record, path",
        [
            (grant_org_credit, f"/internal/accounts/{ORG_ID}/credits"),
            (reverse_org_credit, f"/internal/accounts/{ORG_ID}/credits/reversal"),
        ],
    )
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_posts_to_the_org_route_as_billing(self, mock_settings, record, path):
        _configured(mock_settings)
        with patch(
            "posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, ORG_LEDGER_RESPONSE)
        ) as mock_post:
            result = record(ORG_ID, "20.00", "top_up", "ai_credit:in_1")

        assert mock_post.call_args.args[0] == f"http://gw{path}"
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tok"
        assert headers[IDEMPOTENCY_KEY_HEADER] == "ai_credit:in_1"
        assert headers[INTERNAL_ACTOR_HEADER] == BILLING_ACTOR
        assert mock_post.call_args.kwargs["json"] == {"amount_usd": "20.00", "reason": "top_up"}
        assert mock_post.call_args.kwargs["trust_env"] is False
        assert (result.org_id, result.entry_id, result.balance_usd, result.duplicate) == (
            ORG_ID,
            "entry-1",
            "118.40",
            False,
        )

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_a_4xx_is_rejected_with_its_status(self, mock_settings):
        _configured(mock_settings)
        conflict = _response(409, {"error": "amount_usd does not match the original entry for this Idempotency-Key"})
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=conflict):
            with pytest.raises(AIGatewayRequestRejected, match="does not match") as excinfo:
                grant_org_credit(ORG_ID, "25.00", "top_up", "ai_credit:in_1")

        assert excinfo.value.status_code == 409

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_a_5xx_is_an_internal_error_to_retry(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(503, {"error": "down"})):
            with pytest.raises(AIGatewayInternalError) as excinfo:
                grant_org_credit(ORG_ID, "20.00", "top_up", "ai_credit:in_1")

        assert not isinstance(excinfo.value, AIGatewayRequestRejected)
