import json
import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from posthog.models.integration.codex import (
    STATUS_CONNECTED,
    STATUS_REAUTH_REQUIRED,
    CodexAuthError,
    CodexReauthRequired,
    CodexUserIntegration,
    parse_codex_auth_json,
)
from posthog.models.user_integration import UserIntegration

FROZEN_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _jwt(claims: dict[str, Any]) -> str:
    def segment(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{segment({'alg': 'RS256'})}.{segment(claims)}.c2lnbmF0dXJl"


def _access_token(
    *, account_id: str = "acct_1", plan_type: str | None = "plus", expires_in: timedelta | None = None
) -> str:
    claims: dict[str, Any] = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    if plan_type is not None:
        claims["https://api.openai.com/auth"]["chatgpt_plan_type"] = plan_type
    if expires_in is not None:
        claims["exp"] = int((FROZEN_NOW + expires_in).timestamp())
    return _jwt(claims)


def _auth_json(
    access_token: str | None = None, *, id_token: str | None = _jwt({"email": "dev@example.com"})
) -> dict[str, Any]:
    return {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": access_token or _access_token(expires_in=timedelta(hours=1)),
            "refresh_token": "rt_submitted",
            "id_token": id_token,
            "account_id": "acct_1",
        },
    }


def _openai_response(status_code: int, body: dict[str, Any]) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _refresh_ok(refresh_token: str = "rt_rotated", expires_in: timedelta = timedelta(hours=1)) -> requests.Response:
    return _openai_response(
        200,
        {
            "access_token": _access_token(expires_in=expires_in),
            "refresh_token": refresh_token,
            "id_token": _jwt({"email": "dev@example.com"}),
        },
    )


class TestParseCodexAuthJson(SimpleTestCase):
    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_reads_the_account_plan_email_and_expiry_from_the_tokens(self) -> None:
        tokens = parse_codex_auth_json(_auth_json(_access_token(expires_in=timedelta(minutes=30))))

        assert tokens.account_id == "acct_1"
        assert tokens.plan_type == "plus"
        assert tokens.email == "dev@example.com"
        assert tokens.refresh_token == "rt_submitted"
        assert tokens.expires_at == FROZEN_NOW + timedelta(minutes=30)
        assert "rt_submitted" not in repr(tokens)

    @parameterized.expand(
        [
            ("api_key_login", {"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test"}),
            ("missing_refresh_token", {"tokens": {"access_token": _access_token()}}),
            ("access_token_without_account", {"tokens": {"access_token": _jwt({"sub": "x"}), "refresh_token": "rt"}}),
            ("not_an_object", ["tokens"]),
        ]
    )
    def test_rejects_a_file_that_cannot_start_a_refresh_chain(self, _name: str, raw: object) -> None:
        with self.assertRaises(CodexAuthError):
            parse_codex_auth_json(raw)


