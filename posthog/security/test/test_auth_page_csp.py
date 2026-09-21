from typing import Optional

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.security.auth_page_csp import AuthPageRollout, _read_rollout, auth_page_route, parse_rollout


class TestAuthPageRoute(SimpleTestCase):
    @parameterized.expand(
        [
            ("login", "/login", False, "login"),
            ("login_2fa", "/login/2fa", False, "login"),
            ("sso_begin", "/login/saml/", False, "login"),
            ("signup", "/signup", False, "signup"),
            ("invite_signup", "/signup/abc123", False, "signup"),
            ("reset_request", "/reset", False, "reset"),
            ("reset_complete", "/reset/0198aaaa/abc-123", False, "reset"),
            ("two_factor_reset", "/reset_2fa/0198aaaa/abc-123", False, "reset"),
            ("verify_email", "/verify_email/0198aaaa/abc-123", False, "verify_email"),
            ("consent", "/oauth/authorize", True, "oauth"),
            ("consent_with_slash", "/oauth/authorize/", True, "oauth"),
            ("toolbar_authorize", "/toolbar_oauth/authorize/", True, "toolbar_oauth"),
            # The SPA sends a signed-in visitor on from login to the app inside the same document, and
            # the app loads from origins this policy refuses.
            ("signed_in_login", "/login", True, None),
            ("signed_in_invite", "/signup/abc123", True, None),
            # A prefix match without the separator would hand app pages the auth policy.
            ("login_prefix_without_separator", "/loginfoo", False, None),
            ("reset_prefix_without_separator", "/resetfoo", False, None),
            ("oauth_callback", "/oauth/callback", False, None),
            ("app_page", "/project/1/dashboard", False, None),
        ]
    )
    def test_auth_page_route(self, _name: str, path: str, is_authenticated: bool, expected: Optional[str]) -> None:
        assert auth_page_route(path, is_authenticated=is_authenticated) == expected


class TestParseRollout(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_payload", None, {}, {}),
            ("payload_not_an_object", "enforce everything", {}, {}),
            (
                "routes_and_rates",
                {"enforce": {"oauth": 100, "login": 10}, "report_sample_rate": {"toolbar_oauth": 1, "login": 0.1}},
                {"oauth": 100, "login": 10},
                {"toolbar_oauth": 1.0, "login": 0.1},
            ),
            # A typo must leave a route report-only, never enforce something else.
            ("unknown_route", {"enforce": {"logon": 100}}, {}, {}),
            ("percent_as_string", {"enforce": {"login": "100"}}, {}, {}),
            ("percent_as_bool", {"enforce": {"login": True}}, {}, {}),
            ("percent_out_of_range", {"enforce": {"login": 250, "signup": -5}}, {"login": 100, "signup": 0}, {}),
            # One rate for every route would unsample login along with the quiet routes.
            ("rate_not_per_route", {"report_sample_rate": 1}, {}, {}),
            ("rate_out_of_range", {"report_sample_rate": {"login": 10}}, {}, {}),
        ]
    )
    def test_parse_rollout(
        self,
        _name: str,
        payload: object,
        enforce_percent: dict[str, int],
        report_sample_rate: dict[str, float],
    ) -> None:
        assert parse_rollout(payload) == AuthPageRollout(
            enforce_percent=enforce_percent, report_sample_rate=report_sample_rate
        )

    @patch("posthog.security.auth_page_csp.posthoganalytics.get_feature_flag_result")
    def test_flag_is_read_locally_without_sending_events(self, mock_flag) -> None:
        mock_flag.return_value = None
        assert _read_rollout() is None
        # A network lookup would sit in the path of every auth page, and a flag event per document
        # would flood the project with one-off distinct ids.
        assert mock_flag.call_args.kwargs["only_evaluate_locally"] is True
        assert mock_flag.call_args.kwargs["send_feature_flag_events"] is False
