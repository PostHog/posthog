from typing import Literal

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.http import HttpRequest
from django.test import RequestFactory, override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.helpers.user_devices import KNOWN_DEVICE_COOKIE, build_known_device_cookie_value
from posthog.login_challenge import (
    LoginTurnstileMode,
    LoginTurnstileOutcome,
    get_login_turnstile_mode,
    is_login_turnstile_active,
    precheck_turnstile_fields,
    record_login_turnstile_decision,
)
from posthog.models import User
from posthog.models.instance_setting import override_instance_config
from posthog.turnstile import SiteverifyOutcome, SiteverifyResult

KEYS = {"CLOUDFLARE_TURNSTILE_SITE_KEY": "site", "CLOUDFLARE_TURNSTILE_SECRET_KEY": "secret"}
CLIENT_IP = "203.0.113.7"


def _decisions(outcome: str, client_status: str, mode: str = "shadow") -> float:
    labels = {"mode": mode, "outcome": outcome, "client_status": client_status}
    return REGISTRY.get_sample_value("posthog_login_turnstile_decisions_total", labels) or 0


def _siteverify_samples(result: str) -> float:
    return REGISTRY.get_sample_value("posthog_login_turnstile_siteverify_seconds_count", {"result": result}) or 0


def _request(cookie_user: User | None = None) -> HttpRequest:
    request = RequestFactory().post("/api/login", REMOTE_ADDR=CLIENT_IP, HTTP_USER_AGENT="Mozilla/5.0 Chrome/130")
    if cookie_user is not None:
        request.COOKIES[KNOWN_DEVICE_COOKIE.format(user_id=cookie_user.id)] = build_known_device_cookie_value(
            cookie_user
        )
    return request


def _verify(result: SiteverifyResult, error_codes: tuple[str, ...] = ()) -> MagicMock:
    return MagicMock(return_value=SiteverifyOutcome(result=result, error_codes=error_codes, duration_seconds=0.12))


