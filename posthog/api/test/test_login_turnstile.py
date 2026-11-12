from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from django_otp.plugins.otp_totp.models import TOTPDevice
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.helpers.user_devices import KNOWN_DEVICE_COOKIE
from posthog.models.instance_setting import override_instance_config
from posthog.turnstile import SiteverifyOutcome, SiteverifyResult

KEYS = {"CLOUDFLARE_TURNSTILE_SITE_KEY": "site", "CLOUDFLARE_TURNSTILE_SECRET_KEY": "secret"}
NO_KEYS = {"CLOUDFLARE_TURNSTILE_SITE_KEY": "", "CLOUDFLARE_TURNSTILE_SECRET_KEY": ""}


def _accepted() -> MagicMock:
    return MagicMock(return_value=SiteverifyOutcome(result=SiteverifyResult.ACCEPTED, duration_seconds=0.05))


def _outcomes(capture: MagicMock) -> list[str]:
    return [
        call.kwargs["properties"]["outcome"]
        for call in capture.call_args_list
        if call.kwargs.get("event") == "login_turnstile_decision"
    ]


class TestLoginTurnstileShadow(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.user.is_email_verified = True
        self.user.save()

    def _login(self, client: APIClient, **body):
        return client.post("/api/login", {"email": self.CONFIG_EMAIL, "password": self.CONFIG_PASSWORD, **body})

    def _known_device_cookie(self) -> tuple[str, str]:
        response = self._login(self.client)
        name = KNOWN_DEVICE_COOKIE.format(user_id=self.user.id)
        return name, response.cookies[name].value

    @parameterized.expand(
        [
            (mode_name, case)
            for mode_name in ("shadow_with_keys", "shadow_without_keys")
            for case in ("correct_password", "wrong_password", "unknown_email", "two_factor", "oversized_fields")
        ]
    )
    def test_login_response_is_the_same_as_with_the_check_off(self, mode_name, case):
        if case == "two_factor":
            TOTPDevice.objects.create(user=self.user, name="default")
        body = {"turnstile_token": "tok", "turnstile_client_status": "token"}
        if case == "wrong_password":
            body["password"] = "not-the-password"
        elif case == "unknown_email":
            body["email"] = "nobody@example.com"
        elif case == "oversized_fields":
            body = {"turnstile_token": "x" * 10_000, "turnstile_client_status": "y" * 500}

        with override_instance_config("LOGIN_TURNSTILE_MODE", "off"):
            baseline = self._login(APIClient(), **body)

        settings_for_mode = KEYS if mode_name == "shadow_with_keys" else NO_KEYS
        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            override_settings(**settings_for_mode),
            patch("posthog.login_challenge.verify_login_turnstile_token", _accepted()),
        ):
            response = self._login(APIClient(), **body)

        assert (response.status_code, response.json()) == (baseline.status_code, baseline.json())

    @override_settings(**KEYS)
    def test_precheck_adds_the_site_key_only_for_a_new_browser(self):
        with override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"):
            new_browser = self.client.post("/api/login/precheck", {"email": self.CONFIG_EMAIL})
            name, value = self._known_device_cookie()
            known_client = APIClient()
            known_client.cookies[name] = value
            known_browser = known_client.post("/api/login/precheck", {"email": self.CONFIG_EMAIL})

        assert new_browser.json()["turnstile_site_key"] == "site"
        assert "turnstile_site_key" not in known_browser.json()

    @override_settings(**KEYS)
    def test_precheck_site_key_does_not_reveal_whether_the_account_exists(self):
        with override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"):
            account = self.client.post("/api/login/precheck", {"email": self.CONFIG_EMAIL})
            no_account = self.client.post("/api/login/precheck", {"email": "nobody@example.com"})

        assert account.json().get("turnstile_site_key") == no_account.json().get("turnstile_site_key") == "site"

    @override_settings(**KEYS)
    def test_known_device_is_found_for_an_email_case_variant(self):
        name, value = self._known_device_cookie()
        client = APIClient()
        client.cookies[name] = value

        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            response = client.post("/api/login", {"email": self.user.email.upper(), "password": self.CONFIG_PASSWORD})

        assert response.status_code == 200
        assert _outcomes(capture) == ["skipped_known_device"]

    @override_settings(**KEYS)
    def test_reauth_from_a_signed_in_session_is_skipped(self):
        self._login(self.client)

        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            response = self._login(self.client)

        assert response.status_code == 200
        assert _outcomes(capture) == ["skipped_reauth"]

    @override_settings(**KEYS)
    def test_new_browser_login_records_the_siteverify_outcome(self):
        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.verify_login_turnstile_token", _accepted()) as verify,
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            response = self._login(APIClient(), turnstile_token="tok", turnstile_client_status="token")

        assert response.status_code == 200
        assert _outcomes(capture) == ["passed"]
        assert verify.call_args.args[0] == "tok"

    @override_settings(**KEYS)
    def test_an_error_inside_the_step_does_not_break_login(self):
        with (
            override_instance_config("LOGIN_TURNSTILE_MODE", "shadow"),
            patch("posthog.login_challenge.has_valid_known_device_cookie", side_effect=RuntimeError("boom")),
            patch("posthog.login_challenge.posthoganalytics.capture") as capture,
        ):
            response = self._login(APIClient())
            precheck = self.client.post("/api/login/precheck", {"email": self.CONFIG_EMAIL})

        assert (response.status_code, response.json()) == (200, {"success": True})
        assert _outcomes(capture) == ["error"]
        assert precheck.status_code == 200
        assert "turnstile_site_key" not in precheck.json()
