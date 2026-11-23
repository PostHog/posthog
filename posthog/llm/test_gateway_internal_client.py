import json

import pytest
from unittest.mock import patch

import httpx

from posthog.llm.gateway_internal_client import (
    ADMIN_ACTOR,
    BILLING_ACTOR,
    IDEMPOTENCY_KEY_HEADER,
    INTERNAL_ACTOR_HEADER,
    USAGE_REPORT_TIMEOUT_SECONDS,
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    AIGatewayRequestRejected,
    MalformedSignedMessage,
    add_credit,
    get_usage_report,
    get_usage_report_rows,
    get_wallet,
    post_signed_message,
    read_signed_message,
)

ORG_ID = "0190b3a1-1111-7000-8000-000000000001"


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


def _body(message_type: str = "ai_funding_added", **fields: object) -> str:
    # Spaced unlike json.dumps, so a relay that serializes the body again changes it.
    return (
        "{"
        + ",  ".join(
            f"{json.dumps(key)}:  {json.dumps(value)}"
            for key, value in {"type": message_type, "version": 1, "organization_id": ORG_ID, **fields}.items()
        )
        + "}"
    )


def _envelope(**fields: object) -> dict:
    return {
        "body": _body(),
        "signed_at": "2026-11-23T18:04:05Z",
        "key_id": "billing-us-1",
        "signature": "5f0c1e",
        **fields,
    }


class TestReadSignedMessage:
    def test_reads_the_type_and_organization_and_keeps_the_envelope(self):
        envelope = _envelope()

        message = read_signed_message(envelope)

        assert (message.type, message.organization_id) == ("ai_funding_added", ORG_ID)
        assert message.envelope is envelope

    @pytest.mark.parametrize(
        "envelope",
        [
            pytest.param(None, id="no_envelope"),
            pytest.param({k: v for k, v in _envelope().items() if k != "signature"}, id="missing_signature"),
            pytest.param(_envelope(signed_at=1795543445), id="signed_at_not_a_string"),
            pytest.param(_envelope(body="not json"), id="body_not_json"),
            pytest.param(_envelope(body="[]"), id="body_not_an_object"),
            pytest.param(_envelope(body=json.dumps({"organization_id": ORG_ID})), id="no_type"),
            pytest.param(_envelope(body=json.dumps({"type": "ai_funding_added"})), id="no_organization"),
            pytest.param(
                _envelope(body=json.dumps({"type": "ai_funding_added", "organization_id": "../../admin"})),
                id="organization_not_a_uuid",
            ),
        ],
    )
    def test_an_envelope_that_cannot_be_routed_is_malformed(self, envelope):
        with pytest.raises(MalformedSignedMessage):
            read_signed_message(envelope)


class TestPostSignedMessage:
    @pytest.mark.parametrize(
        "message_type, path",
        [
            ("ai_funding_added", f"/internal/accounts/{ORG_ID}/credits"),
            ("ai_funding_reversed", f"/internal/accounts/{ORG_ID}/credits/reversal"),
            ("ai_reload_outcome", f"/internal/accounts/{ORG_ID}/reload-outcome"),
        ],
    )
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_posts_the_envelope_unchanged_to_the_route_for_its_type(self, mock_settings, message_type, path):
        _configured(mock_settings)
        envelope = _envelope(body=_body(message_type))
        answer = {"entry_id": "entry-1", "duplicate": False}
        with patch("posthog.llm.gateway_internal_client.httpx.post", return_value=_response(200, answer)) as mock_post:
            result = post_signed_message(read_signed_message(envelope))

        assert mock_post.call_args.args[0] == f"http://gw{path}"
        assert mock_post.call_args.kwargs["json"] == envelope
        assert mock_post.call_args.kwargs["headers"] == {
            "Authorization": "Bearer tok",
            INTERNAL_ACTOR_HEADER: BILLING_ACTOR,
        }
        assert mock_post.call_args.kwargs["trust_env"] is False
        assert result == answer

    @pytest.mark.parametrize(
        "answer, rejected",
        [
            pytest.param(_response(400), True, id="bad_body"),
            pytest.param(_response(409), True, id="operation_with_another_amount"),
            pytest.param(_response(204), False, id="no_content"),
            pytest.param(_response(401), False, id="unknown_key"),
            pytest.param(_response(429), False, id="rate_limited"),
            pytest.param(_response(503), False, id="unavailable"),
            pytest.param(httpx.ConnectError("refused"), False, id="no_answer"),
        ],
    )
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_only_a_200_delivers_and_only_400_or_409_is_rejected(self, mock_settings, answer, rejected):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.post", side_effect=[answer]):
            with pytest.raises(AIGatewayInternalError) as excinfo:
                post_signed_message(read_signed_message(_envelope()))

        assert isinstance(excinfo.value, AIGatewayRequestRejected) is rejected

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_a_type_that_no_route_takes_is_malformed_and_never_sent(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.post") as mock_post:
            with pytest.raises(MalformedSignedMessage):
                post_signed_message(read_signed_message(_envelope(body=_body("ai_reload_requested"))))

        mock_post.assert_not_called()
