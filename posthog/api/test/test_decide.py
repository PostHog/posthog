import base64
import json
import random
import time
from typing import Optional
from unittest.mock import patch

from inline_snapshot import snapshot
import pytest
from django.conf import settings
from django.core.cache import cache
from django.db import connection, connections
from django.http import HttpRequest
from django.test import TestCase, TransactionTestCase
from django.test.client import Client
from freezegun import freeze_time
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog import redis
from posthog.api.decide import get_decide, label_for_team_id_to_track
from posthog.api.test.test_feature_flag import QueryTimeoutWrapper
from posthog.exceptions import (
    RequestParsingError,
    UnspecifiedCompressionFallbackParsingError,
)
from posthog.models import (
    FeatureFlag,
    GroupTypeMapping,
    Person,
    PersonalAPIKey,
    Plugin,
    PluginConfig,
    PluginSourceFile,
    Project,
)
from posthog.models.cohort.cohort import Cohort
from posthog.models.feature_flag.feature_flag import FeatureFlagHashKeyOverride
from posthog.models.group.group import Group
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.person import PersonDistinctId
from posthog.models.personal_api_key import hash_key_value
from posthog.models.plugin import sync_team_inject_web_apps
from posthog.models.remote_config import RemoteConfig
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import (
    BaseTest,
    QueryMatchingTest,
    snapshot_postgres_queries,
)


def make_session_recording_decide_response(overrides: Optional[dict] = None) -> dict:
    if overrides is None:
        overrides = {}

    return {
        "endpoint": "/s/",
        "recorderVersion": "v2",
        "consoleLogRecordingEnabled": True,
        "linkedFlag": None,
        "minimumDurationMilliseconds": None,
        "networkPayloadCapture": None,
        "masking": None,
        "urlTriggers": [],
        "urlBlocklist": [],
        "scriptConfig": None,
        "sampleRate": None,
        "eventTriggers": [],
        "triggerMatchType": None,
        **overrides,
    }