class TestCodexUserIntegration(BaseTest):
    def _connect(self, response: requests.Response | None = None) -> CodexUserIntegration:
        with patch("requests.request", return_value=response or _refresh_ok()):
            return CodexUserIntegration.connect(self.user.id, parse_codex_auth_json(_auth_json()), source="test")

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_connect_refreshes_once_and_stores_only_the_rotated_chain(self) -> None:
        with patch("requests.request", return_value=_refresh_ok()) as request:
            integration = CodexUserIntegration.connect(self.user.id, parse_codex_auth_json(_auth_json()), source="test")

        assert request.call_args.kwargs["json"]["refresh_token"] == "rt_submitted"
        row = UserIntegration.objects.get(user=self.user, kind="codex")
        assert row.integration_id == "acct_1"
        assert row.sensitive_config["refresh_token"] == "rt_rotated"
        assert row.config["status"] == STATUS_CONNECTED
        assert integration.plan_type == "plus"
        assert integration.email == "dev@example.com"

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_connect_refuses_a_chain_openai_rejects_and_stores_nothing(self) -> None:
        with patch(
            "requests.request", return_value=_openai_response(400, {"error": {"code": "refresh_token_expired"}})
        ):
            with self.assertRaises(CodexReauthRequired):
                CodexUserIntegration.connect(self.user.id, parse_codex_auth_json(_auth_json()), source="test")

        assert not UserIntegration.objects.filter(user=self.user, kind="codex").exists()

    @parameterized.expand(
        [
            ("fresh_token_not_forced", timedelta(hours=1), False, timedelta(0), False),
            ("inside_refresh_margin", timedelta(minutes=4), False, timedelta(0), True),
            ("forced_right_after_a_refresh", timedelta(hours=1), True, timedelta(seconds=10), False),
            ("forced_after_the_dedupe_window", timedelta(hours=1), True, timedelta(seconds=45), True),
        ]
    )
    def test_issue_access_grant_refreshes_only_when_needed(
        self, _name: str, expires_in: timedelta, force: bool, since_refresh: timedelta, expect_refresh: bool
    ) -> None:
        with time_machine.travel(FROZEN_NOW, tick=False):
            self._connect(_refresh_ok(expires_in=expires_in))
        with time_machine.travel(FROZEN_NOW + since_refresh, tick=False):
            with patch("requests.request", return_value=_refresh_ok("rt_second")) as request:
                grant = CodexUserIntegration.issue_access_grant(self.user.id, force=force, source="test")

        assert request.called is expect_refresh
        row = UserIntegration.objects.get(user=self.user, kind="codex")
        assert row.sensitive_config["refresh_token"] == ("rt_second" if expect_refresh else "rt_rotated")
        assert grant.access_token == row.sensitive_config["access_token"]
        assert grant.account_id == "acct_1"
        assert "access_token" not in repr(grant)

    def test_a_dead_refresh_chain_marks_the_row_for_reconnect_and_drops_the_tokens(self) -> None:
        with time_machine.travel(FROZEN_NOW, tick=False):
            self._connect()

        with time_machine.travel(FROZEN_NOW + timedelta(minutes=1), tick=False):
            with patch("requests.request", return_value=_openai_response(401, {"error": "invalid_grant"})):
                with self.assertRaises(CodexReauthRequired):
                    CodexUserIntegration.issue_access_grant(self.user.id, force=True, source="test")

        row = UserIntegration.objects.get(user=self.user, kind="codex")
        assert row.config["status"] == STATUS_REAUTH_REQUIRED
        assert row.sensitive_config == {}
        with patch("requests.request") as request:
            with self.assertRaises(CodexReauthRequired):
                CodexUserIntegration.issue_access_grant(self.user.id, force=False, source="test")
        assert not request.called

    def test_a_server_error_on_refresh_keeps_the_chain_for_a_retry(self) -> None:
        with time_machine.travel(FROZEN_NOW, tick=False):
            self._connect()

        with time_machine.travel(FROZEN_NOW + timedelta(minutes=1), tick=False):
            with patch("requests.request", return_value=_openai_response(503, {})):
                with self.assertRaises(CodexAuthError) as raised:
                    CodexUserIntegration.issue_access_grant(self.user.id, force=True, source="test")

        assert not isinstance(raised.exception, CodexReauthRequired)
        row = UserIntegration.objects.get(user=self.user, kind="codex")
        assert row.config["status"] == STATUS_CONNECTED
        assert row.sensitive_config["refresh_token"] == "rt_rotated"

    @time_machine.travel(FROZEN_NOW, tick=False)
    def test_disconnect_revokes_the_refresh_token_and_deletes_the_row(self) -> None:
        integration = self._connect()

        with patch("requests.request", return_value=_openai_response(200, {})) as request:
            integration.disconnect(source="test")

        assert request.call_args.kwargs["data"]["token"] == "rt_rotated"
        assert not UserIntegration.objects.filter(user=self.user, kind="codex").exists()