@override_settings(**KEYS)
class TestLoginChallenge(BaseTest):
    def _record(
        self,
        request: HttpRequest,
        *,
        email: str | None = None,
        existing_user: User | None | Literal["self"] = "self",
        is_reauth: bool = False,
        token: str = "",
        client_status: str = "",
    ) -> LoginTurnstileOutcome | None:
        return record_login_turnstile_decision(
            request,
            email=email or self.user.email,
            existing_user=self.user if existing_user == "self" else existing_user,
            is_reauth=is_reauth,
            token=token,
            client_status=client_status,
        )

    def test_unknown_mode_value_is_off(self):
        with override_instance_config("LOGIN_TURNSTILE_MODE", "enforce"):
            assert get_login_turnstile_mode() == LoginTurnstileMode.OFF
            assert is_login_turnstile_active() is False

    @parameterized.expand(
        [
            ("no_site_key", {"CLOUDFLARE_TURNSTILE_SITE_KEY": ""}),
            ("no_secret_key", {"CLOUDFLARE_TURNSTILE_SECRET_KEY": ""}),
        ]
    )
    def test_shadow_without_keys_records_nothing(self, _name, missing_key):
        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            override_settings(**missing_key),
            patch("posthog.login_challenge.verify_login_turnstile_token") as verify,
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            assert is_login_turnstile_active() is False
            assert self._record(_request(), token="tok", client_status="token") is None
            assert precheck_turnstile_fields(_request(), self.user) == {}

        verify.assert_not_called()
        capture.assert_not_called()

    @parameterized.expand(
        [
            ("off_mode", "off", False, False, {}),
            ("new_browser", "shadow", False, False, {"turnstile_site_key": "site"}),
            ("no_account", "shadow", True, False, {"turnstile_site_key": "site"}),
            ("known_device", "shadow", False, True, {}),
        ]
    )
    def test_precheck_fields(self, _name, mode, no_account, with_cookie, expected):
        request = _request(cookie_user=self.user if with_cookie else None)

        with override_instance_config("LOGIN_TURNSTILE_MODE", mode):
            assert precheck_turnstile_fields(request, None if no_account else self.user) == expected

    @parameterized.expand(
        [
            ("reauth", True, True, "tok", SiteverifyResult.ACCEPTED, LoginTurnstileOutcome.SKIPPED_REAUTH),
            ("known_device", False, True, "tok", SiteverifyResult.ACCEPTED, LoginTurnstileOutcome.SKIPPED_KNOWN_DEVICE),
            ("no_token", False, False, "", SiteverifyResult.ACCEPTED, LoginTurnstileOutcome.NO_TOKEN),
            ("accepted", False, False, "tok", SiteverifyResult.ACCEPTED, LoginTurnstileOutcome.PASSED),
            ("rejected", False, False, "tok", SiteverifyResult.REJECTED, LoginTurnstileOutcome.REJECTED),
            (
                "unavailable",
                False,
                False,
                "tok",
                SiteverifyResult.UNAVAILABLE,
                LoginTurnstileOutcome.VERIFY_UNAVAILABLE,
            ),
        ]
    )
    def test_outcomes(self, _name, is_reauth, with_cookie, token, siteverify_result, expected):
        request = _request(cookie_user=self.user if with_cookie else None)

        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.verify_login_turnstile_token", _verify(siteverify_result)),
            patch("posthog.login_challenge.posthoganalytics.capture"),
        ):
            assert self._record(request, is_reauth=is_reauth, token=token, client_status="token") == expected

    @parameterized.expand(
        [
            ("cookie_of_another_user", "other"),
            ("cookie_from_before_a_password_change", "password_change"),
        ]
    )
    def test_invalid_cookie_does_not_skip(self, _name, case):
        if case == "other":
            other = User.objects.create_and_join(self.organization, "other@example.com", "password12345")
            request = _request(cookie_user=other)
        else:
            request = _request(cookie_user=self.user)
            self.user.set_password("a-new-password-12345")
            self.user.save()

        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.posthoganalytics.capture"),
        ):
            assert self._record(request) == LoginTurnstileOutcome.NO_TOKEN

    @parameterized.expand(
        [
            ("unknown_value", "garbage", "unknown"),
            ("missing_value", "", "absent"),
            ("known_value", "script_failed", "script_failed"),
        ]
    )
    def test_client_status_is_normalized(self, _name, sent, recorded):
        before = _decisions("no_token", recorded)

        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            self._record(_request(), client_status=sent)

        assert _decisions("no_token", recorded) == before + 1
        assert capture.call_args.kwargs["properties"]["client_status"] == recorded

    def test_unexpected_error_returns_error_outcome(self):
        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.verify_login_turnstile_token", side_effect=RuntimeError("boom")),
            patch("posthog.login_challenge.posthoganalytics.capture"),
        ):
            assert self._record(_request(), token="tok", client_status="token") == LoginTurnstileOutcome.ERROR

    def test_rejected_records_counter_histogram_and_event_without_raw_identifiers(self):
        before_decisions = _decisions("rejected", "token")
        before_siteverify = _siteverify_samples("rejected")

        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch(
                "posthog.login_challenge.verify_login_turnstile_token",
                _verify(SiteverifyResult.REJECTED, ("invalid-input-response",)),
            ),
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            self._record(_request(), token="tok", client_status="token")

        assert _decisions("rejected", "token") == before_decisions + 1
        assert _siteverify_samples("rejected") == before_siteverify + 1
        capture.assert_called_once()
        kwargs = capture.call_args.kwargs
        properties = kwargs["properties"]
        assert kwargs["event"] == "login_turnstile_decision"
        assert kwargs["distinct_id"] == self.user.distinct_id
        assert {key: properties[key] for key in ("mode", "outcome", "client_status", "has_account")} == {
            "mode": "shadow",
            "outcome": "rejected",
            "client_status": "token",
            "has_account": True,
        }
        assert properties["turnstile_error_codes"] == ["invalid-input-response"]
        assert properties["siteverify_duration_ms"] == 120.0
        assert properties["email_domain"] == self.user.email.split("@")[1]
        assert len(properties["ip_address_hash"]) == 16
        assert all(value not in (self.user.email, CLIENT_IP) for value in properties.values())

    def test_no_account_uses_a_pre_login_distinct_id(self):
        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            self._record(_request(), email="nobody@example.com", existing_user=None)

        assert capture.call_args.kwargs["distinct_id"].startswith("pre_login_")
        assert capture.call_args.kwargs["properties"]["has_account"] is False