class TestDecide(BaseTest, QueryMatchingTest):
    """
    Tests the `/decide` endpoint.
    We use Django's base test class instead of DRF's because we need granular control over the Content-Type sent over.
    """

    use_remote_config = False

    only_evaluate_survey_feature_flags = False

    def setUp(self, *args):
        cache.clear()

        # delete all keys in redis
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)

        super().setUp()
        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(
        self,
        data=None,
        origin="http://127.0.0.1:8000",
        api_version=1,
        distinct_id="example_id",
        groups=None,
        geoip_disable=False,
        ip="127.0.0.1",
        disable_flags=False,
        user_agent: Optional[str] = None,
        assert_num_queries: Optional[int] = None,
        simulate_database_timeout: bool = False,
        only_evaluate_survey_feature_flags: bool = False,
    ):
        if self.use_remote_config:
            # We test a lot with settings changes so the idea is to refresh the remote config
            remote_config = RemoteConfig.objects.get(team=self.team)
            # Force as sync as lots of the tests are clearing redis purposefully which messes with things
            remote_config.sync(force=True)

        if groups is None:
            groups = {}

        def do_request():
            url = f"/decide/?v={api_version}"
            if self.use_remote_config:
                url += "&use_remote_config=true"
            if only_evaluate_survey_feature_flags:
                url += "&only_evaluate_survey_feature_flags=true"
            return self.client.post(
                url,
                {
                    "data": self._dict_to_b64(
                        data
                        or {
                            "token": self.team.api_token,
                            "distinct_id": distinct_id,
                            "groups": groups,
                            "geoip_disable": geoip_disable,
                            "disable_flags": disable_flags,
                        },
                    )
                },
                HTTP_ORIGIN=origin,
                REMOTE_ADDR=ip,
                HTTP_USER_AGENT=user_agent or "PostHog test",
            )

        if simulate_database_timeout:
            with connection.execute_wrapper(QueryTimeoutWrapper()):
                return do_request()

        if assert_num_queries:
            with self.assertNumQueries(assert_num_queries):
                return do_request()
        else:
            return do_request()

    def _update_team(self, data, expected_status_code: int = status.HTTP_200_OK):
        # use a non-csrf client to make requests
        client = Client()
        client.force_login(self.user)

        response = client.patch("/api/environments/@current/", data, content_type="application/json")
        self.assertEqual(response.status_code, expected_status_code)

        client.logout()

    def test_defaults_to_v2_if_conflicting_parameters(self, *args):
        """
        posthog-js version 1.19.0 (but not versions before or after)
        mistakenly sent two `v` parameters to the decide endpoint
        one was correct "2"
        the other incorrect "1.19.0"

        as a result, if there is a value error reading the `v` param, decide now defaults to 2
        """

        response = self.client.post(
            f"/decide/?v=2&v=1.19.0",
            {
                "data": self._dict_to_b64(
                    {
                        "token": self.team.api_token,
                        "distinct_id": "example_id",
                        "groups": {},
                    }
                )
            },
            HTTP_ORIGIN="http://127.0.0.1:8000",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_on_evil_site(self, *args):
        user = self.organization.members.first()
        assert user is not None
        user.toolbar_mode = "toolbar"
        user.save()

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        response = self.client.get("/decide/", HTTP_ORIGIN="https://evilsite.com").json()
        self.assertEqual(response["isAuthenticated"], False)
        self.assertIsNone(response["toolbarParams"].get("toolbarVersion", None))

    def test_user_session_recording_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self._update_team({"session_recording_opt_in": True})

        response = self._post_decide().json()
        assert response["sessionRecording"] == make_session_recording_decide_response()
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js"])

    def test_user_console_log_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self._update_team({"session_recording_opt_in": True, "capture_console_log_opt_in": True})

        response = self._post_decide().json()
        assert response["sessionRecording"] == make_session_recording_decide_response()

    def test_user_performance_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(
            response["capturePerformance"],
            {"network_timing": True, "web_vitals": False, "web_vitals_allowed_metrics": None},
        )

        self._update_team({"capture_performance_opt_in": False})

        response = self._post_decide().json()
        self.assertEqual(response["capturePerformance"], False)

    def test_session_recording_sample_rate(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["sampleRate"] is None

        self._update_team({"session_recording_sample_rate": 0.8})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["sampleRate"], "0.80")

    def test_session_recording_sample_rate_of_0_is_not_treated_as_no_sampling(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["sampleRate"] is None

        self._update_team({"session_recording_sample_rate": 0.0})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["sampleRate"], "0.00")

    def test_session_recording_sample_rate_of_1_is_treated_as_no_sampling(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["sampleRate"] is None

        self._update_team({"session_recording_sample_rate": 1.0})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["sampleRate"], None)

    def test_session_recording_minimum_duration(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["minimumDurationMilliseconds"] is None

        self._update_team({"session_recording_minimum_duration_milliseconds": 800})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["minimumDurationMilliseconds"], 800)

    def test_session_recording_sample_rate_of_0_is_treated_as_no_sampling(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["sampleRate"] is None

        self._update_team({"session_recording_minimum_duration_milliseconds": 0})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["minimumDurationMilliseconds"], None)

    def test_session_recording_linked_flag(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["linkedFlag"] is None

        self._update_team({"session_recording_linked_flag": {"id": 12, "key": "my-flag"}})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["linkedFlag"], "my-flag")

    def test_session_recording_linked_flag_variant(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["linkedFlag"] is None

        self._update_team({"session_recording_linked_flag": {"id": 12, "key": "my-flag", "variant": "test"}})

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["linkedFlag"], {"flag": "my-flag", "variant": "test"})

    def test_session_recording_url_trigger_patterns(self, *args):
        self._update_team(
            {
                "session_recording_url_trigger_config": [{"url": "/replay-examples/", "matching": "regex"}],
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response(
            {
                "urlTriggers": [{"url": "/replay-examples/", "matching": "regex"}],
            }
        )

    def test_session_recording_url_blocklist_patterns(self, *args):
        self._update_team(
            {
                "session_recording_url_blocklist_config": [{"url": "/replay-examples/iframe", "matching": "regex"}],
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response(
            {
                "urlBlocklist": [{"url": "/replay-examples/iframe", "matching": "regex"}],
            }
        )

    def test_session_recording_event_triggers(self, *args):
        self._update_team(
            {
                "session_recording_event_trigger_config": ["$pageview", "$exception"],
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response(
            {"eventTriggers": ["$pageview", "$exception"]}
        )

    def test_session_recording_trigger_match_type_can_be_all(self, *args):
        self._update_team(
            {
                "session_recording_trigger_match_type_config": "all",
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response({"triggerMatchType": "all"})

    def test_session_recording_trigger_match_type_can_be_any(self, *args):
        self._update_team(
            {
                "session_recording_trigger_match_type_config": "any",
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response({"triggerMatchType": "any"})

    def test_session_recording_trigger_match_type_default_is_absent(self, *args):
        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response({"triggerMatchType": None})

    def test_session_recording_trigger_match_type_cannot_be_empty_string(self, *args):
        self._update_team(
            {
                "session_recording_trigger_match_type_config": "",
                "session_recording_opt_in": True,
            },
            expected_status_code=status.HTTP_400_BAD_REQUEST,
        )

    def test_session_recording_trigger_match_type_cannot_be_unknown_string(self, *args):
        self._update_team(
            {
                "session_recording_trigger_match_type_config": "unknown",
                "session_recording_opt_in": True,
            },
            expected_status_code=status.HTTP_400_BAD_REQUEST,
        )

    def test_session_recording_network_payload_capture_config(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["networkPayloadCapture"] is None

        self._update_team(
            {
                "session_recording_network_payload_capture_config": {"recordHeaders": True},
            }
        )

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["networkPayloadCapture"], {"recordHeaders": True})

    @parameterized.expand(
        [
            ["default config", None, None],
            ["mask all inputs", {"maskAllInputs": True}, {"maskAllInputs": True}],
            [
                "mask text selector",
                {"maskAllInputs": False, "maskTextSelector": "*"},
                {"maskAllInputs": False, "maskTextSelector": "*"},
            ],
            [
                "block selector",
                {"blockSelector": "img"},
                {"blockSelector": "img"},
            ],
        ]
    )
    def test_session_recording_masking_config(
        self, _name: str, config: Optional[dict], expected: Optional[dict], *args
    ):
        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        self._update_team({"session_recording_masking_config": config})

        response = self._post_decide().json()
        assert response["sessionRecording"]["masking"] == expected

    def test_session_recording_empty_linked_flag(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert response["sessionRecording"]["linkedFlag"] is None

        self._update_team(
            {"session_recording_linked_flag": {}},
            expected_status_code=status.HTTP_400_BAD_REQUEST,
        )

    def test_session_replay_config(self, *args):
        # :TRICKY: Test for regression around caching

        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        response = self._post_decide().json()
        assert "recordCanvas" not in response["sessionRecording"]
        assert "canvasFps" not in response["sessionRecording"]
        assert "canvasQuality" not in response["sessionRecording"]

        self._update_team(
            {
                "session_replay_config": {"record_canvas": True},
            }
        )

        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"]["recordCanvas"], True)
        self.assertEqual(response["sessionRecording"]["canvasFps"], 3)
        self.assertEqual(response["sessionRecording"]["canvasQuality"], "0.4")

    @parameterized.expand(
        [
            [
                "defaults to none",
                None,
                None,
                {"scriptConfig": None},
                False,
            ],
            [
                "must have allowlist",
                "new-recorder",
                None,
                {"scriptConfig": None},
                False,
            ],
            [
                "ignores empty allowlist",
                "new-recorder",
                [],
                {"scriptConfig": None},
                False,
            ],
            [
                "wild card works",
                "new-recorder",
                ["*"],
                {"scriptConfig": {"script": "new-recorder"}},
                False,
            ],
            [
                "can have wild card and team id",
                "new-recorder",
                ["*"],
                {"scriptConfig": {"script": "new-recorder"}},
                True,
            ],
            [
                "allow list can exclude",
                "new-recorder",
                ["9999", "9998"],
                {"scriptConfig": None},
                False,
            ],
            [
                "allow list can include",
                "new-recorder",
                ["9999", "9998"],
                {"scriptConfig": {"script": "new-recorder"}},
                True,
            ],
        ]
    )
    def test_session_recording_script_config(
        self,
        _name: str,
        rrweb_script_name: str | None,
        team_allow_list: list[str] | None,
        expected: dict,
        include_team_in_allowlist: bool,
    ) -> None:
        self._update_team(
            {
                "session_recording_opt_in": True,
            }
        )

        if team_allow_list and include_team_in_allowlist:
            team_allow_list.append(f"{self.team.id}")

        with self.settings(
            SESSION_REPLAY_RRWEB_SCRIPT=rrweb_script_name,
            SESSION_REPLAY_RRWEB_SCRIPT_ALLOWED_TEAMS=",".join(team_allow_list or []),
        ):
            response = self._post_decide(api_version=3)
            assert response.status_code == 200
            assert response.json()["sessionRecording"] == make_session_recording_decide_response(expected)

    def test_exception_autocapture_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["autocaptureExceptions"], False)

        self._update_team({"autocapture_exceptions_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(response["autocaptureExceptions"], True)

    def test_web_vitals_autocapture_opt_in(self, *args):
        response = self._post_decide().json()
        self.assertEqual(
            response["capturePerformance"],
            {"web_vitals": False, "network_timing": True, "web_vitals_allowed_metrics": None},
        )

        self._update_team({"autocapture_web_vitals_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(
            response["capturePerformance"],
            {"web_vitals": True, "network_timing": True, "web_vitals_allowed_metrics": None},
        )

    def test_web_vitals_autocapture_allowed_metrics(self, *args):
        response = self._post_decide().json()
        self.assertEqual(
            response["capturePerformance"],
            {"web_vitals": False, "network_timing": True, "web_vitals_allowed_metrics": None},
        )

        self._update_team({"autocapture_web_vitals_opt_in": True})
        self._update_team({"autocapture_web_vitals_allowed_metrics": ["CLS", "FCP"]})

        response = self._post_decide().json()
        self.assertEqual(
            response["capturePerformance"],
            {"web_vitals": True, "network_timing": True, "web_vitals_allowed_metrics": ["CLS", "FCP"]},
        )

    def test_user_session_recording_domain_opt_in_wildcard(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["sessionRecording"], False)

        self._update_team(
            {
                "session_recording_opt_in": True,
                "recording_domains": ["https://*.example.com"],
            }
        )

        response = self._post_decide(origin="https://random.example.com").json()
        assert response["sessionRecording"] == make_session_recording_decide_response()
        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js"])

        # Make sure the domain matches exactly
        response = self._post_decide(origin="https://random.example.com.evilsite.com").json()
        self.assertEqual(response["sessionRecording"], False)

    def test_user_session_recording_domain_not_allowed(self, *args):
        self._update_team(
            {
                "session_recording_opt_in": True,
                "recording_domains": ["https://example.com"],
            }
        )

        response = self._post_decide(origin="evil.site.com").json()
        assert response["sessionRecording"] is False

        response = self._post_decide(origin="https://example.com").json()
        assert response["sessionRecording"] == make_session_recording_decide_response()

    def test_user_autocapture_opt_out(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["autocapture_opt_out"], False)

        self._update_team({"autocapture_opt_out": True})

        response = self._post_decide().json()
        self.assertEqual(response["autocapture_opt_out"], True)

    def test_user_heatmaps_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["heatmaps"], False)

        self._update_team({"heatmaps_opt_in": True})

        response = self._post_decide().json()
        self.assertEqual(response["heatmaps"], True)

    def test_user_capture_dead_clicks_opt_in(self, *args):
        # :TRICKY: Test for regression around caching
        response = self._post_decide().json()
        self.assertEqual(response["captureDeadClicks"], False)

        self._update_team({"capture_dead_clicks": True})

        response = self._post_decide().json()
        self.assertEqual(response["captureDeadClicks"], True)

    def test_user_session_recording_allowed_when_no_permitted_domains_are_set(self, *args):
        self._update_team({"session_recording_opt_in": True, "recording_domains": []})

        response = self._post_decide(origin="any.site.com").json()
        assert response["sessionRecording"] == make_session_recording_decide_response()

    def test_user_session_recording_allowed_for_android(self, *args) -> None:
        self._update_team({"session_recording_opt_in": True, "recording_domains": ["https://my-website.io"]})

        response = self._post_decide(origin="any.site.com", user_agent="posthog-android/3.1.0").json()
        assert response["sessionRecording"] == make_session_recording_decide_response()

    def test_user_session_recording_allowed_for_ios(self, *args) -> None:
        self._update_team({"session_recording_opt_in": True, "recording_domains": ["https://my-website.io"]})

        response = self._post_decide(origin="any.site.com", user_agent="posthog-ios/3.1.0").json()
        assert response["sessionRecording"] == make_session_recording_decide_response()

    def test_user_session_recording_allowed_when_permitted_domains_are_not_http_based(self, *args):
        self._update_team(
            {
                "session_recording_opt_in": True,
                "recording_domains": ["capacitor://localhost"],
            }
        )

        response = self._post_decide(origin="capacitor://localhost:8000/home").json()
        assert response["sessionRecording"] == make_session_recording_decide_response()

    @snapshot_postgres_queries
    def test_web_app_queries(self, *args):
        response = self._post_decide(assert_num_queries=2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        PluginConfig.objects.create(
            plugin=plugin,
            enabled=True,
            order=1,
            team=self.team,
            config={},
            web_token="tokentoken",
        )
        sync_team_inject_web_apps(self.team)

        # caching flag definitions in the above mean fewer queries
        # 3 of these queries are just for setting transaction scope
        response = self._post_decide(assert_num_queries=0 if self.use_remote_config else 4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        injected = response.json()["siteApps"]
        self.assertEqual(len(injected), 1)

    def test_site_app_injection(self, *args):
        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        plugin_config = PluginConfig.objects.create(
            plugin=plugin,
            enabled=True,
            order=1,
            team=self.team,
            config={},
            web_token="tokentoken",
        )
        self.team.refresh_from_db()
        self.assertTrue(self.team.inject_web_apps)
        response = self._post_decide(assert_num_queries=1 if self.use_remote_config else 5)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        injected = response.json()["siteApps"]
        self.assertEqual(len(injected), 1)
        self.assertTrue(injected[0]["url"].startswith(f"/site_app/{plugin_config.id}/{plugin_config.web_token}/"))

    def test_feature_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone

        # Test number of queries with multiple property filter feature flags
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=50,
            name="Filter by property",
            key="filer-by-property",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "tim@posthog.com",
                                "type": "person",
                            }
                        ]
                    }
                ]
            },
            name="Filter by property 2",
            key="filer-by-property-2",
            created_by=self.user,
        )

        response = self._post_decide(assert_num_queries=4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("default-flag", response.json()["featureFlags"])
        self.assertIn("beta-feature", response.json()["featureFlags"])
        self.assertIn("filer-by-property-2", response.json()["featureFlags"])

        # caching flag definitions in the above query mean fewer queries
        response = self._post_decide({"token": self.team.api_token, "distinct_id": "another_id"}, assert_num_queries=4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["featureFlags"], ["default-flag"])

    def test_feature_flags_v3_json(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "tim@posthog.com",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": None,
                    }
                ],
                "payloads": {"true": {"color": "blue"}},
            },
            name="Filter by property",
            key="filter-by-property",
            created_by=self.user,
        )

        response = self._post_decide(api_version=3, assert_num_queries=4)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            {"color": "blue"},
            response.json()["featureFlagPayloads"]["filter-by-property"],
        )

    def test_feature_flags_v3_json_multivariate(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "payloads": {"first-variant": {"color": "blue"}},
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=0)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("beta-feature", response.json()["featureFlags"])
        self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])

        response = self._post_decide(api_version=3, assert_num_queries=0)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])
        self.assertEqual(
            {"color": "blue"},
            response.json()["featureFlagPayloads"]["multivariate-flag"],
        )

    def test_feature_flags_v4_json(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        bf = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=0,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        mvFlag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "payloads": {"first-variant": {"color": "blue"}},
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            version=42,
        )
        self.assertEqual(mvFlag.version, 42)

        response = self._post_decide(api_version=4, assert_num_queries=0)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flags = response.json()["flags"]
        self.assertEqual(
            flags["beta-feature"],
            {
                "key": "beta-feature",
                "enabled": False,
                "variant": None,
                "reason": {
                    "code": "out_of_rollout_bound",
                    "condition_index": 0,
                    "description": "Out of rollout bound",
                },
                "metadata": {
                    "id": bf.id,
                    "version": 1,
                    "description": None,
                    "payload": None,
                },
            },
        )
        self.assertEqual(
            flags["multivariate-flag"],
            {
                "key": "multivariate-flag",
                "enabled": True,
                "variant": "first-variant",
                "reason": {
                    "code": "condition_match",
                    "condition_index": 0,
                    "description": "Matched condition set 1",
                },
                "metadata": {
                    "id": mvFlag.id,
                    "version": 42,
                    "description": None,
                    "payload": {"color": "blue"},
                },
            },
        )

    def test_feature_flags_v2(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=1, assert_num_queries=0)  # v1 functionality should not break
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("beta-feature", response.json()["featureFlags"])
        self.assertIn("default-flag", response.json()["featureFlags"])

        # caching flag definitions in the above query mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash

        response = self._post_decide(api_version=2, distinct_id="other_id", assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "third-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, different variant assigned

    def test_feature_flags_v2_with_property_overrides(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$geoip_country_name": "India"},
        )
        Person.objects.create(team=self.team, distinct_ids=["other_id"], properties={})

        australia_ip = "13.106.122.3"

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "Australia",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "India",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": None,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=2, ip=australia_ip, assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])

        # caching flag definitions in the above mean fewer queries
        response = self._post_decide(api_version=2, distinct_id="other_id", ip=australia_ip, assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])

    def test_feature_flags_v2_with_geoip_error(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$geoip_country_name": "India"},
        )
        Person.objects.create(team=self.team, distinct_ids=["other_id"], properties={})

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "Australia",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "India",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": None,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, distinct_id="example_id", assert_num_queries=4)
        self.assertTrue("beta-feature" not in response.json()["featureFlags"])
        self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])

        response = self._post_decide(api_version=2, distinct_id="other_id", assert_num_queries=4)
        self.assertTrue("beta-feature" not in response.json()["featureFlags"])
        self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])

    def test_feature_flags_v2_consistent_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=5)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash

        # new person, merged from old distinct ID
        # person.delete()
        # person2 = Person.objects.create(team=self.team, distinct_ids=["example_id", "other_id"], properties={"email": "tim@posthog.com"})
        person.add_distinct_id("other_id")

        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": "other_id",
                "$anon_distinct_id": "example_id",
            },
            assert_num_queries=13,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, overridden by distinct_id, same variant assigned

    def test_feature_flags_v3_consistent_flags_with_numeric_distinct_ids(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        Person.objects.create(team=self.team, distinct_ids=[1], properties={"email": "tim@posthog.com"})
        Person.objects.create(
            team=self.team,
            distinct_ids=[12345, "xyz"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=5)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])

        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": 12345,
                "$anon_distinct_id": "example_id",
            },
            assert_num_queries=13,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])

        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": "xyz",
                "$anon_distinct_id": 12345,
            },
            assert_num_queries=9,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])

        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": 5,
                "$anon_distinct_id": 12345,
            },
            assert_num_queries=9,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])

    def test_feature_flags_v2_consistent_flags_with_ingestion_delays(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        # We're simulating ingestion delays, so this person below we expect to be created isn't created yet
        # person = Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={"email": "tim@posthog.com"})

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=4)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash

        # identify event is sent, but again, ingestion delays, so no entry in personDistinctID table
        # person.add_distinct_id("other_id")
        # in which case, we're pretty much trashed
        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": "other_id",
                "$anon_distinct_id": "example_id",
            },
            assert_num_queries=12,
        )
        # self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "third-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, should've been overridden by distinct_id, but ingestion delays mean different variant assigned

    def test_feature_flags_v2_consistent_flags_with_merged_persons(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=5)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash

        # new person, created separately before "example_id" came into the picture.
        # on identify, this will trigger a merge with person.id being deleted, and
        # `example_id` becoming a part of person2.
        person2 = Person.objects.create(
            team=self.team,
            distinct_ids=["other_id"],
            properties={"email": "tim@posthog.com"},
        )

        # caching flag definitions in the above mean fewer queries
        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": "other_id",
                "$anon_distinct_id": "example_id",
            },
            assert_num_queries=13,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, overridden by distinct_id, same variant assigned

        # now let's say a merge happens with a call like: identify(distinct_id='example_id', anon_distinct_id='other_id')
        # that is, person2 is going to get merged into person. (Could've been vice versa, but the following code assumes this, it's symmetric.)
        new_person_id = person.id
        old_person_id = person2.id
        # this happens in the plugin server
        # https://github.com/PostHog/posthog/blob/master/plugin-server/src/utils/db/db.ts (updateCohortsAndFeatureFlagsForMerge)
        # at which point we run the query
        query = f"""
            WITH deletions AS (
                    DELETE FROM posthog_featureflaghashkeyoverride WHERE team_id = {self.team.pk} AND person_id = {old_person_id}
                    RETURNING team_id, person_id, feature_flag_key, hash_key
                )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, {new_person_id}, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING
        """
        with connection.cursor() as cursor:
            cursor.execute(query)

        person2.delete()
        person.add_distinct_id("other_id")

        # caching flag definitions in the above mean fewer queries
        response = self._post_decide(
            api_version=2,
            data={"token": self.team.api_token, "distinct_id": "other_id"},
            assert_num_queries=5,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, overridden by distinct_id, same variant assigned

    def test_feature_flags_v2_consistent_flags_with_delayed_new_identified_person(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, assert_num_queries=5)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash

        # new person with "other_id" is yet to be created

        # caching flag definitions in the above mean fewer queries
        response = self._post_decide(
            api_version=2,
            data={
                "token": self.team.api_token,
                "distinct_id": "other_id",
                "$anon_distinct_id": "example_id",
            },
            assert_num_queries=13,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, overridden by distinct_id, same variant assigned

        # calling a simple decide call, while 'other_id' is still missing a person creation.
        # In this case, we are over our grace period for ingestion, and there's
        # no quick decent way to find how 'other_id' is to be treated.
        # So, things appear like a completely new person with distinct-id = other_id.
        # And this person can't have any hash key overrides (since the person doesn't yet exist)
        # So one fewer query to not get overrides.
        response = self._post_decide(
            api_version=2,
            data={"token": self.team.api_token, "distinct_id": "other_id"},
            assert_num_queries=4,
        )
        # self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual("third-variant", response.json()["featureFlags"]["multivariate-flag"])  # variant changed

        person.add_distinct_id("other_id")
        # Finally, 'other_id' is merged. The result goes back to its overridden values

        # caching flag definitions in the above mean fewer queries
        response = self._post_decide(
            api_version=2,
            data={"token": self.team.api_token, "distinct_id": "other_id"},
            assert_num_queries=5,
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, overridden by distinct_id, same variant assigned

    def test_feature_flags_v2_complex(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "realm": "cloud"},
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["hosted_id"],
            properties={"email": "sam@posthog.com", "realm": "hosted"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "realm", "type": "person", "value": "cloud"}],
                        "rollout_percentage": 80,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "fourth-variant",
                            "name": "Fourth Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with top-level property filtering and percentage rollout.",
            key="multivariate-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, distinct_id="hosted_id", assert_num_queries=4)
        self.assertIsNone(
            (response.json()["featureFlags"]).get("multivariate-flag", None)
        )  # User is does not have realm == "cloud". Value is None.
        self.assertTrue((response.json()["featureFlags"]).get("default-flag"))  # User still receives the default flag

        response = self._post_decide(api_version=2, distinct_id="example_id", assert_num_queries=4)
        self.assertIsNotNone(
            response.json()["featureFlags"]["multivariate-flag"]
        )  # User has an 80% chance of being assigned any non-empty value.
        self.assertEqual(
            "second-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # If the user falls in the rollout group, they have a 25% chance of being assigned any particular variant.
        # Their overall probability is therefore 80% * 25% = 20%.
        # To give another example, if n = 100 Cloud users and rollout_percentage = 80:
        # None:           20 (100 * (100% - 80%))
        # first-variant:  20 (100 * 80% * 25% = 20 users)
        # second-variant: 20 (100 * 80% * 25% = 20 users)
        # third-variant:  20 (100 * 80% * 25% = 20 users)
        # fourth-variant: 20 (100 * 80% * 25% = 20 users)

    def test_feature_flags_v3(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {"groups": [{"rollout_percentage": 50}]},
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "multivariate-flag",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # At this stage, our cache should have all 3 flags

        # also adding team to cache
        self._post_decide(api_version=3)
        client.logout()

        response = self._post_decide(api_version=3, assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

        response = self._post_decide(api_version=3, distinct_id="other_id", assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "third-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # different hash, different variant assigned
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_with_database_errors(self, mock_counter, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim",
                                    "type": "person",
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 50,
                        }
                    ]
                },
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "multivariate-flag",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # At this stage, our cache should have all 3 flags

        # also adding team to cache
        self._post_decide(api_version=3)

        client.logout()

        response = self._post_decide(api_version=3, assert_num_queries=4)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

        # now database is down
        response = self._post_decide(api_version=3, distinct_id="example_id", simulate_database_timeout=True)
        self.assertTrue("beta-feature" not in response.json()["featureFlags"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual("first-variant", response.json()["featureFlags"]["multivariate-flag"])
        self.assertTrue(response.json()["errorsWhileComputingFlags"])

        mock_counter.labels.assert_called_once_with(reason="timeout")

    @patch("posthog.models.feature_flag.flag_matching.FLAG_HASH_KEY_WRITES_COUNTER")
    @patch("posthog.api.decide.FLAG_EVALUATION_COUNTER")
    @patch("posthog.models.feature_flag.flag_matching.FLAG_EVALUATION_ERROR_COUNTER")
    def test_feature_flags_v3_metric_counter(self, mock_error_counter, mock_counter, mock_hash_key_counter, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "tim",
                                    "type": "person",
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 50,
                        }
                    ]
                },
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "multivariate-flag",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "ensure_experience_continuity": True,
            },
            format="json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # At this stage, our cache should have all 3 flags

        with self.settings(DECIDE_TRACK_TEAM_IDS=["all"]):
            # also adding team to cache
            response = self._post_decide(
                api_version=3,
                data={
                    "token": self.team.api_token,
                    "distinct_id": "other_id",
                    "$anon_distinct_id": "example_id",
                },
            )

            mock_counter.labels.assert_called_once_with(
                team_id=str(self.team.pk),
                errors_computing=False,
                has_hash_key_override=True,
            )
            mock_counter.labels.return_value.inc.assert_called_once()
            mock_error_counter.labels.assert_not_called()
            mock_hash_key_counter.labels.assert_called_once_with(team_id=str(self.team.pk), successful_write=True)
            client.logout()

            mock_counter.reset_mock()
            mock_hash_key_counter.reset_mock()

            response = self._post_decide(api_version=3, assert_num_queries=9)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant",
                response.json()["featureFlags"]["multivariate-flag"],
            )  # assigned by distinct_id hash
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

            mock_counter.labels.assert_called_once_with(
                team_id=str(self.team.pk),
                errors_computing=False,
                has_hash_key_override=False,
            )
            mock_counter.labels.return_value.inc.assert_called_once()
            mock_error_counter.labels.assert_not_called()
            mock_hash_key_counter.labels.assert_not_called()

            mock_counter.reset_mock()

            # now database is down
            response = self._post_decide(api_version=3, distinct_id="example_id", simulate_database_timeout=True)
            self.assertTrue("beta-feature" not in response.json()["featureFlags"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertTrue("multivariate-flag" not in response.json()["featureFlags"])
            self.assertTrue(response.json()["errorsWhileComputingFlags"])

            mock_counter.labels.assert_called_once_with(
                team_id=str(self.team.pk),
                errors_computing=True,
                has_hash_key_override=False,
            )
            mock_counter.labels.return_value.inc.assert_called_once()
            mock_error_counter.labels.assert_any_call(reason="healthcheck_failed")
            mock_error_counter.labels.assert_any_call(reason="timeout")
            self.assertEqual(mock_error_counter.labels.call_count, 2)

            mock_hash_key_counter.labels.assert_not_called()

    def test_feature_flags_v3_with_database_errors_and_no_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        # adding team to cache
        self._post_decide(api_version=3)

        response = self._post_decide(api_version=3, assert_num_queries=0)
        self.assertEqual(response.json()["featureFlags"], {})
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

        response = self._post_decide(api_version=3, distinct_id="example_id", simulate_database_timeout=True)
        self.assertEqual(response.json()["featureFlags"], {})
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v3_with_database_errors_and_geoip_properties(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        australia_ip = "13.106.122.3"

        Person.objects.create(team=self.team, distinct_ids=["example_id"], properties={})

        # use a non-csrf client to make requests to add feature flags
        client = Client()
        client.force_login(self.user)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "$geoip_country_name",
                                    "value": "Australia",
                                    "type": "person",
                                    "operator": "icontains",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
                "name": "Beta feature",
                "key": "beta-feature",
            },
            content_type="application/json",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "default-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
            content_type="application/json",
        )  # Should be enabled for everyone
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # At this stage, our cache should have both flags

        # also adding team to cache
        self._post_decide(api_version=3)

        client.logout()

        response = self._post_decide(api_version=3, ip=australia_ip, assert_num_queries=0)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

        response = self._post_decide(
            api_version=3, distinct_id="example_id", ip=australia_ip, simulate_database_timeout=True
        )
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertFalse(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v3_consistent_flags_with_database_errors(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()
        person = Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=30,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            name="This is a feature flag with default params, no filters.",
            key="default-flag",
            created_by=self.user,
        )  # Should be enabled for everyone
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            name="This is a feature flag with multiple variants.",
            key="multivariate-flag",
            created_by=self.user,
            ensure_experience_continuity=True,
        )
        # make sure caches are populated
        response = self._post_decide(api_version=3)

        # effectively 3 queries, wrapped around by an atomic transaction
        # E   1. SAVEPOINT "s4379526528_x103"
        # E   2. SET LOCAL statement_timeout = 1000
        # E   3. SELECT "posthog_persondistinctid"."person_id", "posthog_persondistinctid"."distinct_id" FROM "posthog_persondistinctid"
        #           WHERE ("posthog_persondistinctid"."distinct_id" IN ('example_id') AND "posthog_persondistinctid"."team_id" = 1)
        # E   4. SELECT "posthog_featureflaghashkeyoverride"."feature_flag_key", "posthog_featureflaghashkeyoverride"."hash_key", "posthog_featureflaghashkeyoverride"."person_id" FROM "posthog_featureflaghashkeyoverride"
        #            WHERE ("posthog_featureflaghashkeyoverride"."person_id" IN (7) AND "posthog_featureflaghashkeyoverride"."team_id" = 1)
        # E   5. RELEASE SAVEPOINT "s4379526528_x103"
        response = self._post_decide(api_version=3, assert_num_queries=5)
        self.assertTrue(response.json()["featureFlags"]["beta-feature"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertEqual(
            "first-variant", response.json()["featureFlags"]["multivariate-flag"]
        )  # assigned by distinct_id hash

        # new person, merged from old distinct ID
        person.add_distinct_id("other_id")

        # now database is down
        response = self._post_decide(
            api_version=3,
            data={
                "token": self.team.api_token,
                "distinct_id": "other_id",
                "$anon_distinct_id": "example_id",
            },
            simulate_database_timeout=True,
        )
        self.assertTrue("beta-feature" not in response.json()["featureFlags"])
        self.assertTrue(response.json()["featureFlags"]["default-flag"])
        self.assertTrue(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v2_with_groups(self, *args):
        # More in-depth tests in posthog/api/test/test_feature_flag.py

        self.team.app_urls = ["https://example.com"]
        assert self.team is not None
        self.team.save()
        self.client.logout()
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com", "realm": "cloud"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "aggregation_group_type_index": 0,
                "groups": [{"rollout_percentage": 100}],
            },
            name="This is a group-based flag",
            key="groups-flag",
            created_by=self.user,
        )

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, distinct_id="example_id", assert_num_queries=4)
        self.assertEqual(response.json()["featureFlags"], {})

        response = self._post_decide(
            api_version=2, distinct_id="example_id", groups={"organization": "foo"}, assert_num_queries=4
        )
        self.assertEqual(response.json()["featureFlags"], {"groups-flag": True})

    def test_feature_flags_with_personal_api_key(self, *args):
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(key_value))
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Test",
            key="test",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Disabled",
            key="disabled",
            created_by=self.user,
            active=False,
        )  # disabled flag
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="default-flag",
            created_by=self.user,
        )  # enabled for everyone
        response = self._post_decide(
            {
                "distinct_id": "example_id",
                "api_key": key_value,
                "project_id": self.team.id,
            }
        ).json()
        self.assertIn("default-flag", response["featureFlags"])
        self.assertIn("test", response["featureFlags"])

    @snapshot_postgres_queries
    def test_flag_with_regular_cohorts(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_1"],
            properties={"$some_prop_1": "something_1"},
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                }
            ],
            name="cohort1",
        )
        # no calculation for cohort

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=3, distinct_id="example_id_1", assert_num_queries=5)
        self.assertEqual(response.json()["featureFlags"], {"cohort-flag": True})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

        response = self._post_decide(api_version=3, distinct_id="another_id", assert_num_queries=5)
        self.assertEqual(response.json()["featureFlags"], {"cohort-flag": False})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

    def test_flag_with_invalid_cohort_filter_condition(self, *args):
        self.team.app_urls = ["https://example.com"]
        assert self.team is not None
        self.team.save()
        self.client.logout()

        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"registration_ts": 1716447600},
        )

        # Create a cohort with an invalid filter condition (tis broken filter came from this issue: https://github.com/PostHog/posthog/issues/23213)
        # The invalid condition is that the registration_ts property is compared against a list of values
        # Since this filter must match everything, the flag should evaluate to False
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                # This is the valid condition
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": "1716274800",
                                    "operator": "gte",
                                },
                                # This is the invalid condition (lte operator comparing against a list of values)
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": ["1716447600"],
                                    "operator": "lte",
                                },
                            ],
                        }
                    ],
                }
            },
            name="Test cohort",
        )

        # Create a feature flag that uses the cohort
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": cohort.pk,
                            }
                        ],
                    }
                ]
            },
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=3, distinct_id=person1_distinct_id, assert_num_queries=5)
        self.assertEqual(response.json()["featureFlags"], {"cohort-flag": False})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

    def test_flag_with_invalid_but_safe_cohort_filter_condition(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        person1_distinct_id = "example_id"
        Person.objects.create(
            team=self.team,
            distinct_ids=[person1_distinct_id],
            properties={"registration_ts": 1716447600},
        )

        # Create a cohort with a safe OR filter that contains an invalid condition
        # it should still evaluate the FeatureFlag to True
        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                # This is the valid condition
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": "1716274800",
                                    "operator": "gte",
                                },
                                # This is the invalid condition (lte operator comparing against a list of values)
                                {
                                    "key": "registration_ts",
                                    "type": "person",
                                    "value": ["1716447600"],
                                    "operator": "lte",
                                },
                            ],
                        }
                    ],
                }
            },
            name="Test cohort",
        )

        # Create a feature flag that uses the cohort
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": cohort.pk,
                            }
                        ],
                    }
                ]
            },
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=3, distinct_id=person1_distinct_id, assert_num_queries=5)
        self.assertEqual(response.json()["featureFlags"], {"cohort-flag": True})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

    def test_flag_with_unknown_cohort(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_1"],
            properties={"$some_prop_1": "something_1"},
        )

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": 99999, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            name="This is a regular flag",
            key="simple-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=3, distinct_id="example_id_1", assert_num_queries=6)
        self.assertEqual(response.json()["featureFlags"], {"cohort-flag": False, "simple-flag": True})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

    def test_flag_with_multiple_complex_unknown_cohort(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()

        other_team = Team.objects.create(
            organization=self.organization,
            api_token="bazinga_new",
            name="New Team",
        )
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_1"],
            properties={"$some_prop_1": "something_1"},
        )

        deleted_cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                },
            ],
            name="cohort1",
            deleted=True,
        )

        cohort_from_other_team = Cohort.objects.create(
            team=other_team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                },
            ],
            name="cohort1",
        )

        cohort_with_nested_invalid = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        },
                        {
                            "key": "id",
                            "value": 99999,
                            "type": "cohort",
                        },
                        {
                            "key": "id",
                            "value": deleted_cohort.pk,
                            "type": "cohort",
                        },
                        {
                            "key": "id",
                            "value": cohort_from_other_team.pk,
                            "type": "cohort",
                        },
                    ]
                },
            ],
            name="cohort1",
        )

        cohort_valid = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        },
                    ]
                },
            ],
            name="cohort1",
        )

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": 99999, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [{"key": "id", "value": cohort_with_nested_invalid.pk, "type": "cohort"}]}]
            },
            name="This is a cohort-based flag",
            key="cohort-flag-2",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort_from_other_team.pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag-3",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {"properties": [{"key": "id", "value": cohort_valid.pk, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": cohort_with_nested_invalid.pk, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": 99999, "type": "cohort"}]},
                    {"properties": [{"key": "id", "value": deleted_cohort.pk, "type": "cohort"}]},
                ]
            },
            name="This is a cohort-based flag",
            key="cohort-flag-4",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            name="This is a regular flag",
            key="simple-flag",
            created_by=self.user,
        )

        # Each invalid cohort is queried only once
        # 1. Select all valid cohorts
        # 2. Select 99999 cohort
        # 3. Select deleted cohort
        # 4. Select cohort from other team
        response = self._post_decide(api_version=3, distinct_id="example_id_1", assert_num_queries=8)
        self.assertEqual(
            response.json()["featureFlags"],
            {
                "cohort-flag": False,
                "simple-flag": True,
                "cohort-flag-2": False,
                "cohort-flag-3": False,
                "cohort-flag-4": True,
            },
        )
        self.assertEqual(response.json()["errorsWhileComputingFlags"], False)

    @snapshot_postgres_queries
    def test_flag_with_behavioural_cohorts(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id_1"],
            properties={"$some_prop_1": "something_1"},
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[
                {"event_id": "$pageview", "days": 7},
                {
                    "properties": [
                        {
                            "key": "$some_prop_1",
                            "value": "something_1",
                            "type": "person",
                        }
                    ]
                },
            ],
            name="cohort1",
        )
        # no calculation for cohort

        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [{"key": "id", "value": cohort.pk, "type": "cohort"}]}]},
            name="This is a cohort-based flag",
            key="cohort-flag",
            created_by=self.user,
        )

        response = self._post_decide(api_version=3, distinct_id="example_id_1", assert_num_queries=1)
        self.assertEqual(response.json()["featureFlags"], {})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], True)

        response = self._post_decide(api_version=3, distinct_id="another_id", assert_num_queries=1)
        self.assertEqual(response.json()["featureFlags"], {})
        self.assertEqual(response.json()["errorsWhileComputingFlags"], True)

    def test_personal_api_key_without_project_id(self, *args):
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(key_value))
        Person.objects.create(team=self.team, distinct_ids=["example_id"])

        response = self._post_decide({"distinct_id": "example_id", "api_key": key_value})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.json(),
            {
                "type": "authentication_error",
                "code": "invalid_api_key",
                "detail": "Project API key invalid. You can find your project API key in PostHog project settings.",
                "attr": None,
            },
        )

    def test_missing_token(self, *args):
        Person.objects.create(team=self.team, distinct_ids=["example_id"])
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Test",
            key="test",
            created_by=self.user,
        )
        response = self._post_decide({"distinct_id": "example_id", "api_key": None, "project_id": self.team.id})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_short_circuited_team(self, *args):
        short_circuited_team_token = "short_circuited_team_token"

        _, short_circuited_team = Project.objects.create_with_team(
            organization=self.organization,
            team_fields={
                "api_token": short_circuited_team_token,
                "test_account_filters": [
                    {
                        "key": "email",
                        "value": "@posthog.com",
                        "operator": "not_icontains",
                        "type": "person",
                    }
                ],
                "has_completed_onboarding_for": {"product_analytics": True},
            },
            initiating_user=self.user,
        )
        with self.settings(DECIDE_SHORT_CIRCUITED_TEAM_IDS=[short_circuited_team.id]):
            response = self._post_decide(
                {
                    "distinct_id": "example_id",
                    "api_key": short_circuited_team_token,
                    "project_id": short_circuited_team.id,
                }
            )
            self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
            response_data = response.json()
            self.assertEqual(
                response_data["detail"],
                f"Team with ID {short_circuited_team.id} cannot access the /decide endpoint. Please contact us at hey@posthog.com",
            )

    def test_invalid_payload_on_decide_endpoint(self, *args):
        invalid_payloads = [
            base64.b64encode(b"1-1").decode("utf-8"),
            "1==1",
            "{distinct_id-1}",
        ]

        for payload in invalid_payloads:
            response = self.client.post("/decide/", {"data": payload}, HTTP_ORIGIN="http://127.0.0.1:8000")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            response_data = response.json()
            detail = response_data.pop("detail")
            self.assertEqual(
                response.json(),
                {"type": "validation_error", "code": "malformed_data", "attr": None},
            )
            self.assertIn("Malformed request data:", detail)

    def test_invalid_gzip_payload_on_decide_endpoint(self, *args):
        response = self.client.post(
            "/decide/?compression=gzip",
            data=b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03",
            HTTP_ORIGIN="http://127.0.0.1:8000",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        detail = response_data.pop("detail")
        self.assertEqual(
            response.json(),
            {"type": "validation_error", "code": "malformed_data", "attr": None},
        )
        self.assertIn("Malformed request data:", detail)

    def test_geoip_disable(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$geoip_country_name": "India"},
        )

        australia_ip = "13.106.122.3"

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Beta feature 1",
            key="australia-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "Australia",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Beta feature 2",
            key="india-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "India",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        geoip_not_disabled_res = self._post_decide(
            api_version=3, ip=australia_ip, geoip_disable=False, assert_num_queries=0
        )
        geoip_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable=True, assert_num_queries=4)

        # person has geoip_country_name set to India, but australia-feature is true, because geoip resolution of current IP is enabled
        self.assertEqual(
            geoip_not_disabled_res.json()["featureFlags"],
            {"australia-feature": True, "india-feature": False},
        )
        # person has geoip_country_name set to India, and australia-feature is false, because geoip resolution of current IP is disabled
        self.assertEqual(
            geoip_disabled_res.json()["featureFlags"],
            {"australia-feature": False, "india-feature": True},
        )

        # test for falsy/truthy values
        geoip_not_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable="0")
        geoip_disabled_res = self._post_decide(api_version=3, ip=australia_ip, geoip_disable="yes")

        # person has geoip_country_name set to India, but australia-feature is true, because geoip resolution of current IP is enabled
        self.assertEqual(
            geoip_not_disabled_res.json()["featureFlags"],
            {"australia-feature": True, "india-feature": False},
        )
        # person has geoip_country_name set to India, and australia-feature is false, because geoip resolution of current IP is disabled
        self.assertEqual(
            geoip_disabled_res.json()["featureFlags"],
            {"australia-feature": False, "india-feature": True},
        )

    def test_disable_flags(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"$geoip_country_name": "India"},
        )

        australia_ip = "13.106.122.3"

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Beta feature 1",
            key="australia-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "Australia",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Beta feature 2",
            key="india-feature",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "$geoip_country_name",
                                "value": "India",
                                "type": "person",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        flag_disabled_res = self._post_decide(api_version=3, ip=australia_ip, disable_flags=True, assert_num_queries=0)
        self.assertEqual(flag_disabled_res.json()["featureFlags"], {})

        # test for falsy/truthy values
        flags_not_disabled_res = self._post_decide(api_version=3, ip=australia_ip, disable_flags="0")
        flags_disabled_res = self._post_decide(api_version=3, ip=australia_ip, disable_flags="yes")

        # person has geoip_country_name set to India, but australia-feature is true, because geoip resolution of current IP is enabled
        self.assertEqual(
            flags_not_disabled_res.json()["featureFlags"],
            {"australia-feature": True, "india-feature": False},
        )
        # person has geoip_country_name set to India, and australia-feature is false, because geoip resolution of current IP is disabled
        self.assertEqual(flags_disabled_res.json()["featureFlags"], {})

    @snapshot_postgres_queries
    def test_decide_doesnt_error_out_when_database_is_down(self, *args):
        ALL_TEAM_PARAMS_FOR_DECIDE = {
            "session_recording_opt_in": True,
            "session_recording_sample_rate": 0.2,
            "capture_console_log_opt_in": True,
            "inject_web_apps": True,
            "recording_domains": ["https://*.example.com"],
            "capture_performance_opt_in": True,
            "autocapture_exceptions_opt_in": True,
            "surveys_opt_in": True,
        }
        self._update_team(ALL_TEAM_PARAMS_FOR_DECIDE)

        response = self._post_decide(api_version=2, origin="https://random.example.com").json()

        self.assertEqual(
            response["sessionRecording"],
            make_session_recording_decide_response(
                {
                    "sampleRate": "0.20",
                }
            ),
        )

        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js"])
        self.assertEqual(response["siteApps"], [])
        self.assertEqual(
            response["capturePerformance"],
            {"network_timing": True, "web_vitals": False, "web_vitals_allowed_metrics": None},
        )
        self.assertEqual(response["featureFlags"], {})
        self.assertEqual(response["autocaptureExceptions"], True)

        response = self._post_decide(
            api_version=2, origin="https://random.example.com", simulate_database_timeout=True
        ).json()

        self.assertEqual(
            response["sessionRecording"],
            make_session_recording_decide_response(
                {
                    "sampleRate": "0.20",
                }
            ),
        )

        self.assertEqual(response["supportedCompression"], ["gzip", "gzip-js"])
        self.assertEqual(response["siteApps"], [])
        self.assertEqual(
            response["capturePerformance"],
            {"network_timing": True, "web_vitals": False, "web_vitals_allowed_metrics": None},
        )
        self.assertEqual(response["autocaptureExceptions"], True)
        self.assertEqual(response["featureFlags"], {})

    def test_decide_with_json_and_numeric_distinct_ids(self, *args):
        self.client.logout()
        Person.objects.create(
            team=self.team,
            distinct_ids=[
                "a",
                "{'id': 33040, 'shopify_domain': 'xxx.myshopify.com', 'shopify_token': 'shpat_xxxx', 'created_at': '2023-04-17T08:55:34.624Z', 'updated_at': '2023-04-21T08:43:34.479'}",
                "{'x': 'y'}",
                '{"x": "z"}',
            ],
            properties={"email": "tim@posthog.com", "realm": "cloud"},
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
            name="This is a group-based flag",
            key="random-flag",
            created_by=self.user,
        )
        FeatureFlag.objects.create(
            team=self.team,
            filters={"properties": [{"key": "email", "value": "tim@posthog.com", "type": "person"}]},
            rollout_percentage=100,
            name="Filter by property",
            key="filer-by-property",
            created_by=self.user,
        )

        self._post_decide(api_version=2, distinct_id="a")

        # caching flag definitions mean fewer queries
        response = self._post_decide(api_version=2, distinct_id=12345, assert_num_queries=4)
        self.assertEqual(response.json()["featureFlags"], {"random-flag": True})

        response = self._post_decide(
            api_version=2,
            distinct_id={
                "id": 33040,
                "shopify_domain": "xxx.myshopify.com",
                "shopify_token": "shpat_xxxx",
                "created_at": "2023-04-17T08:55:34.624Z",
                "updated_at": "2023-04-21T08:43:34.479",
            },
            assert_num_queries=4,
        )
        self.assertEqual(
            response.json()["featureFlags"],
            {"random-flag": True, "filer-by-property": True},
        )

        response = self._post_decide(
            api_version=2,
            distinct_id="{'id': 33040, 'shopify_domain': 'xxx.myshopify.com', 'shopify_token': 'shpat_xxxx', 'created_at': '2023-04-17T08:55:34.624Z', 'updated_at': '2023-04-21T08:43:34.479'",
            assert_num_queries=4,
        )
        self.assertEqual(response.json()["featureFlags"], {"random-flag": True})

        response = self._post_decide(api_version=2, distinct_id={"x": "y"}, assert_num_queries=4)
        self.assertEqual(
            response.json()["featureFlags"],
            {"random-flag": True, "filer-by-property": True},
        )

        response = self._post_decide(api_version=2, distinct_id={"x": "z"}, assert_num_queries=4)
        self.assertEqual(response.json()["featureFlags"], {"random-flag": True})
        # need to pass in exact string to get the property flag

    def test_rate_limits(self, *args):
        with self.settings(
            DECIDE_RATE_LIMIT_ENABLED="y",
            DECIDE_BUCKET_REPLENISH_RATE=0.1,
            DECIDE_BUCKET_CAPACITY=3,
        ):
            self.client.logout()
            Person.objects.create(
                team=self.team,
                distinct_ids=["example_id"],
                properties={"email": "tim@posthog.com"},
            )
            FeatureFlag.objects.create(
                team=self.team,
                rollout_percentage=50,
                name="Beta feature",
                key="beta-feature",
                created_by=self.user,
            )
            FeatureFlag.objects.create(
                team=self.team,
                filters={"groups": [{"properties": [], "rollout_percentage": None}]},
                name="This is a feature flag with default params, no filters.",
                key="default-flag",
                created_by=self.user,
            )  # Should be enabled for everyone

            for i in range(3):
                response = self._post_decide(api_version=i + 1)
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_replenish_over_time(self, *args):
        with self.settings(
            DECIDE_RATE_LIMIT_ENABLED="y",
            DECIDE_BUCKET_REPLENISH_RATE=1,
            DECIDE_BUCKET_CAPACITY=1,
        ):
            self.client.logout()
            Person.objects.create(
                team=self.team,
                distinct_ids=["example_id"],
                properties={"email": "tim@posthog.com"},
            )
            FeatureFlag.objects.create(
                team=self.team,
                rollout_percentage=50,
                name="Beta feature",
                key="beta-feature",
                created_by=self.user,
            )
            FeatureFlag.objects.create(
                team=self.team,
                filters={"groups": [{"properties": [], "rollout_percentage": None}]},
                name="This is a feature flag with default params, no filters.",
                key="default-flag",
                created_by=self.user,
            )  # Should be enabled for everyone

            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 429)

            # wait for bucket to replenish
            time.sleep(1)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 429)

    def test_rate_limits_work_with_invalid_tokens(self, *args):
        self.client.logout()
        with self.settings(
            DECIDE_RATE_LIMIT_ENABLED="y",
            DECIDE_BUCKET_REPLENISH_RATE=0.01,
            DECIDE_BUCKET_CAPACITY=3,
        ):
            for _ in range(3):
                response = self._post_decide(api_version=3, data={"token": "aloha?", "distinct_id": "123"})
                self.assertEqual(response.status_code, 401)

            response = self._post_decide(api_version=3, data={"token": "aloha?", "distinct_id": "123"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_work_with_missing_tokens(self, *args):
        self.client.logout()
        with self.settings(
            DECIDE_RATE_LIMIT_ENABLED="y",
            DECIDE_BUCKET_REPLENISH_RATE=0.1,
            DECIDE_BUCKET_CAPACITY=3,
        ):
            for _ in range(3):
                response = self._post_decide(api_version=3, data={"distinct_id": "123"})
                self.assertEqual(response.status_code, 401)

            response = self._post_decide(api_version=3, data={"distinct_id": "123"})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_work_with_malformed_request(self, *args):
        self.client.logout()
        with self.settings(
            DECIDE_RATE_LIMIT_ENABLED="y",
            DECIDE_BUCKET_REPLENISH_RATE=0.1,
            DECIDE_BUCKET_CAPACITY=4,
        ):

            def invalid_request():
                return self.client.post("/decide/", {"data": "1==1"}, HTTP_ORIGIN="http://127.0.0.1:8000")

            for _ in range(4):
                response = invalid_request()
                self.assertEqual(response.status_code, 400)

            response = invalid_request()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "rate_limit_exceeded",
                    "detail": "Rate limit exceeded ",
                    "attr": None,
                },
            )

    def test_rate_limits_dont_apply_when_disabled(self, *args):
        with self.settings(DECIDE_RATE_LIMIT_ENABLED="n"):
            self.client.logout()

            for _ in range(3):
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 200)

    def test_rate_limits_dont_mix_teams(self, *args):
        new_token = "bazinga"
        Team.objects.create(
            organization=self.organization,
            api_token=new_token,
            test_account_filters=[
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "not_icontains",
                    "type": "person",
                }
            ],
        )
        self.client.logout()
        with self.settings(
            DECIDE_RATE_LIMIT_ENABLED="y",
            DECIDE_BUCKET_REPLENISH_RATE=0.1,
            DECIDE_BUCKET_CAPACITY=3,
        ):
            for _ in range(3):
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=2)
            self.assertEqual(response.status_code, 429)

            # other team is fine
            for _ in range(3):
                response = self._post_decide(api_version=3, data={"token": new_token, "distinct_id": "123"})
                self.assertEqual(response.status_code, 200)

            response = self._post_decide(api_version=3, data={"token": new_token, "distinct_id": "other id"})
            self.assertEqual(response.status_code, 429)

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_quota_limited_recordings_disabled(self, _fake_token_limiting, *args):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_SESSION_REPLAY_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token] if args[0] == QuotaResource.RECORDINGS else []

            _fake_token_limiting.side_effect = fake_limiter

            self._update_team(
                {
                    "session_recording_opt_in": True,
                }
            )

            response = self._post_decide().json()
            assert response["sessionRecording"] is False
            assert response["quotaLimited"] == ["recordings"]

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_quota_limited_recordings_other_token(self, _fake_token_limiting, *args):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_SESSION_REPLAY_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token + "a"] if args[0] == QuotaResource.RECORDINGS else []

            _fake_token_limiting.side_effect = fake_limiter

            self._update_team(
                {
                    "session_recording_opt_in": True,
                }
            )

            response = self._post_decide().json()
            assert response["sessionRecording"] is not False
            assert not response.get("quotaLimited")

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_analytics_only_fires_when_enabled(self, *args):
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        self.client.logout()
        with self.settings(DECIDE_BILLING_SAMPLING_RATE=0):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that no increments made it to redis
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{self.team.pk}"), {})

        with self.settings(DECIDE_BILLING_SAMPLING_RATE=1), freeze_time("2022-05-07 12:23:07"):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that single increment made it to redis
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{self.team.pk}"),
                {b"165192618": b"1"},
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_analytics_samples_appropriately(self, *args):
        random.seed(67890)
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        self.client.logout()
        with self.settings(DECIDE_BILLING_SAMPLING_RATE=0.5), freeze_time("2022-05-07 12:23:07"):
            for _ in range(5):
                # given the seed, 2 out of 5 are sampled
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that no increments made it to redis
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{self.team.pk}"),
                {b"165192618": b"4"},
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_analytics_samples_appropriately_with_small_sample_rate(self, *args):
        random.seed(12345)
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        self.client.logout()
        with self.settings(DECIDE_BILLING_SAMPLING_RATE=0.02), freeze_time("2022-05-07 12:23:07"):
            for _ in range(5):
                # given the seed, 1 out of 5 are sampled
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that no increments made it to redis
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{self.team.pk}"),
                {b"165192618": b"50"},
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_analytics_samples_dont_break_with_zero_sampling(self, *args):
        random.seed(12345)
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        self.client.logout()
        with self.settings(DECIDE_BILLING_SAMPLING_RATE=0), freeze_time("2022-05-07 12:23:07"):
            for _ in range(5):
                # 0 out of 5 are sampled
                response = self._post_decide(api_version=3)
                self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that no increments made it to redis
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{self.team.pk}"), {})

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_analytics_only_fires_with_non_survey_targeting_flags(self, *args):
        ff = FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="beta-feature",
            created_by=self.user,
        )
        # use a non-csrf client to make requests
        req_client = Client()
        req_client.force_login(self.user)
        response = req_client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "linked_flag_id": ff.id,
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
            content_type="application/json",
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        req_client.logout()
        self.client.logout()

        with self.settings(DECIDE_BILLING_SAMPLING_RATE=1), freeze_time("2022-05-07 12:23:07"):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that single increment made it to redis
            self.assertEqual(
                client.hgetall(f"posthog:decide_requests:{self.team.pk}"),
                {b"165192618": b"1"},
            )

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_analytics_does_not_fire_for_survey_targeting_flags(self, *args):
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=50,
            name="Beta feature",
            key="survey-targeting-random",
            created_by=self.user,
        )
        # use a non-csrf client to make requests
        req_client = Client()
        req_client.force_login(self.user)
        response = req_client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
            content_type="application/json",
        )

        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        req_client.logout()
        self.client.logout()

        with self.settings(DECIDE_BILLING_SAMPLING_RATE=1), freeze_time("2022-05-07 12:23:07"):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)

            client = redis.get_client()
            # check that single increment made it to redis
            self.assertEqual(client.hgetall(f"posthog:decide_requests:{self.team.pk}"), {})

    @patch("posthog.models.feature_flag.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_decide_new_capture_activation(self, *args):
        self.client.logout()
        response = self._post_decide(api_version=3)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("analytics" in response.json())
        self.assertEqual(response.json()["analytics"]["endpoint"], "/i/v0/e/")

        with self.settings(NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS={str(self.team.id)}):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)
            self.assertFalse("analytics" in response.json())

    def test_decide_element_chain_as_string(self, *args):
        self.client.logout()
        with self.settings(
            ELEMENT_CHAIN_AS_STRING_TEAMS={str(self.team.id)}, ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS={"0"}
        ):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)
            self.assertTrue("elementsChainAsString" in response.json())
            self.assertTrue(response.json()["elementsChainAsString"])

        with self.settings(
            ELEMENT_CHAIN_AS_STRING_TEAMS={str(self.team.id)},
            ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS={str(self.team.id)},
        ):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, 200)
            self.assertFalse("elementsChainAsString" in response.json())

    def test_decide_default_identified_only(self, *args):
        self.client.logout()
        response = self._post_decide(api_version=3)
        self.assertEqual(response.status_code, 200)
        self.assertTrue("defaultIdentifiedOnly" in response.json())
        self.assertTrue(response.json()["defaultIdentifiedOnly"])

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_decide_v1_return_empty_objects_for_all_feature_flag_related_fields_when_quota_limited(
        self, _fake_token_limiting, *args
    ):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_FEATURE_FLAG_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token] if args[0] == QuotaResource.FEATURE_FLAG_REQUESTS else []

            _fake_token_limiting.side_effect = fake_limiter

            response = self._post_decide(api_version=1).json()
            assert response["featureFlags"] == []
            assert response["errorsWhileComputingFlags"] is False
            assert "feature_flags" in response["quotaLimited"]

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_decide_v2_return_empty_objects_for_all_feature_flag_related_fields_when_quota_limited(
        self, _fake_token_limiting, *args
    ):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_FEATURE_FLAG_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token] if args[0] == QuotaResource.FEATURE_FLAG_REQUESTS else []

            _fake_token_limiting.side_effect = fake_limiter

            response = self._post_decide(api_version=2).json()
            assert response["featureFlags"] == {}
            assert response["errorsWhileComputingFlags"] is False
            assert "feature_flags" in response["quotaLimited"]

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_decide_v3_return_empty_objects_for_all_feature_flag_related_fields_when_quota_limited(
        self, _fake_token_limiting, *args
    ):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_FEATURE_FLAG_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token] if args[0] == QuotaResource.FEATURE_FLAG_REQUESTS else []

            _fake_token_limiting.side_effect = fake_limiter

            response = self._post_decide(api_version=3).json()
            assert response["featureFlags"] == {}
            assert response["featureFlagPayloads"] == {}
            assert response["errorsWhileComputingFlags"] is False
            assert "feature_flags" in response["quotaLimited"]

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_decide_v4_return_empty_objects_for_all_feature_flag_related_fields_when_quota_limited(
        self, _fake_token_limiting, *args
    ):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_FEATURE_FLAG_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token] if args[0] == QuotaResource.FEATURE_FLAG_REQUESTS else []

            _fake_token_limiting.side_effect = fake_limiter

            response = self._post_decide(api_version=4).json()
            assert response["flags"] == {}
            assert response["errorsWhileComputingFlags"] is False
            assert "feature_flags" in response["quotaLimited"]

    @patch("ee.billing.quota_limiting.list_limited_team_attributes")
    def test_feature_flags_are_empty_list_when_not_quota_limited(self, _fake_token_limiting, *args):
        from ee.billing.quota_limiting import QuotaResource

        with self.settings(DECIDE_FEATURE_FLAG_QUOTA_CHECK=True):

            def fake_limiter(*args, **kwargs):
                return [self.team.api_token + "a"] if args[0] == QuotaResource.FEATURE_FLAG_REQUESTS else []

            _fake_token_limiting.side_effect = fake_limiter

            response = self._post_decide().json()
            assert isinstance(response["featureFlags"], list)
            assert "feature_flags" not in response.get("quotaLimited", [])

    def test_decide_with_flag_keys_param(self, *args):
        self.team.app_urls = ["https://example.com"]
        self.team.save()
        self.client.logout()

        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "tim@posthog.com"},
        )

        # Create three different feature flags
        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Flag 1",
            key="flag-1",
            created_by=self.user,
        )

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Flag 2",
            key="flag-2",
            created_by=self.user,
        )

        FeatureFlag.objects.create(
            team=self.team,
            rollout_percentage=100,
            name="Flag 3",
            key="flag-3",
            created_by=self.user,
        )

        # Make a decide request with only flag-1 and flag-3 keys
        response = self._post_decide(
            api_version=3,
            data={
                "token": self.team.api_token,
                "distinct_id": "example_id",
                "flag_keys_to_evaluate": ["flag-1", "flag-3"],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify only the requested flags are returned
        response_data = response.json()
        self.assertEqual(response_data["featureFlags"], {"flag-1": True, "flag-3": True})

        # Verify flag-2 is not in the response
        self.assertNotIn("flag-2", response_data["featureFlags"])

    def test_missing_distinct_id(self, *args):
        response = self._post_decide(
            data={
                "token": self.team.api_token,
                "groups": {},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "missing_distinct_id",
                "detail": "Decide requires a distinct_id.",
                "attr": None,
            },
        )

    def test_only_evaluate_survey_feature_flags_query_param(self, *args):
        # Create a survey flag and a regular flag
        FeatureFlag.objects.create(
            team=self.team,
            name="survey flag",
            key="survey-targeting-test-survey",
            created_by=self.user,
            rollout_percentage=100,
        )
        FeatureFlag.objects.create(
            team=self.team,
            name="regular flag",
            key="regular-flag",
            created_by=self.user,
            rollout_percentage=100,
        )

        # Test with only_evaluate_survey_feature_flags=true
        response = self._post_decide(
            api_version=3,
            only_evaluate_survey_feature_flags=True,
        )
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn("featureFlags", response_data)
        self.assertIn("survey-targeting-test-survey", response_data["featureFlags"])
        self.assertNotIn("regular-flag", response_data["featureFlags"])

        # # Test with only_evaluate_survey_feature_flags=false
        # self.only_evaluate_survey_feature_flags = False
        # response = self._post_decide(
        #     api_version=3,
        # )
        # self.assertEqual(response.status_code, 200)
        # response_data = response.json()
        # self.assertIn("featureFlags", response_data)
        # self.assertIn("survey-targeting-test-survey", response_data["featureFlags"])
        # self.assertIn("regular-flag", response_data["featureFlags"])

        # # Test without the parameter (default behavior)
        # response = self._post_decide(api_version=3)
        # self.assertEqual(response.status_code, 200)
        # response_data = response.json()
        # self.assertIn("featureFlags", response_data)
        # self.assertIn("survey-targeting-test-survey", response_data["featureFlags"])
        # self.assertIn("regular-flag", response_data["featureFlags"])


class TestDecideRemoteConfig(TestDecide):
    use_remote_config = True

    def test_definitely_loads_via_remote_config(self, *args):
        # NOTE: This is a sanity check test that we aren't just using the old decide logic

        with patch.object(
            RemoteConfig, "get_config_via_token", wraps=RemoteConfig.get_config_via_token
        ) as wrapped_get_config_via_token:
            response = self._post_decide(api_version=3)
            wrapped_get_config_via_token.assert_called_once()
            request_id = response.json()["requestId"]

        # NOTE: If this changes it indicates something is wrong as we should keep this exact format
        # for backwards compatibility
        assert response.json() == snapshot(
            {
                "supportedCompression": ["gzip", "gzip-js"],
                "captureDeadClicks": False,
                "capturePerformance": {"network_timing": True, "web_vitals": False, "web_vitals_allowed_metrics": None},
                "autocapture_opt_out": False,
                "autocaptureExceptions": False,
                "analytics": {"endpoint": "/i/v0/e/"},
                "elementsChainAsString": True,
                "errorTracking": {
                    "autocaptureExceptions": False,
                    "suppressionRules": [],
                },
                "sessionRecording": False,
                "heatmaps": False,
                "surveys": False,
                "defaultIdentifiedOnly": True,
                "siteApps": [],
                "isAuthenticated": False,
                # requestId is a UUID
                "requestId": request_id,
                "toolbarParams": {},
                "config": {"enable_collect_everything": True},
                "featureFlags": {},
                "errorsWhileComputingFlags": False,
                "featureFlagPayloads": {},
            }
        )


class TestDatabaseCheckForDecide(BaseTest, QueryMatchingTest):
    """
    Tests that the database check for decide works as expected.
    Does not patch it.
    """

    def setUp(self, *args):
        cache.clear()

        super().setUp(*args)
        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(
        self,
        data=None,
        origin="http://127.0.0.1:8000",
        api_version=1,
        distinct_id="example_id",
        groups=None,
        geoip_disable=False,
        ip="127.0.0.1",
    ):
        if groups is None:
            groups = {}
        return self.client.post(
            f"/decide/?v={api_version}",
            {
                "data": self._dict_to_b64(
                    data
                    or {
                        "token": self.team.api_token,
                        "distinct_id": distinct_id,
                        "groups": groups,
                        "geoip_disable": geoip_disable,
                    },
                )
            },
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    def _update_team(self, data):
        # use a non-csrf client to make requests
        client = Client()
        client.force_login(self.user)

        response = client.patch("/api/environments/@current/", data, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        client.logout()


@pytest.mark.skipif(
    "decide" not in settings.READ_REPLICA_OPT_IN,
    reason="This test requires READ_REPLICA_OPT_IN=decide",
)
class TestDecideUsesReadReplica(TransactionTestCase):
    """
    A cheat sheet for creating a READ-ONLY fake replica when local testing:

    docker compose -f docker-compose.dev.yml exec db bash
    psql -U posthog
    CREATE USER posthog2 WITH PASSWORD 'posthog';
    # this user will be the one used to connect to the replica^^

    # switch to the db on which you want to give permissions
    \c test_posthog
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO posthog2;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO posthog2;

    then run this test:

    POSTHOG_DB_NAME='posthog' READ_REPLICA_OPT_IN='decide,PersonalAPIKey,local_evaluation' POSTHOG_POSTGRES_READ_HOST='localhost'  POSTHOG_DB_PASSWORD='posthog' POSTHOG_DB_USER='posthog'  ./bin/tests posthog/api/test/test_decide.py::TestDecideUsesReadReplica

    or run locally with the same env vars.
    For local run, also change postgres_config in data_stores.py so you can have a different user for the read replica.

    POSTHOG_DB_NAME='posthog' READ_REPLICA_OPT_IN='decide' POSTHOG_POSTGRES_READ_HOST='localhost'  POSTHOG_DB_PASSWORD='posthog' POSTHOG_DB_USER='posthog' POSTHOG_DB_PASSWORD_READ_REPLICA='password' POSTHOG_DB_USER_READ_REPLICA='posthog2' ./bin/start

    This test suite aims to be comprehensive, covering all decide code paths so we can catch if something is hitting the main db
    when it shouldn't be.
    """  # noqa: W605

    databases = {"default", "replica"}

    def setup_user_and_team_in_db(self, dbname: str = "default"):
        organization = Organization.objects.db_manager(dbname).create(
            name="Org 1", slug=f"org-{dbname}-{random.randint(1, 1000000)}"
        )
        team = Team.objects.db_manager(dbname).create(organization=organization, name="Team 1 org 1")
        user = User.objects.db_manager(dbname).create(
            email=f"test-{random.randint(1, 100000)}@posthog.com",
            password="password",
            first_name="first_name",
            current_team=team,
            current_organization=organization,
        )
        OrganizationMembership.objects.db_manager(dbname).create(
            user=user,
            organization=organization,
            level=OrganizationMembership.Level.OWNER,
        )

        return organization, team, user

    def setup_flags_in_db(self, dbname, team, user, flags, persons):
        created_flags = []
        created_persons = []
        for flag in flags:
            f = FeatureFlag.objects.db_manager(dbname).create(
                team=team,
                rollout_percentage=flag.get("rollout_percentage") or None,
                filters=flag.get("filters") or {},
                name=flag["name"],
                key=flag["key"],
                ensure_experience_continuity=flag.get("ensure_experience_continuity") or False,
                created_by=user,
            )
            created_flags.append(f)
        for person in persons:
            p = Person.objects.db_manager(dbname).create(
                team=team,
                properties=person["properties"],
            )
            created_persons.append(p)
            for distinct_id in person["distinct_ids"]:
                PersonDistinctId.objects.db_manager(dbname).create(person=p, distinct_id=distinct_id, team=team)

        return created_flags, created_persons

    def setUp(self):
        cache.clear()
        super().setUp()

        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)

    def _dict_to_b64(self, data: dict) -> str:
        return base64.b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")

    def _post_decide(
        self,
        data=None,
        origin="http://127.0.0.1:8000",
        api_version=3,
        distinct_id="example_id",
        groups=None,
        person_props=None,
        geoip_disable=False,
        ip="127.0.0.1",
    ):
        if person_props is None:
            person_props = {}
        if groups is None:
            groups = {}
        return self.client.post(
            f"/decide/?v={api_version}",
            {
                "data": self._dict_to_b64(
                    data
                    or {
                        "token": self.team.api_token,
                        "distinct_id": distinct_id,
                        "groups": groups,
                        "geoip_disable": geoip_disable,
                        "person_properties": person_props,
                    },
                )
            },
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    def test_healthcheck_uses_read_replica(self):
        org, team, user = self.setup_user_and_team_in_db("replica")
        self.organization, self.team, self.user = org, team, user
        # this create fills up team cache^

        with (
            freeze_time("2021-01-01T00:00:00Z"),
            self.assertNumQueries(1, using="default"),
        ):
            response = self._post_decide()
            # Replica queries:
            # E   1. SELECT 1
            # Main DB queries:
            # E   1. SELECT "posthog_featureflag"."id", -- fill up feature flags cache

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual({}, response.json()["featureFlags"])

    def test_decide_uses_read_replica(self):
        org, team, user = self.setup_user_and_team_in_db("default")
        self.organization, self.team, self.user = org, team, user

        persons = [{"distinct_ids": ["example_id"], "properties": {"email": "tim@posthog.com"}}]
        flags = [
            {
                "rollout_percentage": 50,
                "name": "Beta feature",
                "key": "beta-feature",
            },
            {
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
                "name": "This is a feature flag with default params, no filters.",
                "key": "default-no-prop-flag",
            },  # Should be enabled for everyone
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "posthog",
                                    "operator": "icontains",
                                    "type": "person",
                                }
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "default-flag",
            },
        ]
        self.setup_flags_in_db("default", team, user, flags, persons)

        # make sure we have the flags in cache
        response = self._post_decide(api_version=3)

        with self.assertNumQueries(4, using="replica"), self.assertNumQueries(0, using="default"):
            response = self._post_decide(api_version=3)
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 600
            # E   2. SELECT (true) AS "flag_41_condition_0", (true) AS "flag_42_condition_0" -- i.e. flag selection

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json()["featureFlags"],
                {
                    "default-flag": True,
                    "default-no-prop-flag": True,
                    "beta-feature": True,
                },
            )

        # same query with property overrides, shouldn't go to db
        with self.assertNumQueries(0, using="replica"), self.assertNumQueries(0, using="default"):
            response = self._post_decide(person_props={"email": "tom@hi.com"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json()["featureFlags"],
                {
                    "default-flag": False,
                    "default-no-prop-flag": True,
                    "beta-feature": True,
                },
            )

    def test_decide_uses_read_replica_for_cohorts_based_flags(self):
        org, team, user = self.setup_user_and_team_in_db("default")
        self.organization, self.team, self.user = org, team, user

        cohort_dynamic = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "email",
                                    "value": "tim@posthog.com",
                                    "type": "person",
                                },
                                {
                                    "key": "email",
                                    "value": "tim3@posthog.com",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        cohort_static = Cohort.objects.create(
            team=self.team,
            is_static=True,
            name="cohort2",
        )

        persons = [
            {
                "distinct_ids": ["example_id"],
                "properties": {"email": "tim@posthog.com"},
            },
            {
                "distinct_ids": ["cohort_founder"],
                "properties": {"email": "tim2@posthog.com"},
            },
            {
                "distinct_ids": ["cohort_secondary"],
                "properties": {"email": "tim3@posthog.com"},
            },
        ]
        flags = [
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "value": cohort_static.pk,
                                    "type": "cohort",
                                }
                            ]
                        }
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "static-flag",
            },
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "value": cohort_dynamic.pk,
                                    "type": "cohort",
                                }
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "dynamic-flag",
            },
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "value": cohort_dynamic.pk,
                                    "type": "cohort",
                                },
                                {
                                    "key": "id",
                                    "value": cohort_static.pk,
                                    "type": "cohort",
                                },
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "both-flag",
            },
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "value": cohort_dynamic.pk,
                                    "type": "cohort",
                                }
                            ],
                        },
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "value": cohort_static.pk,
                                    "type": "cohort",
                                }
                            ],
                        },
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "either-flag",
            },
        ]
        self.setup_flags_in_db("default", team, user, flags, persons)

        cohort_static.insert_users_by_list(["cohort_founder", "cohort_secondary"])

        # make sure we have the flags in cache
        response = self._post_decide(api_version=3)

        with self.assertNumQueries(5, using="replica"), self.assertNumQueries(0, using="default"):
            response = self._post_decide(api_version=3, distinct_id="cohort_founder")
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 600
            # E   2. SELECT "posthog_cohort"."id", "posthog_cohort"."name", -- i.e. select all cohorts
            # E   3. SELECT EXISTS(SELECT (1) AS "a" FROM "posthog_cohortpeople" U0 WHERE (U0."cohort_id" = 28 AND U0."cohort_id" = 28 AND U0."person_id" = "posthog_person"."id") LIMIT 1) AS "flag_47_condition_0",  -- a.k.a flag selection query

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json()["featureFlags"],
                {
                    "static-flag": True,
                    "dynamic-flag": False,
                    "both-flag": False,
                    "either-flag": True,
                },
            )

        with self.assertNumQueries(5, using="replica"), self.assertNumQueries(0, using="default"):
            response = self._post_decide(api_version=3, distinct_id="example_id")
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 600
            # E   2. SELECT "posthog_cohort"."id", "posthog_cohort"."name", -- i.e. select all cohorts
            # E   3. SELECT EXISTS(SELECT (1) AS "a" FROM "posthog_cohortpeople" U0 WHERE (U0."cohort_id" = 28 AND U0."cohort_id" = 28 AND U0."person_id" = "posthog_person"."id") LIMIT 1) AS "flag_47_condition_0",  -- a.k.a flag selection query

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json()["featureFlags"],
                {
                    "static-flag": False,
                    "dynamic-flag": True,
                    "both-flag": False,
                    "either-flag": True,
                },
            )

        with self.assertNumQueries(5, using="replica"), self.assertNumQueries(0, using="default"):
            response = self._post_decide(api_version=3, distinct_id="cohort_secondary")
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 600
            # E   2. SELECT "posthog_cohort"."id", "posthog_cohort"."name", -- i.e. select all cohorts
            # E   3. SELECT EXISTS(SELECT (1) AS "a" FROM "posthog_cohortpeople" U0 WHERE (U0."cohort_id" = 28 AND U0."cohort_id" = 28 AND U0."person_id" = "posthog_person"."id") LIMIT 1) AS "flag_47_condition_0",  -- a.k.a flag selection query

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.json()["featureFlags"],
                {
                    "static-flag": True,
                    "dynamic-flag": True,
                    "both-flag": True,
                    "either-flag": True,
                },
            )

    def test_feature_flags_v3_consistent_flags(self):
        org, team, user = self.setup_user_and_team_in_db("default")
        self.organization, self.team, self.user = org, team, user

        persons = [{"distinct_ids": ["example_id"], "properties": {"email": "tim@posthog.com"}}]
        flags = [
            {
                "rollout_percentage": 30,
                "name": "Beta feature",
                "key": "beta-feature",
                "ensure_experience_continuity": True,
            },
            {
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
                "name": "This is a feature flag with default params, no filters.",
                "key": "default-no-prop-flag",
            },  # Should be enabled for everyone
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "posthog",
                                    "operator": "icontains",
                                    "type": "person",
                                }
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "default-flag",
            },
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "name": "This is a flag with multiple variants",
                "key": "multivariate-flag",
                "ensure_experience_continuity": True,
            },
        ]
        _, created_persons = self.setup_flags_in_db("default", team, user, flags, persons)

        person = created_persons[0]

        # make sure caches are populated
        response = self._post_decide()

        with self.assertNumQueries(9, using="replica"), self.assertNumQueries(0, using="default"):
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. SELECT "posthog_persondistinctid"."person_id", "posthog_persondistinctid"."distinct_id" FROM "posthog_persondistinctid"
            #           WHERE ("posthog_persondistinctid"."distinct_id" IN ('example_id') AND "posthog_persondistinctid"."team_id" = 1)
            # E   3. SELECT "posthog_featureflaghashkeyoverride"."feature_flag_key", "posthog_featureflaghashkeyoverride"."hash_key", "posthog_featureflaghashkeyoverride"."person_id" FROM "posthog_featureflaghashkeyoverride"
            #            WHERE ("posthog_featureflaghashkeyoverride"."person_id" IN (7) AND "posthog_featureflaghashkeyoverride"."team_id" = 1)

            # E   4. SET LOCAL statement_timeout = 600
            # E   5. SELECT (true) AS "flag_28_condition_0",  -- flag matching query because one flag requires properties
            response = self._post_decide(api_version=3)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # new person, merged from old distinct ID
        PersonDistinctId.objects.db_manager("default").create(person=person, distinct_id="other_id", team=self.team)
        # hash key override already exists
        FeatureFlagHashKeyOverride.objects.db_manager("default").create(
            team=self.team,
            person=person,
            hash_key="example_id",
            feature_flag_key="beta-feature",
        )
        FeatureFlagHashKeyOverride.objects.db_manager("default").create(
            team=self.team,
            person=person,
            hash_key="example_id",
            feature_flag_key="multivariate-flag",
        )

        # new request with hash key overrides but not writes should not go to main database
        with self.assertNumQueries(13, using="replica"), self.assertNumQueries(0, using="default"):
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. WITH some CTEs,
            #           SELECT key FROM posthog_featureflag WHERE team_id = 13
            # E         AND key NOT IN (SELECT feature_flag_key FROM existing_overrides)
            # E   3. SET LOCAL statement_timeout = 300
            # E   4. SELECT "posthog_persondistinctid"."person_id", "posthog_persondistinctid"."distinct_id" FROM "posthog_persondistinctid" -- a.k.a select the person ids.
            #        We select person overrides from replica DB when no inserts happened
            # E   5. SELECT "posthog_featureflaghashkeyoverride"."feature_flag_key",  - a.k.a select the flag overrides

            # E   6. SET LOCAL statement_timeout = 600
            # E   7. SELECT (true) AS "flag_28_condition_0",  -- flag matching query because one flag requires properties

            response = self._post_decide(
                api_version=3,
                data={
                    "token": self.team.api_token,
                    "distinct_id": "other_id",
                    "$anon_distinct_id": "example22_id",
                },
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        # now main database is down, but does not affect replica

        with (
            connections["default"].execute_wrapper(QueryTimeoutWrapper()),
            self.assertNumQueries(13, using="replica"),
            self.assertNumQueries(0, using="default"),
        ):
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. WITH some CTEs,
            #           SELECT key FROM posthog_featureflag WHERE team_id = 13
            # E         AND key NOT IN (SELECT feature_flag_key FROM existing_overrides)
            # E   3. SET LOCAL statement_timeout = 300
            # E   4. SELECT "posthog_persondistinctid"."person_id", -- i.e person from distinct ids
            # E   5. SELECT "posthog_featureflaghashkeyoverride"."feature_flag_key", -- i.e. hash key overrides (note this would've gone to main db if insert did not fail)
            # E   6. SET LOCAL statement_timeout = 600
            # E   7. SELECT (true) AS "flag_13_condition_0", (true) AS "flag_14_condition_0", -- flag matching

            response = self._post_decide(
                api_version=3,
                data={
                    "token": self.team.api_token,
                    "distinct_id": "other_id",
                    "$anon_distinct_id": "example22_id",
                },
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        # now replica is down, so errors computing flags should be true
        with connections["replica"].execute_wrapper(QueryTimeoutWrapper()):
            response = self._post_decide(
                api_version=3,
                data={
                    "token": self.team.api_token,
                    "distinct_id": "other_id",
                    "$anon_distinct_id": "example22_id",
                },
            )
            self.assertTrue("beta-feature" not in response.json()["featureFlags"])
            self.assertTrue("default-flag" not in response.json()["featureFlags"])
            self.assertTrue(response.json()["featureFlags"]["default-no-prop-flag"])
            self.assertTrue(response.json()["errorsWhileComputingFlags"])

    def test_feature_flags_v3_consistent_flags_with_write_on_hash_key_overrides(self):
        org, team, user = self.setup_user_and_team_in_db("default")
        self.organization, self.team, self.user = org, team, user

        persons = [{"distinct_ids": ["example_id"], "properties": {"email": "tim@posthog.com"}}]
        flags = [
            {
                "rollout_percentage": 30,
                "name": "Beta feature",
                "key": "beta-feature",
                "ensure_experience_continuity": True,
            },
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "posthog",
                                    "operator": "icontains",
                                    "type": "person",
                                }
                            ],
                            "rollout_percentage": None,
                        }
                    ]
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "default-flag",
            },  # Should be enabled for everyone
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "name": "This is a flag with multiple variants",
                "key": "multivariate-flag",
                "ensure_experience_continuity": True,
            },
        ]
        _, created_persons = self.setup_flags_in_db("default", team, user, flags, persons)

        person = created_persons[0]

        # make sure caches are populated
        response = self._post_decide(api_version=3)

        with self.assertNumQueries(9, using="replica"), self.assertNumQueries(0, using="default"):
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. SELECT "posthog_persondistinctid"."person_id", "posthog_persondistinctid"."distinct_id" FROM "posthog_persondistinctid"
            #           WHERE ("posthog_persondistinctid"."distinct_id" IN ('example_id') AND "posthog_persondistinctid"."team_id" = 1)
            # E   3. SELECT "posthog_featureflaghashkeyoverride"."id", "posthog_featureflaghashkeyoverride"."team_id", -- hash key overrides

            # E   4. SET LOCAL statement_timeout = 600
            # E   5. SELECT (true) AS "flag_28_condition_0",  -- flag matching query because one flag requires properties
            response = self._post_decide(api_version=3)
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

        # new person, merged from old distinct ID
        PersonDistinctId.objects.db_manager("default").create(person=person, distinct_id="other_id", team=self.team)

        # request with hash key overrides and _new_ writes should go to main database
        with self.assertNumQueries(8, using="replica"), self.assertNumQueries(9, using="default"):
            # Replica queries:
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. WITH some CTEs,
            #           SELECT key FROM posthog_featureflag WHERE team_id = 13
            # E         AND key NOT IN (SELECT feature_flag_key FROM existing_overrides) -- checks whether we need to write
            # E   3. SET LOCAL statement_timeout = 600
            # E   4. SELECT (true) AS "flag_28_condition_0",  -- flag matching query because one flag requires properties
            # Main queries:
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. (The insert hashkey overrides query)
            # E                       WITH some CTEs,
            # E                       INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
            # E                           SELECT team_id, person_id, key, 'example_id'
            # E                           FROM flags_to_override, target_person_ids
            # E                           WHERE EXISTS (SELECT 1 FROM posthog_person WHERE id = person_id AND team_id = 7)
            # E                           ON CONFLICT DO NOTHING

            # E   3. SET LOCAL statement_timeout = 300
            # E   4. SELECT "posthog_persondistinctid"."person_id", "posthog_persondistinctid"."distinct_id" FROM "posthog_persondistinctid" -- a.k.a select the person for overrides.
            #        We select person overrides from main DB in this case to prevent replication lag from giving us the wrong override values.
            # E   5. SELECT "posthog_featureflaghashkeyoverride"."feature_flag_key",  -- a.k.a get hash key overrides

            response = self._post_decide(
                api_version=3,
                data={
                    "token": self.team.api_token,
                    "distinct_id": "other_id",
                    "$anon_distinct_id": "example_id",
                },
            )
            self.assertTrue(response.json()["featureFlags"]["beta-feature"])
            self.assertTrue(response.json()["featureFlags"]["default-flag"])
            self.assertFalse(response.json()["errorsWhileComputingFlags"])
            self.assertEqual(
                "first-variant", response.json()["featureFlags"]["multivariate-flag"]
            )  # assigned by distinct_id hash

    def test_feature_flags_v2_with_groups(
        self,
    ):
        org, team, user = self.setup_user_and_team_in_db("replica")
        self.organization, self.team, self.user = org, team, user

        persons = [{"distinct_ids": ["example_id"], "properties": {"email": "tim@posthog.com"}}]
        flags = [
            {
                "filters": {
                    "aggregation_group_type_index": 1,
                    "groups": [{"properties": [], "rollout_percentage": None}],
                },
                "name": "This is a feature flag with default params, no filters.",
                "key": "default-no-prop-group-flag",
            },  # Should be enabled for everyone
            {
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "posthog",
                                    "operator": "icontains",
                                    "type": "group",
                                    "group_type_index": 0,
                                }
                            ],
                            "rollout_percentage": None,
                        }
                    ],
                },
                "name": "This is a group-based flag",
                "key": "groups-flag",
            },
        ]
        self.setup_flags_in_db("replica", team, user, flags, persons)

        GroupTypeMapping.objects.db_manager("replica").create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.db_manager("default").create(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=1
        )

        Group.objects.db_manager("replica").create(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="foo",
            group_properties={"email": "a@posthog.com"},
            version=0,
        )

        with self.assertNumQueries(4, using="replica"), self.assertNumQueries(0, using="default"):
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. SELECT "posthog_grouptypemapping"."id", -- a.k.a. get group type mappings
            response = self._post_decide(distinct_id="example_id")
            self.assertEqual(
                response.json()["featureFlags"],
                {"default-no-prop-group-flag": False, "groups-flag": False},
            )
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        with self.assertNumQueries(9, using="replica"), self.assertNumQueries(0, using="default"):
            # E   1. SET LOCAL statement_timeout = 300
            # E   2. SELECT "posthog_grouptypemapping"."id", "posthog_grouptypemapping"."team_id", -- a.k.a get group type mappings

            # E   3. SET LOCAL statement_timeout = 600
            # E   4. SELECT (UPPER(("posthog_group"."group_properties" ->> 'email')::text) AS "flag_182_condition_0" FROM "posthog_group" -- a.k.a get group0 conditions
            # E   5. SELECT (true) AS "flag_181_condition_0" FROM "posthog_group" WHERE ("posthog_group"."team_id" = 91 -- a.k.a get group1 conditions
            response = self._post_decide(
                distinct_id="example_id",
                groups={"organization": "foo2", "project": "bar"},
            )
            self.assertEqual(
                response.json()["featureFlags"],
                {"groups-flag": False, "default-no-prop-group-flag": True},
            )
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

        with self.assertNumQueries(9, using="replica"), self.assertNumQueries(0, using="default"):
            # E   2. SET LOCAL statement_timeout = 300
            # E   3. SELECT "posthog_grouptypemapping"."id", "posthog_grouptypemapping"."team_id", -- a.k.a get group type mappings

            # E   6. SET LOCAL statement_timeout = 600
            # E   7. SELECT (UPPER(("posthog_group"."group_properties" ->> 'email')::text) AS "flag_182_condition_0" FROM "posthog_group" -- a.k.a get group0 conditions
            # E   8. SELECT (true) AS "flag_181_condition_0" FROM "posthog_group" WHERE ("posthog_group"."team_id" = 91 -- a.k.a get group1 conditions
            response = self._post_decide(
                distinct_id="example_id",
                groups={"organization": "foo", "project": "bar"},
            )
            self.assertEqual(
                response.json()["featureFlags"],
                {"groups-flag": True, "default-no-prop-group-flag": True},
            )
            self.assertFalse(response.json()["errorsWhileComputingFlags"])

    def test_site_apps_in_decide_use_replica(
        self,
    ):
        org, team, user = self.setup_user_and_team_in_db("default")
        self.organization, self.team, self.user = org, team, user

        plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
        PluginSourceFile.objects.create(
            plugin=plugin,
            filename="site.ts",
            source="export function inject (){}",
            transpiled="function inject(){}",
            status=PluginSourceFile.Status.TRANSPILED,
        )
        PluginConfig.objects.create(
            plugin=plugin,
            enabled=True,
            order=1,
            team=self.team,
            config={},
            web_token="tokentoken",
        )
        sync_team_inject_web_apps(self.team)

        # update caches
        self._post_decide(api_version=3)

        with self.assertNumQueries(4, using="replica"), self.assertNumQueries(0, using="default"):
            response = self._post_decide(api_version=3)
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            injected = response.json()["siteApps"]
            self.assertEqual(len(injected), 1)

    # Adding local evaluation tests for read replica in one place for now, until we move to a separate CI flow for all read replica tests
    # since code-level overrides don't work for theses tests, as they affect the DATABASES setting
    @patch("posthog.api.feature_flag.report_user_action")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_local_evaluation(self, mock_rate_limit, mock_capture):
        org, team, user = self.setup_user_and_team_in_db("replica")
        self.organization, self.team, self.user = org, team, user

        FeatureFlag.objects.all().delete()
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

        client = APIClient()
        client.force_login(self.user)

        client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )

        client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 21}],
                },
            },
            format="json",
        )

        # old style feature flags
        FeatureFlag.objects.create(
            name="Beta feature",
            key="beta-feature",
            team=self.team,
            rollout_percentage=51,
            filters={"properties": [{"key": "beta-property", "value": "beta-value"}]},
            created_by=self.user,
        )
        # and inactive flag
        FeatureFlag.objects.create(
            name="Inactive feature",
            key="inactive-flag",
            team=self.team,
            active=False,
            rollout_percentage=100,
            filters={"properties": []},
            created_by=self.user,
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        client.logout()
        self.client.logout()
        cache.clear()

        # `local_evaluation` is called by logged out clients!

        # missing API key
        with self.assertNumQueries(0, using="replica"), self.assertNumQueries(0, using="default"):
            response = self.client.get(f"/api/feature_flag/local_evaluation?token={self.team.api_token}")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        with self.assertNumQueries(0, using="replica"), self.assertNumQueries(0, using="default"):
            response = self.client.get(f"/api/feature_flag/local_evaluation")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        with self.assertNumQueries(3, using="replica"), self.assertNumQueries(9, using="default"):
            # Captured queries for write DB:
            # E   1. UPDATE "posthog_personalapikey" SET "last_used_at" = '2023-08-01T11:26:50.728057+00:00'
            # E   2. SELECT "posthog_team"."id", "posthog_team"."uuid", "posthog_team"."organization_id"
            # E   3. SELECT "posthog_organizationmembership"."id", "posthog_organizationmembership"."organization_id", - user org permissions check
            # Captured queries for replica DB:
            # E   1. SELECT "posthog_personalapikey"."id", "posthog_personalapikey"."user_id", "posthog_personalapikey"."label", "posthog_personalapikey"."value", -- check API key, joined with user
            # E   2. SELECT "posthog_featureflag"."id", "posthog_featureflag"."key", "posthog_featureflag"."name", "posthog_featureflag"."filters", -- get flags
            # E   3. SELECT "posthog_grouptypemapping"."id", "posthog_grouptypemapping"."team_id", -- get groups

            response = self.client.get(
                f"/api/feature_flag/local_evaluation?token={self.team.api_token}",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertTrue("flags" in response_data and "group_type_mapping" in response_data)
        self.assertEqual(len(response_data["flags"]), 4)

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 20}],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[0],
        )
        self.assertDictContainsSubset(
            {
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [{"key": "beta-property", "value": "beta-value"}],
                            "rollout_percentage": 51,
                        }
                    ]
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[1],
        )
        self.assertDictContainsSubset(
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {
                    "groups": [{"rollout_percentage": 21}],
                    "aggregation_group_type_index": 0,
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[2],
        )

        self.assertDictContainsSubset(
            {
                "name": "Inactive feature",
                "key": "inactive-flag",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "deleted": False,
                "active": False,
                "ensure_experience_continuity": False,
            },
            sorted_flags[3],
        )

        self.assertEqual(response_data["group_type_mapping"], {"0": "organization", "1": "company"})

    @patch("posthog.api.feature_flag.report_user_action")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_local_evaluation_for_cohorts(self, mock_rate_limit, mock_capture):
        FeatureFlag.objects.all().delete()

        org, team, user = self.setup_user_and_team_in_db("replica")
        self.organization, self.team, self.user = org, team, user

        client = APIClient()
        client.force_login(self.user)

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        other_cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )

        Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2 -unrelated",
        )

        client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )
        client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": other_cohort1.pk,
                                }
                            ],
                        }
                    ],
                },
            },
            format="json",
        )

        client.logout()
        self.client.logout()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))
        cache.clear()

        with self.assertNumQueries(4, using="replica"), self.assertNumQueries(9, using="default"):
            # Captured queries for write DB:
            # E   1. UPDATE "posthog_personalapikey" SET "last_used_at" = '2023-08-01T11:26:50.728057+00:00'
            # E   2. SELECT "posthog_team"."id", "posthog_team"."uuid", "posthog_team"."organization_id"
            # E   3. SELECT "posthog_organizationmembership"."id", "posthog_organizationmembership"."organization_id", - user org permissions check
            # Captured queries for replica DB:
            # E   1. SELECT "posthog_personalapikey"."id", "posthog_personalapikey"."user_id", "posthog_personalapikey"."label", "posthog_personalapikey"."value", -- check API key, joined with user
            # E   2. SELECT "posthog_featureflag"."id", "posthog_featureflag"."key", "posthog_featureflag"."name", "posthog_featureflag"."filters", -- get flags
            # E   3. SELECT "posthog_cohort"."id", "posthog_cohort"."name", "posthog_cohort"."description", -- select all cohorts
            # E   5. SELECT "posthog_grouptypemapping"."id", "posthog_grouptypemapping"."team_id", -- get groups

            response = self.client.get(
                f"/api/feature_flag/local_evaluation?token={self.team.api_token}&send_cohorts",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertTrue(
                "flags" in response_data and "group_type_mapping" in response_data and "cohorts" in response_data
            )
            self.assertEqual(len(response_data["flags"]), 2)

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                            "rollout_percentage": 20,
                        },
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[0],
        )

        self.assertDictContainsSubset(
            {
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": other_cohort1.pk,
                                }
                            ],
                            "rollout_percentage": 20,
                        },
                    ],
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[1],
        )

        # When send_cohorts is true, no transformations happen, so all relevant cohorts are returned
        self.assertEqual(
            response_data["cohorts"],
            {
                str(cohort_valid_for_ff.pk): {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                },
                                {
                                    "key": "$some_prop2",
                                    "type": "person",
                                    "value": "nomatchihope2",
                                },
                            ],
                        }
                    ],
                },
                str(other_cohort1.pk): {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                },
                            ],
                        }
                    ],
                },
            },
        )

    @patch("posthog.api.feature_flag.report_user_action")
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_local_evaluation_for_arbitrary_cohorts(self, mock_rate_limit, mock_capture):
        FeatureFlag.objects.all().delete()

        org, team, user = self.setup_user_and_team_in_db("replica")
        self.organization, self.team, self.user = org, team, user

        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "value": "nomatchihope",
                                    "type": "person",
                                },
                                {
                                    "key": "$some_prop2",
                                    "value": "nomatchihope2",
                                    "type": "person",
                                },
                                {
                                    "key": "id",
                                    "value": cohort_valid_for_ff.pk,
                                    "type": "cohort",
                                    "negation": True,
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )

        client = APIClient()
        client.force_login(self.user)
        client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort2.pk}],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
            },
            format="json",
        )

        client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature-2",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                        }
                    ],
                },
            },
            format="json",
        )

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="X", user=self.user, secure_value=hash_key_value(personal_api_key))

        client.logout()
        self.client.logout()

        with self.assertNumQueries(4, using="replica"), self.assertNumQueries(9, using="default"):
            # Captured queries for write DB:
            # E   1. UPDATE "posthog_personalapikey" SET "last_used_at" = '2023-08-01T11:26:50.728057+00:00'
            # E   2. SELECT "posthog_team"."id", "posthog_team"."uuid", "posthog_team"."organization_id"
            # E   3. SELECT "posthog_organizationmembership"."id", "posthog_organizationmembership"."organization_id", - user org permissions check
            # Captured queries for replica DB:
            # E   1. SELECT "posthog_personalapikey"."id", "posthog_personalapikey"."user_id", "posthog_personalapikey"."label", "posthog_personalapikey"."value", -- check API key, joined with user
            # E   2. SELECT feature flags
            # E   3. SELECT "posthog_cohort"."id", "posthog_cohort"."name", "posthog_cohort"."description", -- select all cohorts
            # E   5. SELECT "posthog_grouptypemapping"."id", "posthog_grouptypemapping"."team_id", -- get groups

            response = self.client.get(
                f"/api/feature_flag/local_evaluation?token={self.team.api_token}&send_cohorts",
                HTTP_AUTHORIZATION=f"Bearer {personal_api_key}",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            response_data = response.json()
            self.assertTrue(
                "flags" in response_data and "group_type_mapping" in response_data and "cohorts" in response_data
            )
            self.assertEqual(len(response_data["flags"]), 2)

        sorted_flags = sorted(response_data["flags"], key=lambda x: x["key"])

        self.assertEqual(
            response_data["cohorts"],
            {
                str(cohort_valid_for_ff.pk): {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                },
                                {
                                    "key": "$some_prop2",
                                    "type": "person",
                                    "value": "nomatchihope2",
                                },
                            ],
                        }
                    ],
                },
                str(cohort2.pk): {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "$some_prop",
                                    "type": "person",
                                    "value": "nomatchihope",
                                },
                                {
                                    "key": "$some_prop2",
                                    "type": "person",
                                    "value": "nomatchihope2",
                                },
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                    "negation": True,
                                },
                            ],
                        }
                    ],
                },
            },
        )

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 20,
                            "properties": [{"key": "id", "type": "cohort", "value": cohort2.pk}],
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {
                                "key": "first-variant",
                                "name": "First Variant",
                                "rollout_percentage": 50,
                            },
                            {
                                "key": "second-variant",
                                "name": "Second Variant",
                                "rollout_percentage": 25,
                            },
                            {
                                "key": "third-variant",
                                "name": "Third Variant",
                                "rollout_percentage": 25,
                            },
                        ]
                    },
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[0],
        )

        self.assertDictContainsSubset(
            {
                "name": "Alpha feature",
                "key": "alpha-feature-2",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_valid_for_ff.pk,
                                }
                            ],
                            "rollout_percentage": 20,
                        },
                    ],
                },
                "deleted": False,
                "active": True,
                "ensure_experience_continuity": False,
            },
            sorted_flags[1],
        )


