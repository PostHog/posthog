import json
from urllib.parse import quote

from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.auth_entry_experiment import LOGIN_ENTRY_FLAG, LoginEntryExperiment
from posthog.constants import POSTHOG_JS_CLOUD_TOKEN
from posthog.frontend_views import home
from posthog.models import User
from posthog.utils import get_context_for_template


class TestAuthPrototype(SimpleTestCase):
    @parameterized.expand([("control",), ("test",)])
    def test_development_entry_keeps_server_assignment(self, variant: str) -> None:
        request = RequestFactory().get("/login?no-preloaded-app-context=1")
        request.user = AnonymousUser()
        with (
            self.settings(DEBUG=True, TEST=False, SELF_CAPTURE=False),
            patch.object(request, "csp_nonce", "synthetic-nonce", create=True),
            patch("posthog.utils.get_persisted_feature_flags_for_app_context", return_value=[]),
        ):
            context = get_context_for_template("auth_prototype.html", request, {"login_entry_variant": variant})
        self.assertIn("src/auth-prototype/authPrototypeEntry.tsx", context["vite_dev_scripts"])
        self.assertIn('nonce="synthetic-nonce"', context["vite_dev_scripts"])
        self.assertEqual(context["posthog_bootstrap"]["featureFlags"][LOGIN_ENTRY_FLAG], variant)

    @parameterized.expand(
        [
            ("disabled", False, "/login?auth_app=standalone", False, "index.html"),
            ("no_opt_in", True, "/login", False, "index.html"),
            ("unknown_variant", True, "/login?auth_app=other", False, "index.html"),
            ("login", True, "/login?auth_app=standalone", False, "auth_prototype.html"),
            ("trailing_slash", True, "/login/?auth_app=standalone", False, "auth_prototype.html"),
            ("signup", True, "/signup?auth_app=standalone", False, "index.html"),
            ("two_factor", True, "/login/2fa?auth_app=standalone", False, "index.html"),
            ("signed_in", True, "/login?auth_app=standalone", True, "index.html"),
        ]
    )
    def test_only_opted_in_login_uses_the_separate_entry(
        self, _name: str, enabled: bool, path: str, authenticated: bool, template: str
    ) -> None:
        request = RequestFactory().get(path)
        request.user = User() if authenticated else AnonymousUser()
        with (
            self.settings(AUTH_APP_PROTOTYPE_ENABLED=enabled),
            patch("posthog.frontend_views.is_cloud", return_value=False),
            patch("posthog.frontend_views.render_template", side_effect=lambda name, *_: HttpResponse(name)),
        ):
            response = home(request)

        self.assertEqual(response.content.decode(), template)
        if template == "auth_prototype.html":
            self.assertEqual(response["Cache-Control"], "private, no-store")
            self.assertIn("csrftoken", " ".join(response.cookies))

    @parameterized.expand([("control", "index.html"), ("test", "auth_prototype.html"), (None, "index.html")])
    def test_server_assignment_selects_the_entry(self, variant: str | None, template: str) -> None:
        request = RequestFactory().get("/login")
        request.user = AnonymousUser()
        with (
            self.settings(AUTH_APP_PROTOTYPE_ENABLED=False),
            patch.object(LoginEntryExperiment, "variant", return_value=variant),
            patch("posthog.frontend_views.render_template", side_effect=lambda name, *_: HttpResponse(name)),
        ):
            response = home(request)
        self.assertEqual(response.content.decode(), template)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_cloud_query_cannot_force_the_test_entry(self) -> None:
        request = RequestFactory().get("/login?auth_app=standalone", HTTP_HOST="us.posthog.com")
        request.user = AnonymousUser()
        with (
            self.settings(AUTH_APP_PROTOTYPE_ENABLED=True),
            patch("posthog.frontend_views.is_cloud", return_value=True),
            patch("posthog.frontend_views.render_template", side_effect=lambda name, *_: HttpResponse(name)),
        ):
            self.assertEqual(home(request).content.decode(), "index.html")


