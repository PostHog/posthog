import json
import time

from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import MagicMock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.api.tagged_item import set_tags_on_object
from posthog.frontend_views import app_context
from posthog.models import Team, UserHomeSettings
from posthog.stable_chunks import StableChunks
from posthog.templatetags.posthog_filters import TolerantJSONEncoder
from posthog.utils import (
    flags_for_app_evaluation_context,
    get_context_for_template,
    get_persisted_feature_flags_for_app_context,
)

from products.conversations.backend.services.identity import IDENTITY_CLAIM_MAX_AGE_SECONDS


class TestPersistedFeatureFlagsForAppContext(SimpleTestCase):
    @parameterized.expand(
        [
            ("enabled", True, [], [], ["warehouse-person-properties"]),
            ("disabled", False, [], [], []),
            (
                "disabled_explicit",
                False,
                ["warehouse-person-properties", "other-feature"],
                [],
                ["other-feature"],
            ),
            (
                "disabled_dynamic",
                False,
                ["other-feature"],
                [
                    {
                        "key": "warehouse-person-properties",
                        "active": True,
                        "filters": {"groups": [{"rollout_percentage": 100}]},
                    }
                ],
                ["other-feature"],
            ),
        ]
    )
    @mock.patch("posthog.utils.posthoganalytics.feature_flag_definitions")
    def test_self_hosted_context_respects_operator_setting(
        self, _name, enabled, static_flags, definitions, expected, mock_definitions
    ):
        mock_definitions.return_value = definitions
        with self.settings(
            CLOUD_DEPLOYMENT=None,
            DEBUG=False,
            PERSISTED_FEATURE_FLAGS=static_flags,
            WAREHOUSE_PERSON_PROPERTIES_ENABLED_SELF_HOSTED=enabled,
        ):
            assert get_persisted_feature_flags_for_app_context() == expected

    @parameterized.expand(
        [
            ("without_explicit_flag", [], []),
            (
                "with_explicit_flag",
                ["warehouse-person-properties"],
                ["warehouse-person-properties"],
            ),
        ]
    )
    @mock.patch("posthog.utils.posthoganalytics.feature_flag_definitions", return_value=[])
    def test_cloud_context_does_not_include_non_cloud_persisted_flags(
        self, _name, static_flags, expected, _definitions
    ):
        with self.settings(
            CLOUD_DEPLOYMENT="US",
            DEBUG=False,
            PERSISTED_FEATURE_FLAGS=static_flags,
            WAREHOUSE_PERSON_PROPERTIES_ENABLED_SELF_HOSTED=False,
        ):
            assert get_persisted_feature_flags_for_app_context() == expected


STABLE_CHUNKS = StableChunks(
    imports={"@c/eAAAA": "static/index-S0000000000.js"},
    preload_js_urls=("static/index-S0000000000.js",),
    authenticated_preload_js_urls=("static/shell-S1111111111.js",),
)


class TestFlagsForAppEvaluationContext(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_contexts_is_kept", {"evaluation_contexts": None}, True),
            ("empty_contexts_is_kept", {"evaluation_contexts": []}, True),
            ("app_context_is_kept", {"evaluation_contexts": ["posthog-web-app", "posthog-website"]}, True),
            ("other_context_is_dropped", {"evaluation_contexts": ["posthog-website"]}, False),
            ("active_is_kept", {"active": True}, True),
            ("disabled_is_dropped", {"active": False}, False),
            ("client_runtime_is_kept", {"evaluation_runtime": "client"}, True),
            ("server_runtime_is_dropped", {"evaluation_runtime": "server"}, False),
        ]
    )
    def test_keeps_flags_the_app_evaluates(self, _name, definition, kept):
        definitions = [{"key": "the-flag", **definition}]

        actual = flags_for_app_evaluation_context({"the-flag": True, "untagged": True}, definitions)

        assert actual == ({"the-flag": True, "untagged": True} if kept else {"untagged": True})

    def test_keeps_every_flag_before_definitions_load(self):
        assert flags_for_app_evaluation_context({"the-flag": True}, None) == {"the-flag": True}

    def test_keeps_no_flags_when_analytics_is_disabled(self):
        definitions = [{"key": "the-flag", "evaluation_contexts": ["posthog-website"]}]

        assert flags_for_app_evaluation_context(None, definitions) is None