class TestDecideMetricLabel(TestCase):
    def test_simple_team_ids(self):
        with self.settings(DECIDE_TRACK_TEAM_IDS=["1", "2", "3"]):
            self.assertEqual(label_for_team_id_to_track(3), "3")
            self.assertEqual(label_for_team_id_to_track(2), "2")
            self.assertEqual(label_for_team_id_to_track(1), "1")
            self.assertEqual(label_for_team_id_to_track(0), "unknown")
            self.assertEqual(label_for_team_id_to_track(4), "unknown")
            self.assertEqual(label_for_team_id_to_track(40), "unknown")
            self.assertEqual(label_for_team_id_to_track(10), "unknown")
            self.assertEqual(label_for_team_id_to_track(20), "unknown")
            self.assertEqual(label_for_team_id_to_track(31), "unknown")

    def test_all_team_ids(self):
        with self.settings(DECIDE_TRACK_TEAM_IDS=["1", "2", "3", "all"]):
            self.assertEqual(label_for_team_id_to_track(3), "3")
            self.assertEqual(label_for_team_id_to_track(2), "2")
            self.assertEqual(label_for_team_id_to_track(1), "1")
            self.assertEqual(label_for_team_id_to_track(0), "0")
            self.assertEqual(label_for_team_id_to_track(4), "4")
            self.assertEqual(label_for_team_id_to_track(40), "40")
            self.assertEqual(label_for_team_id_to_track(10), "10")
            self.assertEqual(label_for_team_id_to_track(20), "20")
            self.assertEqual(label_for_team_id_to_track(31), "31")

    def test_range_team_ids(self):
        with self.settings(DECIDE_TRACK_TEAM_IDS=["1", "2", "1:3", "10:20", "30:40"]):
            self.assertEqual(label_for_team_id_to_track(3), "3")
            self.assertEqual(label_for_team_id_to_track(2), "2")
            self.assertEqual(label_for_team_id_to_track(1), "1")
            self.assertEqual(label_for_team_id_to_track(0), "unknown")
            self.assertEqual(label_for_team_id_to_track(4), "unknown")
            self.assertEqual(label_for_team_id_to_track(40), "40")
            self.assertEqual(label_for_team_id_to_track(41), "unknown")
            self.assertEqual(label_for_team_id_to_track(10), "10")
            self.assertEqual(label_for_team_id_to_track(9), "unknown")
            self.assertEqual(label_for_team_id_to_track(20), "20")
            self.assertEqual(label_for_team_id_to_track(25), "unknown")
            self.assertEqual(label_for_team_id_to_track(31), "31")


class TestDecideExceptions(TestCase):
    @patch("posthog.api.decide.capture_exception")
    @patch("posthog.api.decide.load_data_from_request")
    def test_unspecified_compression_fallback_parsing_error(self, mock_load_data, mock_capture_exception):
        mock_load_data.side_effect = UnspecifiedCompressionFallbackParsingError("Test error")

        request = HttpRequest()
        request.method = "POST"

        response = get_decide(request)

        self.assertEqual(response.status_code, 400)
        mock_capture_exception.assert_not_called()

    @patch("posthog.api.decide.capture_exception")
    @patch("posthog.api.decide.load_data_from_request")
    def test_request_parsing_error(self, mock_load_data, mock_capture_exception):
        mock_load_data.side_effect = RequestParsingError("Test error")

        request = HttpRequest()
        request.method = "POST"

        response = get_decide(request)

        self.assertEqual(response.status_code, 400)
        mock_capture_exception.assert_called_once()
