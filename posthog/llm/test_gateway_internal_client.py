import pytest
from unittest.mock import patch

import httpx

from posthog.llm.gateway_internal_client import (
    ADMIN_ACTOR,
    IDEMPOTENCY_KEY_HEADER,
    INTERNAL_ACTOR_HEADER,
    USER_ACTOR,
    USER_SCOPE_TYPE,
    AIGatewayInternalError,
    AIGatewayNotConfigured,
    add_credit,
    clear_user_budget,
    get_user_budget,
    get_wallet,
    set_user_budget,
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
        with patch(
            "posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, payload)
        ) as mock_request:
            wallet = get_wallet(42)

        method, url = mock_request.call_args.args
        assert method == "GET"
        assert url == "http://gw/internal/admin/api/teams/42"
        assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
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
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, payload)):
            wallet = get_wallet(42)
        assert wallet.has_ledger is False
        assert wallet.balance is None
        assert wallet.recent == []

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_unknown_team(self, mock_settings):
        _configured(mock_settings)
        payload = {"team_id": 42, "known": False, "wallet": {"has_ledger": True}}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, payload)):
            wallet = get_wallet(42)
        assert wallet.has_ledger is True
        assert wallet.known is False
        assert wallet.balance is None

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_http_error(self, mock_settings):
        _configured(mock_settings)
        body = {"error": "team not found"}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(500, body)):
            with pytest.raises(AIGatewayInternalError, match="team not found"):
                get_wallet(42)

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_non_json_success_body(self, mock_settings):
        _configured(mock_settings)
        non_json = httpx.Response(200, text="<html>not json</html>", request=httpx.Request("GET", "http://gw"))
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=non_json):
            with pytest.raises(AIGatewayInternalError, match="not valid JSON"):
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
        with patch(
            "posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, payload)
        ) as mock_request:
            result = add_credit(42, "25.00", "topping up", "key-123")

        method, url = mock_request.call_args.args
        assert method == "POST"
        assert url == "http://gw/internal/teams/42/credits"
        assert mock_request.call_args.kwargs["json"] == {"amount_usd": "25.00", "reason": "topping up"}
        assert mock_request.call_args.kwargs["headers"][IDEMPOTENCY_KEY_HEADER] == "key-123"
        assert mock_request.call_args.kwargs["headers"][INTERNAL_ACTOR_HEADER] == ADMIN_ACTOR
        assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert result.entry_id == "entry-1"
        assert result.balance_usd == "35.000000"
        assert result.duplicate is False

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_duplicate_replay(self, mock_settings):
        _configured(mock_settings)
        payload = {"team_id": 42, "entry_id": "entry-1", "amount_usd": "25", "balance_usd": "35", "duplicate": True}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, payload)):
            result = add_credit(42, "25", "again", "key-123")
        assert result.duplicate is True

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_with_error_detail_on_4xx(self, mock_settings):
        _configured(mock_settings)
        body = {"error": "amount_usd: must be positive"}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(400, body)):
            with pytest.raises(AIGatewayInternalError, match="amount_usd: must be positive"):
                add_credit(42, "-1", "bad", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_non_json_success_body(self, mock_settings):
        _configured(mock_settings)
        non_json = httpx.Response(200, text="<html>not json</html>", request=httpx.Request("POST", "http://gw"))
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=non_json):
            with pytest.raises(AIGatewayInternalError, match="not valid JSON"):
                add_credit(42, "10", "x", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_raises_on_success_body_missing_required_fields(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, {"team_id": 42})):
            with pytest.raises(AIGatewayInternalError, match="missing required fields"):
                add_credit(42, "10", "x", "key-123")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_accepts_zero_balance(self, mock_settings):
        _configured(mock_settings)
        body = {"team_id": 42, "entry_id": "e1", "amount_usd": "10", "balance_usd": "0", "duplicate": False}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, body)):
            result = add_credit(42, "10", "x", "key-123")
        assert result.balance_usd == "0"