class TestGetContextForTemplate(APIBaseTest):
    def test_get_context_for_template(self):
        with (
            self.settings(STRIPE_PUBLIC_KEY=None, PERSISTED_FEATURE_FLAGS=["the_persisted_flags"]),
            mock.patch("posthog.settings.CLOUD_DEPLOYMENT", "LOCAL"),
        ):
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
            "posthog_app_context": {
                "persisted_feature_flags": ["the_persisted_flags", "warehouse-person-properties"],
                "anonymous": False,
                "run_mode": "LOCAL",
            },
            "posthog_bootstrap": {},
            "posthog_js_uuid_version": "v7",
            "region": None,
            "self_capture": True,
        }

    @parameterized.expand(
        [
            ("hobby", None, False, "HOBBY"),
            ("local", None, True, "LOCAL"),
            ("cloud_us", "US", False, "US"),
            ("cloud_eu", "EU", False, "EU"),
            ("cloud_dev", "DEV", False, "DEV"),
            ("e2e", "E2E", False, "E2E"),
        ]
    )
    def test_exposes_run_mode(self, _name, deployment, debug, expected):
        with (
            mock.patch("posthog.settings.CLOUD_DEPLOYMENT", deployment),
            mock.patch("posthog.settings.DEBUG", debug),
        ):
            actual = get_context_for_template("layout", MagicMock())
        assert actual["posthog_app_context"]["run_mode"] == expected

    def test_picks_up_stripe_public_key_from_environment(self):
        with self.settings(STRIPE_PUBLIC_KEY="pk_test_12345"):
            actual = get_context_for_template(
                "layout",
                MagicMock(),
            )

        assert actual["stripe_public_key"] == "pk_test_12345"

    def test_renders_one_origin_trial_meta_tag_per_token(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        with self.settings(ORIGIN_TRIAL_TOKENS=["tokenA+/=", "tokenB"]):
            html = render_to_string("head.html", get_context_for_template("layout", request), request=request)

        assert html.count('http-equiv="origin-trial"') == 2
        assert '<meta http-equiv="origin-trial" content="tokenA+/=">' in html
        assert '<meta http-equiv="origin-trial" content="tokenB">' in html

    @parameterized.expand(
        [
            (
                "configured",
                {
                    "pathname": "/dashboard/42",
                    "pinned": True,
                    "title": "Default dashboard",
                },
            ),
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

        app_context = actual["posthog_app_context"]
        assert app_context["homepage"] == (stored_homepage or None)

    @parameterized.expand([("shares_email", False, "user@example.com"), ("anonymized", True, None)])
    @mock.patch("posthog.utils.posthoganalytics.get_all_flags", return_value={})
    def test_flag_bootstrap_evaluates_with_the_identity_the_browser_sends(
        self, _name, anonymize_data, expected_email, mock_get_all_flags
    ):
        self.user.email = "user@example.com"
        self.user.anonymize_data = anonymize_data
        self.user.save()
        self.organization.customer_id = "cus_123"
        self.organization.save()
        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user

        with self.settings(SITE_URL="https://app.example.com"):
            get_context_for_template("layout", request)

        kwargs = mock_get_all_flags.call_args.kwargs
        assert kwargs["person_properties"] == {
            "email": expected_email,
            "joined_at": self.user.date_joined.isoformat(),
        }
        assert kwargs["groups"] == {
            "project": str(self.team.uuid),
            "organization": str(self.organization.id),
            "customer": "cus_123",
            "instance": "https://app.example.com",
        }
        assert kwargs["group_properties"]["project"] == {
            "id": self.team.id,
            "uuid": str(self.team.uuid),
            "name": self.team.name,
            "ingested_event": self.team.ingested_event,
            "is_demo": self.team.is_demo,
            "timezone": self.team.timezone,
            "instance_tag": settings.INSTANCE_TAG,
        }
        assert kwargs["group_properties"]["organization"] == {
            "id": str(self.organization.id),
            "name": self.organization.name,
            "slug": self.organization.slug,
            "created_at": mock.ANY,
            "available_product_features": self.organization.available_product_features or [],
            "member_count": 1,
            "project_count": 1,
            "instance_tag": settings.INSTANCE_TAG,
        }
        assert kwargs["group_properties"]["instance"] == {"site_url": "https://app.example.com"}

    def test_bootstraps_project_tags_into_app_context(self):
        # projectLogic reads currentProject from the app context and only calls the API when it is
        # absent, so tags missing here render an empty Tags field until something refetches.
        set_tags_on_object(["production", "eu-region"], self.team.project)

        request = RequestFactory().get("/")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user

        actual = get_context_for_template("layout", request)

        app_context = actual["posthog_app_context"]
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
            claims = context["js_posthog_identity_claims"]
            assert claims["email"]["value"] == self.user.email.lower()
            current_time = int(time.time())
            assert current_time < claims["email"]["expires_at"] <= current_time + IDENTITY_CLAIM_MAX_AGE_SECONDS

    @parameterized.expand(
        [
            ("logged in", "", True, ("static/index-S0000000000.js", "static/shell-S1111111111.js")),
            ("anonymous", "", False, ("static/index-S0000000000.js",)),
            ("fell back after a failed chunk", "?stable_chunks=fallback", True, ()),
        ]
    )
    def test_a_page_boots_through_the_import_map_unless_it_fell_back(
        self, _name, query, authenticated, expected_preload_js_urls
    ):
        expect_stable = query == ""
        request = RequestFactory().get(f"/{query}")
        SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
        request.user = self.user if authenticated else AnonymousUser()

        with mock.patch("posthog.stable_chunks._resolve_stable_chunks", return_value=STABLE_CHUNKS):
            context = get_context_for_template("index.html", request)

        assert context.get("stable_chunks", False) is expect_stable
        assert context["preload_js_urls"] == expected_preload_js_urls
        if expect_stable:
            assert json.loads(context["stable_chunks_importmap"]) == {
                "imports": {"@c/eAAAA": f"{context['js_url']}/static/index-S0000000000.js"}
            }
        else:
            assert "stable_chunks_importmap" not in context

    @mock.patch("posthog.utils.posthoganalytics.get_all_flags", return_value={"some-flag": True})
    @mock.patch("posthog.utils.posthoganalytics.feature_flag_definitions", return_value=None)
    def test_deferred_page_gets_the_user_data_from_app_context(self, _mock_definitions, _mock_get_all_flags):
        def user_request(path: str) -> HttpRequest:
            request = RequestFactory().get(path)
            SessionMiddleware(lambda _request: HttpResponse()).process_request(request)
            request.user = self.user
            return request

        inline = get_context_for_template("index.html", user_request("/?deferred_app_context=0"))
        deferred = get_context_for_template("index.html", user_request("/?deferred_app_context=1"))
        fetched = json.loads(app_context(user_request("/_app_context")).content)

        assert deferred["posthog_app_context"]["deferred"] is True
        assert deferred["posthog_app_context"]["current_user"] is None
        assert "featureFlags" not in deferred["posthog_bootstrap"]
        page_with_fetched = {**deferred["posthog_app_context"], **fetched["app_context"]}
        page_with_fetched.pop("deferred")
        assert page_with_fetched == json.loads(json.dumps(inline["posthog_app_context"], cls=TolerantJSONEncoder))
        assert fetched["feature_flags"] == inline["posthog_bootstrap"]["featureFlags"]

    def test_app_context_loads_the_project_in_its_path_not_the_saved_one(self):
        page_team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
        assert self.user.team == self.team

        response = self.client.get(f"/project/{page_team.pk}/_app_context")

        assert response.status_code == 200
        assert response.json()["app_context"]["current_team"]["id"] == page_team.pk

    def test_app_context_refuses_an_anonymous_request(self):
        request = RequestFactory().get("/_app_context")
        request.user = AnonymousUser()

        response = app_context(request)

        assert response.status_code == 401
        assert b"current_user" not in response.content
