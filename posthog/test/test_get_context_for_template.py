import json

from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import MagicMock

from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory

from parameterized import parameterized

from posthog.models import UserHomeSettings
from posthog.utils import get_context_for_template


class TestGetContextForTemplate(APIBaseTest):
    def test_get_context_for_template(self):
        with self.settings(STRIPE_PUBLIC_KEY=None, PERSISTED_FEATURE_FLAGS=["the_persisted_flags"]):
            actual = get_context_for_template(
                "layout",
                MagicMock(),
            )

        # the current team has an api_token
        assert self.team.api_token != "sTMFPsFhdP1Ssg"
        # but we use the posthog cloud api_token for the context
        assert actual == {
            "git_rev": mock.ANY,
            "js_capture_time_to_see_data": False,
            # NB: we default to the PH Cloud key
            "js_posthog_api_key": "sTMFPsFhdP1Ssg",
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