class TestUserBudgets:
    ROW = {"team_id": 42, "scope_type": "user", "scope_value": "u1", "limit_usd": "5", "window_seconds": 3600}

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_get_matches_only_this_users_row_in_the_collection(self, mock_settings):
        _configured(mock_settings)
        rows = [
            {**self.ROW, "scope_type": "product"},
            {**self.ROW, "scope_value": "someone-else"},
            self.ROW,
        ]
        with patch(
            "posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, {"budgets": rows})
        ) as mock_request:
            budget = get_user_budget(42, "u1")

        method, url = mock_request.call_args.args
        assert method == "GET"
        assert url == "http://gw/internal/teams/42/budgets"
        assert budget is not None
        assert budget.limit_usd == "5"
        assert budget.window_seconds == 3600

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_get_returns_none_when_the_user_has_no_budget(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, {"budgets": []})):
            assert get_user_budget(42, "u1") is None

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_get_surfaces_a_route_missing_404_with_its_status(self, mock_settings):
        _configured(mock_settings)
        with patch(
            "posthog.llm.gateway_internal_client.httpx.request", return_value=_response(404, {"error": "not found"})
        ):
            with pytest.raises(AIGatewayInternalError) as exc:
                get_user_budget(42, "u1")
        assert exc.value.status_code == 404

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_set_puts_the_node_addressed_budget_on_the_collection(self, mock_settings):
        _configured(mock_settings)
        with patch(
            "posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, self.ROW)
        ) as mock_request:
            budget = set_user_budget(42, "u1", "5", 3600)

        method, url = mock_request.call_args.args
        assert method == "PUT"
        assert url == "http://gw/internal/teams/42/budgets"
        assert mock_request.call_args.kwargs["json"] == {
            "scope_type": USER_SCOPE_TYPE,
            "scope_value": "u1",
            "limit_usd": "5",
            "window_seconds": 3600,
        }
        assert mock_request.call_args.kwargs["headers"][INTERNAL_ACTOR_HEADER] == USER_ACTOR
        assert budget.limit_usd == "5"

    @pytest.mark.parametrize(
        "row",
        [
            {"limit_usd": "5", "window_seconds": "soon"},
            {"limit_usd": "5"},
            {"window_seconds": 3600},
        ],
    )
    @patch("posthog.llm.gateway_internal_client.settings")
    def test_set_wraps_a_malformed_budget_row_in_the_error_contract(self, mock_settings, row):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(200, row)):
            with pytest.raises(AIGatewayInternalError):
                set_user_budget(42, "u1", "5", 3600)

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_clear_deletes_the_budget_by_query_params(self, mock_settings):
        _configured(mock_settings)
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(204)) as mock_request:
            clear_user_budget(42, "u1")

        method, url = mock_request.call_args.args
        assert method == "DELETE"
        assert url == "http://gw/internal/teams/42/budgets"
        assert mock_request.call_args.kwargs["params"] == {"scope_type": USER_SCOPE_TYPE, "scope_value": "u1"}
        assert mock_request.call_args.kwargs["headers"][INTERNAL_ACTOR_HEADER] == USER_ACTOR

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_clear_treats_the_gateways_row_missing_404_as_cleared(self, mock_settings):
        _configured(mock_settings)
        body = {"status": 404, "code": "not_found", "message": "no budget set for that node"}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(404, body)):
            clear_user_budget(42, "u1")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_clear_treats_a_route_missing_404_as_an_error(self, mock_settings):
        _configured(mock_settings)
        router_404 = httpx.Response(404, text="404 page not found", request=httpx.Request("DELETE", "http://gw"))
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=router_404):
            with pytest.raises(AIGatewayInternalError) as exc:
                clear_user_budget(42, "u1")
        assert exc.value.status_code == 404

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_clear_rejects_a_redirect_response(self, mock_settings):
        _configured(mock_settings)
        redirect = httpx.Response(
            302,
            headers={"location": "http://gw/other"},
            request=httpx.Request("DELETE", "http://gw/internal/teams/42/budgets"),
        )
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=redirect):
            with pytest.raises(AIGatewayInternalError):
                clear_user_budget(42, "u1")

    @patch("posthog.llm.gateway_internal_client.settings")
    def test_clear_surfaces_a_conflict_with_its_status(self, mock_settings):
        _configured(mock_settings)
        body = {"status": 409, "code": "version_conflict", "message": "a concurrent update set a newer budget"}
        with patch("posthog.llm.gateway_internal_client.httpx.request", return_value=_response(409, body)):
            with pytest.raises(AIGatewayInternalError) as exc:
                clear_user_budget(42, "u1")
        assert exc.value.status_code == 409


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