class TestLoginEntryExperiment(SimpleTestCase):
    @parameterized.expand([("control", "control"), ("test", "test"), (False, None), (None, None), ("unknown", None)])
    def test_local_assignment_and_exposure(self, flag_value: str | bool | None, expected: str | None) -> None:
        request = RequestFactory().get("/login", HTTP_HOST="us.posthog.com")
        request.user = AnonymousUser()
        request.COOKIES[f"ph_{POSTHOG_JS_CLOUD_TOKEN}_posthog"] = quote(
            json.dumps({"distinct_id": "synthetic-person", "$device_id": "synthetic-device"})
        )
        with (
            self.settings(OPT_OUT_CAPTURE=False),
            patch("posthog.auth_entry_experiment.is_cloud", return_value=True),
            patch(
                "posthog.auth_entry_experiment.posthoganalytics.get_feature_flag", return_value=flag_value
            ) as evaluate,
            patch("posthog.auth_entry_experiment.posthoganalytics.capture") as capture,
        ):
            self.assertEqual(LoginEntryExperiment.variant(request), expected)
        evaluate.assert_called_once_with(
            LOGIN_ENTRY_FLAG,
            "synthetic-person",
            device_id="synthetic-device",
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        self.assertEqual(capture.call_count, int(expected is not None))
        if expected is not None:
            self.assertEqual(capture.call_args.kwargs["properties"]["$device_id"], "synthetic-device")

    def test_flag_failure_keeps_the_current_entry(self) -> None:
        request = RequestFactory().get("/login", HTTP_HOST="us.posthog.com")
        request.user = AnonymousUser()
        request.COOKIES[f"ph_{POSTHOG_JS_CLOUD_TOKEN}_posthog"] = json.dumps(
            {"distinct_id": "synthetic-person", "$device_id": "synthetic-device"}
        )
        with (
            self.settings(OPT_OUT_CAPTURE=False),
            patch("posthog.auth_entry_experiment.is_cloud", return_value=True),
            patch(
                "posthog.auth_entry_experiment.posthoganalytics.get_feature_flag",
                side_effect=RuntimeError("unavailable"),
            ),
            patch("posthog.auth_entry_experiment.capture_exception") as capture_error,
        ):
            self.assertIsNone(LoginEntryExperiment.variant(request))
        capture_error.assert_called_once()

    @parameterized.expand(
        [
            ("/login", ""),
            ("/login", "broken"),
            ("/login", "[]"),
            ("/login", '{"distinct_id":"synthetic-person"}'),
            ("/login", json.dumps({"distinct_id": "", "$device_id": "synthetic-device"})),
            ("/login", json.dumps({"distinct_id": "synthetic-person", "$device_id": ""})),
            ("/login", json.dumps({"distinct_id": "x" * 201, "$device_id": "synthetic-device"})),
            ("/login", json.dumps({"distinct_id": "synthetic-person", "$device_id": "x" * 201})),
            ("/login?auth_app=standalone", None),
            ("/login?auth_app=fallback", None),
            ("/signup", None),
            ("/login/2fa", None),
        ]
    )
    def test_ineligible_request_does_not_evaluate(self, path: str, cookie: str | None) -> None:
        request = RequestFactory().get(path, HTTP_HOST="us.posthog.com")
        request.user = AnonymousUser()
        request.COOKIES[f"ph_{POSTHOG_JS_CLOUD_TOKEN}_posthog"] = (
            cookie
            if cookie is not None
            else json.dumps({"distinct_id": "synthetic-person", "$device_id": "synthetic-device"})
        )
        with (
            self.settings(OPT_OUT_CAPTURE=False),
            patch("posthog.auth_entry_experiment.is_cloud", return_value=True),
            patch("posthog.auth_entry_experiment.posthoganalytics.get_feature_flag") as evaluate,
        ):
            self.assertIsNone(LoginEntryExperiment.variant(request))
        evaluate.assert_not_called()
