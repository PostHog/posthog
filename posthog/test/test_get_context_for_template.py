import json
import time

from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory

from parameterized import parameterized

from posthog.api.tagged_item import set_tags_on_object
from posthog.models import UserHomeSettings
from posthog.utils import get_context_for_template

from products.conversations.backend.services.identity import IDENTITY_CLAIM_MAX_AGE_SECONDS


class TestGetContextForTemplate(APIBaseTest):
    def test_get_context_for_template(self):
        with self.settings(STRIPE_PUBLIC_KEY=None, PERSISTED_FEATURE_FLAGS=["the_persisted_flags"]):
            actual = get_context_for_template(
                "layout",
                MagicMock(),
            )

        # Under self-capture, posthog-js evaluates PostHog's own flags with the dogfood-flags team's
        # token (first team by PK), which in this test is self.team — not the PH Cloud key.
        assert self.team.api_token != "sTMFPsFhdP1Ssg"
        assert actual == {
            "git_rev": mock.ANY,
            "js_capture_time_to_see_data": False,
            "js_posthog_api_key": self.team.api_token,
            "js_posthog_host": "",
            "js_url": "http://localhost:8234",
            "opt_out_capture": False,
            "posthog_app_context": '{"persisted_feature_flags": ["the_persisted_flags"], "anonymous": false}',
            "posthog_bootstrap": "{}",
            "posthog_js_uuid_version": "v7",
            "region": None,
            "self_capture": True,
        }

    def test_picks_up_stripe_public_key_from_environment(self):
        with self.settings(STRIPE_PUBLIC_KEY="pk_test_12345"):
            actual = get_context_for_template(
                "layout",
                MagicMock(),
            )

        assert actual["stripe_public_key"] == "pk_test_12345"

    @parameterized.expand(
        [
            ("configured", {"pathname": "/dashboard/42", "pinned": True, "title": "Default dashboard"}),
            ("not_configured", None),
            ("empty_is_cleared", {}),
        ]
    )
    def test_bootstraps_configured_homepage_into_app_context(self, _name, stored_homepage):
        if stored_homepage is not None:
            UserHomeSettings.objects.create(user=self.user, team=self.team, homepage=stored_homepage)

        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user

        actual = get_context_for_template("layout", request)

        app_context = json.loads(actual["posthog_app_context"])
        assert app_context["homepage"] == (stored_homepage or None)

    def test_bootstraps_project_tags_into_app_context(self):
        # projectLogic reads currentProject from the app context and only calls the API when it is
        # absent, so tags missing here render an empty Tags field until something refetches.
        set_tags_on_object(["production", "eu-region"], self.team.project)

        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user

        actual = get_context_for_template("layout", request)

        app_context = json.loads(actual["posthog_app_context"])
        assert sorted(app_context["current_project"]["tags"]) == ["eu-region", "production"]

    @parameterized.expand(
        [
            ("anonymous_is_always_light", None, "light"),
            ("missing_theme_mode_means_light", "", "light"),
            ("dark", "dark", "dark"),
            ("system_defers_to_the_os", "system", "system"),
        ]
    )
    def test_boot_theme_mirrors_theme_logic(self, _name, theme_mode, expected):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        if theme_mode is None:
            request.user = AnonymousUser()
        else:
            self.user.theme_mode = theme_mode or None
            self.user.save()
            request.user = self.user

        actual = get_context_for_template("index.html", request)

        assert actual["boot_theme"] == expected

    @parameterized.expand(
        [
            ("verified", True, True),
            ("unverified", False, False),
            ("legacy_unknown", None, False),
        ]
    )
    def test_only_verified_email_is_signed_as_identity_claim(self, _name, verification_state, expects_claim):
        self.user.is_email_verified = verification_state
        self.user.save(update_fields=["is_email_verified"])
        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user

        with mock.patch(
            "posthog.models.instance_setting.get_instance_setting",
            return_value="test-conversations-secret",
        ):
            context = get_context_for_template("index.html", request)

        assert ("js_posthog_identity_claims" in context) is expects_claim
        if expects_claim:
            claims = json.loads(context["js_posthog_identity_claims"])
            assert claims["email"]["value"] == self.user.email.lower()
            current_time = int(time.time())
            assert current_time < claims["email"]["expires_at"] <= current_time + IDENTITY_CLAIM_MAX_AGE_SECONDS
