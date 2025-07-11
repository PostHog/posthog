from decimal import Decimal
from unittest.mock import patch

from parameterized import parameterized
from django.test import RequestFactory
from inline_snapshot import snapshot
import pytest
from posthog.models.action.action import Action
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.surveys.survey import Survey
from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionType
from posthog.models.plugin import Plugin, PluginConfig, PluginSourceFile
from posthog.models.project import Project
from posthog.models.remote_config import RemoteConfig, cache_key_for_team_token
from posthog.test.base import BaseTest
from django.core.cache import cache
from django.utils import timezone

CONFIG_REFRESH_QUERY_COUNT = 5


class _RemoteConfigBase(BaseTest):
    remote_config: RemoteConfig

    def setUp(self):
        super().setUp()

        project, team = Project.objects.create_with_team(
            initiating_user=self.user,
            organization=self.organization,
            name="Test project",
        )
        self.team = team
        self.team.api_token = "phc_12345"  # Easier to test against
        self.team.recording_domains = ["https://*.example.com"]
        self.team.session_recording_opt_in = True
        self.team.surveys_opt_in = True
        self.team.save()

        # There will always be a config thanks to the signal
        self.remote_config = RemoteConfig.objects.get(team=self.team)


class TestRemoteConfig(_RemoteConfigBase):
    def test_creates_remote_config_immediately(self):
        assert self.remote_config
        assert self.remote_config.updated_at
        assert self.remote_config.synced_at

        assert self.remote_config.config == snapshot(
            {
                "token": "phc_12345",
                "surveys": False,
                "heatmaps": False,
                "siteApps": [],
                "analytics": {"endpoint": "/i/v0/e/"},
                "siteAppsJS": [],
                "hasFeatureFlags": False,
                "sessionRecording": {
                    "domains": ["https://*.example.com"],
                    "endpoint": "/s/",
                    "linkedFlag": None,
                    "sampleRate": None,
                    "urlTriggers": [],
                    "scriptConfig": None,
                    "urlBlocklist": [],
                    "eventTriggers": [],
                    "triggerMatchType": None,
                    "recorderVersion": "v2",
                    "networkPayloadCapture": None,
                    "masking": None,
                    "consoleLogRecordingEnabled": True,
                    "minimumDurationMilliseconds": None,
                },
                "errorTracking": {
                    "autocaptureExceptions": False,
                    "suppressionRules": [],
                },
                "captureDeadClicks": False,
                "capturePerformance": {"web_vitals": False, "network_timing": True, "web_vitals_allowed_metrics": None},
                "autocapture_opt_out": False,
                "supportedCompression": ["gzip", "gzip-js"],
                "autocaptureExceptions": False,
                "defaultIdentifiedOnly": True,
                "elementsChainAsString": True,
            }
        )

    def test_indicates_if_feature_flags_exist(self):
        assert not self.remote_config.config["hasFeatureFlags"]

        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={},
            name="TestFlag",
            key="test-flag",
            created_by=self.user,
            deleted=True,
        )

        assert not self.remote_config.config["hasFeatureFlags"]
        flag.active = False
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert not self.remote_config.config["hasFeatureFlags"]
        flag.active = True
        flag.deleted = False
        flag.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["hasFeatureFlags"]

    def test_capture_dead_clicks_toggle(self):
        self.team.capture_dead_clicks = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["captureDeadClicks"]

    def test_capture_performance_toggle(self):
        self.team.capture_performance_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["capturePerformance"]["network_timing"]

    def test_autocapture_opt_out_toggle(self):
        self.team.autocapture_opt_out = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["autocapture_opt_out"]

    def test_autocapture_exceptions_toggle(self):
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["autocaptureExceptions"]

    @parameterized.expand([["1.00", None], ["0.95", "0.95"], ["0.50", "0.50"], ["0.00", "0.00"], [None, None]])
    def test_session_recording_sample_rate(self, value: str | None, expected: str | None) -> None:
        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = Decimal(value) if value else None
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["sessionRecording"]["sampleRate"] == expected

    def test_session_recording_domains(self):
        self.team.session_recording_opt_in = True
        self.team.recording_domains = ["https://posthog.com", "https://*.posthog.com"]
        self.team.save()
        self.remote_config.refresh_from_db()
        assert self.remote_config.config["sessionRecording"]["domains"] == self.team.recording_domains


class TestRemoteConfigSurveys(_RemoteConfigBase):
    # Largely copied from TestSurveysAPIList
    def setUp(self):
        super().setUp()

        self.team.save()

    def test_includes_survey_config(self):
        survey_appearance = {
            "thankYouMessageHeader": "Thanks for your feedback!",
            "thankYouMessageDescription": "We'll use it to make notebooks better",
        }

        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Basic survey",
            description="This should not be included",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=timezone.now(),
        )
        self.team.survey_config = {"appearance": survey_appearance}
        self.team.save()

        self.remote_config.refresh_from_db()
        assert self.remote_config.config["survey_config"] == snapshot(
            {
                "appearance": {
                    "thankYouMessageHeader": "Thanks for your feedback!",
                    "thankYouMessageDescription": "We'll use it to make notebooks better",
                }
            }
        )

    def test_includes_range_of_survey_types(self):
        survey_basic = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Basic survey",
            description="This should not be included",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=timezone.now(),
        )
        linked_flag = FeatureFlag.objects.create(team=self.team, key="linked-flag", created_by=self.user)
        targeting_flag = FeatureFlag.objects.create(team=self.team, key="targeting-flag", created_by=self.user)
        internal_targeting_flag = FeatureFlag.objects.create(
            team=self.team, key="custom-targeting-flag", created_by=self.user
        )

        survey_with_flags = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Survey with flags",
            type="popover",
            linked_flag=linked_flag,
            targeting_flag=targeting_flag,
            internal_targeting_flag=internal_targeting_flag,
            questions=[{"type": "open", "question": "What's a hedgehog?"}],
            start_date=timezone.now(),
        )

        action = Action.objects.create(
            team=self.team,
            name="user subscribed",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        survey_with_actions = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="survey with actions",
            type="popover",
            questions=[{"type": "open", "question": "Why's a hedgehog?"}],
            start_date=timezone.now(),
        )
        survey_with_actions.actions.set(Action.objects.filter(name="user subscribed"))
        survey_with_actions.save()

        self.remote_config.refresh_from_db()
        assert self.remote_config.config["surveys"]

        actual_surveys = sorted(self.remote_config.config["surveys"], key=lambda s: str(s["id"]))
        expected_surveys = sorted(
            [
                {
                    "id": str(survey_basic.id),
                    "name": "Basic survey",
                    "type": "popover",
                    "end_date": None,
                    "questions": [
                        {"id": str(survey_basic.questions[0]["id"]), "type": "open", "question": "What's a survey?"}
                    ],
                    "appearance": None,
                    "conditions": None,
                    "start_date": (
                        survey_basic.start_date.isoformat().replace("+00:00", "Z") if survey_basic.start_date else None
                    ),
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                    "schedule": "once",
                    "enable_partial_responses": False,
                },
                {
                    "id": str(survey_with_flags.id),
                    "name": "Survey with flags",
                    "type": "popover",
                    "end_date": None,
                    "questions": [
                        {
                            "id": str(survey_with_flags.questions[0]["id"]),
                            "type": "open",
                            "question": "What's a hedgehog?",
                        }
                    ],
                    "appearance": None,
                    "conditions": None,
                    "start_date": (
                        survey_with_flags.start_date.isoformat().replace("+00:00", "Z")
                        if survey_with_flags.start_date
                        else None
                    ),
                    "linked_flag_key": "linked-flag",
                    "current_iteration": None,
                    "targeting_flag_key": "targeting-flag",
                    "internal_targeting_flag_key": "custom-targeting-flag",
                    "current_iteration_start_date": None,
                    "schedule": "once",
                    "enable_partial_responses": False,
                },
                {
                    "id": str(survey_with_actions.id),
                    "name": "survey with actions",
                    "type": "popover",
                    "end_date": None,
                    "questions": [
                        {
                            "id": str(survey_with_actions.questions[0]["id"]),
                            "type": "open",
                            "question": "Why's a hedgehog?",
                        }
                    ],
                    "appearance": None,
                    "conditions": {
                        "actions": {
                            "values": [
                                {
                                    "id": action.id,
                                    "name": "user subscribed",
                                    "steps": [
                                        {
                                            "url": "docs",
                                            "href": None,
                                            "text": None,
                                            "event": "$pageview",
                                            "selector": None,
                                            "tag_name": None,
                                            "properties": None,
                                            "url_matching": "contains",
                                            "href_matching": None,
                                            "text_matching": None,
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                    "start_date": (
                        survey_with_actions.start_date.isoformat().replace("+00:00", "Z")
                        if survey_with_actions.start_date
                        else None
                    ),
                    "current_iteration": None,
                    "current_iteration_start_date": None,
                    "schedule": "once",
                    "enable_partial_responses": False,
                },
            ],
            key=lambda s: str(s["id"]),  # type: ignore
        )

        assert actual_surveys == expected_surveys


class TestRemoteConfigCaching(_RemoteConfigBase):
    def setUp(self):
        super().setUp()
        self.remote_config.refresh_from_db()
        # Clear the cache so we are properly testing each flow
        assert cache.delete(cache_key_for_team_token(self.team.api_token))

    def _assert_matches_config(self, data):
        assert data == snapshot(
            {
                "token": "phc_12345",
                "supportedCompression": ["gzip", "gzip-js"],
                "hasFeatureFlags": False,
                "captureDeadClicks": False,
                "capturePerformance": {"network_timing": True, "web_vitals": False, "web_vitals_allowed_metrics": None},
                "autocapture_opt_out": False,
                "autocaptureExceptions": False,
                "analytics": {"endpoint": "/i/v0/e/"},
                "elementsChainAsString": True,
                "sessionRecording": {
                    "endpoint": "/s/",
                    "consoleLogRecordingEnabled": True,
                    "recorderVersion": "v2",
                    "sampleRate": None,
                    "minimumDurationMilliseconds": None,
                    "linkedFlag": None,
                    "networkPayloadCapture": None,
                    "masking": None,
                    "urlTriggers": [],
                    "urlBlocklist": [],
                    "eventTriggers": [],
                    "triggerMatchType": None,
                    "scriptConfig": None,
                },
                "errorTracking": {
                    "autocaptureExceptions": False,
                    "suppressionRules": [],
                },
                "heatmaps": False,
                "surveys": False,
                "defaultIdentifiedOnly": True,
                "siteApps": [],
            }
        )

    def _assert_matches_config_js(self, data):
        assert data == snapshot(
            """\
(function() {
  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};
  window._POSTHOG_REMOTE_CONFIG['phc_12345'] = {
    config: {"token": "phc_12345", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},
    siteApps: []
  }
})();\
"""
        )

    def _assert_matches_config_array_js(self, data):
        assert data == snapshot(
            """\
[MOCKED_ARRAY_JS_CONTENT]

(function() {
  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};
  window._POSTHOG_REMOTE_CONFIG['phc_12345'] = {
    config: {"token": "phc_12345", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},
    siteApps: []
  }
})();\
"""
        )

    def test_syncs_if_changes(self):
        synced_at = self.remote_config.synced_at
        self.remote_config.config["surveys"] = True
        self.remote_config.sync()
        assert synced_at < self.remote_config.synced_at  # type: ignore

    def test_does_not_syncs_if_no_changes(self):
        synced_at = self.remote_config.synced_at
        self.remote_config.sync()
        assert synced_at == self.remote_config.synced_at

    def test_persists_data_to_redis_on_sync(self):
        self.remote_config.config["surveys"] = True
        self.remote_config.sync()
        assert cache.get(cache_key_for_team_token(self.team.api_token))

    def test_gets_via_redis_cache(self):
        with self.assertNumQueries(CONFIG_REFRESH_QUERY_COUNT):
            data = RemoteConfig.get_config_via_token(self.team.api_token)
            self._assert_matches_config(data)

        with self.assertNumQueries(0):
            data = RemoteConfig.get_config_via_token(self.team.api_token)
            self._assert_matches_config(data)

    def test_gets_js_via_redis_cache(self):
        with self.assertNumQueries(CONFIG_REFRESH_QUERY_COUNT):
            data = RemoteConfig.get_config_js_via_token(self.team.api_token)
            self._assert_matches_config_js(data)

        with self.assertNumQueries(0):
            data = RemoteConfig.get_config_js_via_token(self.team.api_token)
            self._assert_matches_config_js(data)

    def test_gets_js_reuses_config_cache(self):
        with self.assertNumQueries(CONFIG_REFRESH_QUERY_COUNT):
            RemoteConfig.get_config_via_token(self.team.api_token)

        with self.assertNumQueries(0):
            data = RemoteConfig.get_config_js_via_token(self.team.api_token)
            self._assert_matches_config_js(data)

    @patch("posthog.models.remote_config.get_array_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_gets_array_js_via_redis_cache(self, mock_get_array_js_content):
        with self.assertNumQueries(CONFIG_REFRESH_QUERY_COUNT):
            data = RemoteConfig.get_array_js_via_token(self.team.api_token)
            self._assert_matches_config_array_js(data)

        with self.assertNumQueries(0):
            data = RemoteConfig.get_array_js_via_token(self.team.api_token)
            self._assert_matches_config_array_js(data)

    def test_caches_missing_response(self):
        with self.assertNumQueries(1):
            with pytest.raises(RemoteConfig.DoesNotExist):
                RemoteConfig.get_array_js_via_token("missing-token")

        with self.assertNumQueries(0):
            with pytest.raises(RemoteConfig.DoesNotExist):
                RemoteConfig.get_array_js_via_token("missing-token")

    def test_sanitizes_config_for_public_cdn(self):
        config = self.remote_config.get_config_via_token(self.team.api_token)
        # Ensure the domain and siteAppsJS are removed
        assert config == snapshot(
            {
                "token": "phc_12345",
                "supportedCompression": ["gzip", "gzip-js"],
                "hasFeatureFlags": False,
                "captureDeadClicks": False,
                "capturePerformance": {"network_timing": True, "web_vitals": False, "web_vitals_allowed_metrics": None},
                "autocapture_opt_out": False,
                "autocaptureExceptions": False,
                "analytics": {"endpoint": "/i/v0/e/"},
                "elementsChainAsString": True,
                "sessionRecording": {
                    "endpoint": "/s/",
                    "consoleLogRecordingEnabled": True,
                    "recorderVersion": "v2",
                    "sampleRate": None,
                    "minimumDurationMilliseconds": None,
                    "linkedFlag": None,
                    "networkPayloadCapture": None,
                    "masking": None,
                    "urlTriggers": [],
                    "urlBlocklist": [],
                    "eventTriggers": [],
                    "triggerMatchType": None,
                    "scriptConfig": None,
                },
                "errorTracking": {
                    "autocaptureExceptions": False,
                    "suppressionRules": [],
                },
                "heatmaps": False,
                "surveys": False,
                "defaultIdentifiedOnly": True,
                "siteApps": [],
            }
        )

    def test_only_includes_recording_for_approved_domains(self):
        with self.assertNumQueries(CONFIG_REFRESH_QUERY_COUNT):
            mock_request = RequestFactory().get("/")
            mock_request.META["HTTP_ORIGIN"] = "https://my.example.com"
            config = self.remote_config.get_config_via_token(self.team.api_token, request=mock_request)
            assert config["sessionRecording"]

        # No additional queries should be needed to check the other domain
        with self.assertNumQueries(0):
            mock_request = RequestFactory().get("/")
            mock_request.META["HTTP_ORIGIN"] = "https://other.com"
            config = self.remote_config.get_config_via_token(self.team.api_token, request=mock_request)
            assert not config["sessionRecording"]

    @patch("posthog.models.remote_config.requests.post")
    def test_purges_cdn_cache_on_sync(self, mock_post):
        with self.settings(
            REMOTE_CONFIG_CDN_PURGE_ENDPOINT="https://api.cloudflare.com/client/v4/zones/MY_ZONE_ID/purge_cache",
            REMOTE_CONFIG_CDN_PURGE_TOKEN="MY_TOKEN",
            REMOTE_CONFIG_CDN_PURGE_DOMAINS=["cdn.posthog.com", "https://cdn2.posthog.com"],
        ):
            # Force a change to the config
            self.remote_config.config["token"] = "NOT"
            self.remote_config.sync()
            mock_post.assert_called_once_with(
                "https://api.cloudflare.com/client/v4/zones/MY_ZONE_ID/purge_cache",
                headers={"Authorization": "Bearer MY_TOKEN"},
                json={
                    "files": [
                        {"url": "https://cdn.posthog.com/array/phc_12345/config"},
                        {"url": "https://cdn.posthog.com/array/phc_12345/config.js"},
                        {"url": "https://cdn.posthog.com/array/phc_12345/array.js"},
                        {"url": "https://cdn2.posthog.com/array/phc_12345/config"},
                        {"url": "https://cdn2.posthog.com/array/phc_12345/config.js"},
                        {"url": "https://cdn2.posthog.com/array/phc_12345/array.js"},
                    ]
                },
            )


class TestRemoteConfigJS(_RemoteConfigBase):
    def test_renders_js_including_config(self):
        # NOTE: This is a very basic test to check that the JS is rendered correctly
        # It doesn't check the actual contents of the JS, as that changes often but checks some general things
        js = self.remote_config.get_config_js_via_token(self.team.api_token)

        # TODO: Come up with a good way of solidly testing this...
        assert js == snapshot(
            """\
(function() {
  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};
  window._POSTHOG_REMOTE_CONFIG['phc_12345'] = {
    config: {"token": "phc_12345", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},
    siteApps: []
  }
})();\
"""
        )

    def test_renders_js_including_site_apps(self):
        files = [
            "(function () { return { inject: (data) => console.log('injected!', data)}; })",
            "(function () { return { inject: (data) => console.log('injected 2!', data)}; })",
            "(function () { return { inject: (data) => console.log('injected but disabled!', data)}; })",
        ]

        plugin_configs = []

        for transpiled in files:
            plugin = Plugin.objects.create(organization=self.team.organization, name="My Plugin", plugin_type="source")
            PluginSourceFile.objects.create(
                plugin=plugin,
                filename="site.ts",
                source="IGNORED FOR TESTING",
                transpiled=transpiled,
                status=PluginSourceFile.Status.TRANSPILED,
            )
            plugin_configs.append(
                PluginConfig.objects.create(
                    plugin=plugin,
                    enabled=True,
                    order=1,
                    team=self.team,
                    config={},
                    web_token="tokentoken",
                )
            )

        plugin_configs[2].enabled = False

        js = self.remote_config.get_config_js_via_token(self.team.api_token)

        # TODO: Come up with a good way of solidly testing this, ideally by running it in an actual browser environment
        assert js == snapshot(
            """\
(function() {
  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};
  window._POSTHOG_REMOTE_CONFIG['phc_12345'] = {
    config: {"token": "phc_12345", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},
    siteApps: [    
    {
      id: 'tokentoken',
      init: function(config) {
            (function () { return { inject: (data) => console.log('injected!', data)}; })().inject({ config:{}, posthog:config.posthog });
        config.callback(); return {}  }
    },    
    {
      id: 'tokentoken',
      init: function(config) {
            (function () { return { inject: (data) => console.log('injected 2!', data)}; })().inject({ config:{}, posthog:config.posthog });
        config.callback(); return {}  }
    },    
    {
      id: 'tokentoken',
      init: function(config) {
            (function () { return { inject: (data) => console.log('injected but disabled!', data)}; })().inject({ config:{}, posthog:config.posthog });
        config.callback(); return {}  }
    }]
  }
})();\
"""  # noqa: W291, W293
        )

    def test_renders_js_including_site_functions(self):
        non_site_app = HogFunction.objects.create(
            name="Non site app",
            type=HogFunctionType.DESTINATION,
            team=self.team,
            enabled=True,
            filters={
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": True,
            },
        )

        site_destination = HogFunction.objects.create(
            name="Site destination",
            type=HogFunctionType.SITE_DESTINATION,
            team=self.team,
            enabled=True,
            filters={
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": True,
            },
        )

        site_app = HogFunction.objects.create(
            name="Site app",
            type=HogFunctionType.SITE_APP,
            team=self.team,
            enabled=True,
        )

        js = self.remote_config.get_config_js_via_token(self.team.api_token)
        assert str(non_site_app.id) not in js
        assert str(site_destination.id) in js
        assert str(site_app.id) in js

        js = js.replace(str(non_site_app.id), "NON_SITE_APP_ID")
        js = js.replace(str(site_destination.id), "SITE_DESTINATION_ID")
        js = js.replace(str(site_app.id), "SITE_APP_ID")

        # TODO: Come up with a good way of solidly testing this, ideally by running it in an actual browser environment
        assert js == snapshot(
            """\
(function() {
  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};
  window._POSTHOG_REMOTE_CONFIG['phc_12345'] = {
    config: {"token": "phc_12345", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},
    siteApps: [    
    {
      id: 'SITE_DESTINATION_ID',
      init: function(config) { return     (function() {
        function toString (value) { return __STLToString(value) }
        function match (str, pattern) { return !str || !pattern ? false : new RegExp(pattern).test(str) }
        function ilike (str, pattern) { return __like(str, pattern, true) }
        function __like(str, pattern, caseInsensitive = false) {
            if (caseInsensitive) {
                str = str.toLowerCase()
                pattern = pattern.toLowerCase()
            }
            pattern = String(pattern)
                .replaceAll(/[-/\\\\^$*+?.()|[\\]{}]/g, '\\\\$&')
                .replaceAll('%', '.*')
                .replaceAll('_', '.')
            return new RegExp(pattern).test(str)
        }
        function __getProperty(objectOrArray, key, nullish) {
            if ((nullish && !objectOrArray) || key === 0) { return null }
            if (Array.isArray(objectOrArray)) { return key > 0 ? objectOrArray[key - 1] : objectOrArray[objectOrArray.length + key] }
            else { return objectOrArray[key] }
        }
        function __STLToString(arg) {
            if (arg && __isHogDate(arg)) { return `${arg.year}-${arg.month.toString().padStart(2, '0')}-${arg.day.toString().padStart(2, '0')}`; }
            else if (arg && __isHogDateTime(arg)) { return __DateTimeToString(arg); }
            return __printHogStringOutput(arg); }
        function __printHogStringOutput(obj) { if (typeof obj === 'string') { return obj } return __printHogValue(obj) }
        function __printHogValue(obj, marked = new Set()) {
            if (typeof obj === 'object' && obj !== null && obj !== undefined) {
                if (marked.has(obj) && !__isHogDateTime(obj) && !__isHogDate(obj) && !__isHogError(obj)) { return 'null'; }
                marked.add(obj);
                try {
                    if (Array.isArray(obj)) {
                        if (obj.__isHogTuple) { return obj.length < 2 ? `tuple(${obj.map((o) => __printHogValue(o, marked)).join(', ')})` : `(${obj.map((o) => __printHogValue(o, marked)).join(', ')})`; }
                        return `[${obj.map((o) => __printHogValue(o, marked)).join(', ')}]`;
                    }
                    if (__isHogDateTime(obj)) { const millis = String(obj.dt); return `DateTime(${millis}${millis.includes('.') ? '' : '.0'}, ${__escapeString(obj.zone)})`; }
                    if (__isHogDate(obj)) return `Date(${obj.year}, ${obj.month}, ${obj.day})`;
                    if (__isHogError(obj)) { return `${String(obj.type)}(${__escapeString(obj.message)}${obj.payload ? `, ${__printHogValue(obj.payload, marked)}` : ''})`; }
                    if (obj instanceof Map) { return `{${Array.from(obj.entries()).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`; }
                    return `{${Object.entries(obj).map(([key, value]) => `${__printHogValue(key, marked)}: ${__printHogValue(value, marked)}`).join(', ')}}`;
                } finally {
                    marked.delete(obj);
                }
            } else if (typeof obj === 'boolean') return obj ? 'true' : 'false';
            else if (obj === null || obj === undefined) return 'null';
            else if (typeof obj === 'string') return __escapeString(obj);
                    if (typeof obj === 'function') return `fn<${__escapeIdentifier(obj.name || 'lambda')}(${obj.length})>`;
            return obj.toString();
        }
        function __isHogError(obj) {return obj && obj.__hogError__ === true}
        function __escapeString(value) {
            const singlequoteEscapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\', "'": "\\\\'" }
            return `'${value.split('').map((c) => singlequoteEscapeCharsMap[c] || c).join('')}'`;
        }
        function __escapeIdentifier(identifier) {
            const backquoteEscapeCharsMap = { '\\b': '\\\\b', '\\f': '\\\\f', '\\r': '\\\\r', '\\n': '\\\\n', '\\t': '\\\\t', '\\0': '\\\\0', '\\v': '\\\\v', '\\\\': '\\\\\\\\', '`': '\\\\`' }
            if (typeof identifier === 'number') return identifier.toString();
            if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(identifier)) return identifier;
            return `\\`${identifier.split('').map((c) => backquoteEscapeCharsMap[c] || c).join('')}\\``;
        }
        function __isHogDateTime(obj) { return obj && obj.__hogDateTime__ === true }
        function __isHogDate(obj) { return obj && obj.__hogDate__ === true }
        function __DateTimeToString(dt) {
            if (__isHogDateTime(dt)) {
                const date = new Date(dt.dt * 1000);
                const timeZone = dt.zone || 'UTC';
                const milliseconds = Math.floor(dt.dt * 1000 % 1000);
                const options = { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
                const formatter = new Intl.DateTimeFormat('en-US', options);
                const parts = formatter.formatToParts(date);
                let year, month, day, hour, minute, second;
                for (const part of parts) {
                    switch (part.type) {
                        case 'year': year = part.value; break;
                        case 'month': month = part.value; break;
                        case 'day': day = part.value; break;
                        case 'hour': hour = part.value; break;
                        case 'minute': minute = part.value; break;
                        case 'second': second = part.value; break;
                        default: break;
                    }
                }
                const getOffset = (date, timeZone) => {
                    const tzDate = new Date(date.toLocaleString('en-US', { timeZone }));
                    const utcDate = new Date(date.toLocaleString('en-US', { timeZone: 'UTC' }));
                    const offset = (tzDate - utcDate) / 60000; // in minutes
                    const sign = offset >= 0 ? '+' : '-';
                    const absOffset = Math.abs(offset);
                    const hours = Math.floor(absOffset / 60);
                    const minutes = absOffset % 60;
                    return `${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
                };
                let offset = 'Z';
                if (timeZone !== 'UTC') {
                    offset = getOffset(date, timeZone);
                }
                let isoString = `${year}-${month}-${day}T${hour}:${minute}:${second}`;
                isoString += `.${milliseconds.toString().padStart(3, '0')}`;
                isoString += offset;
                return isoString;
            }
        }
        function buildInputs(globals, initial) {
        let inputs = {
        };
        let __getGlobal = (key) => key === 'inputs' ? inputs : globals[key];
        return inputs;}
        const source = (function () {let exports={};"use strict";;return exports;})();
            let processEvent = undefined;
            if ('onEvent' in source) {
                processEvent = function processEvent(globals, posthog) {
                    if (!('onEvent' in source)) { return; };
                    const inputs = buildInputs(globals);
                    const filterGlobals = { ...globals.groups, ...globals.event, person: globals.person, inputs, pdi: { distinct_id: globals.event.distinct_id, person: globals.person } };
                    let __getGlobal = (key) => filterGlobals[key];
                    const filterMatches = !!(!!(!ilike(toString(__getProperty(__getProperty(__getGlobal("person"), "properties", true), "email", true)), "%@posthog.com%") && ((!match(toString(__getProperty(__getGlobal("properties"), "$host", true)), "^(localhost|127\\\\.0\\\\.0\\\\.1)($|:)")) ?? 1) && (__getGlobal("event") == "$pageview")));
                    if (!filterMatches) { return; }
                    ;
                }
            }
        
            function init(config) {
                const posthog = config.posthog;
                const callback = config.callback;
                if ('onLoad' in source) {
                    const globals = {
                        person: {
                            properties: posthog.get_property('$stored_person_properties'),
                        }
                    }
                    const r = source.onLoad({ inputs: buildInputs(globals, true), posthog: posthog });
                    if (r && typeof r.then === 'function' && typeof r.finally === 'function') { r.catch(() => callback(false)).then(() => callback(true)) } else { callback(true) }
                } else {
                    callback(true);
                }
        
                const response = {}
        
                if (processEvent) {
                    response.processEvent = (globals) => processEvent(globals, posthog)
                }
        
                return response
            }
        
            return { init: init };
        })().init(config) } 
    },    
    {
      id: 'SITE_APP_ID',
      init: function(config) { return     (function() {
        
        function buildInputs(globals, initial) {
        let inputs = {
        };
        let __getGlobal = (key) => key === 'inputs' ? inputs : globals[key];
        return inputs;}
        const source = (function () {let exports={};"use strict";;return exports;})();
            let processEvent = undefined;
            if ('onEvent' in source) {
                processEvent = function processEvent(globals, posthog) {
                    if (!('onEvent' in source)) { return; };
                    const inputs = buildInputs(globals);
                    const filterGlobals = { ...globals.groups, ...globals.event, person: globals.person, inputs, pdi: { distinct_id: globals.event.distinct_id, person: globals.person } };
                    let __getGlobal = (key) => filterGlobals[key];
                    const filterMatches = true;
                    if (!filterMatches) { return; }
                    ;
                }
            }
        
            function init(config) {
                const posthog = config.posthog;
                const callback = config.callback;
                if ('onLoad' in source) {
                    const globals = {
                        person: {
                            properties: posthog.get_property('$stored_person_properties'),
                        }
                    }
                    const r = source.onLoad({ inputs: buildInputs(globals, true), posthog: posthog });
                    if (r && typeof r.then === 'function' && typeof r.finally === 'function') { r.catch(() => callback(false)).then(() => callback(true)) } else { callback(true) }
                } else {
                    callback(true);
                }
        
                const response = {}
        
                if (processEvent) {
                    response.processEvent = (globals) => processEvent(globals, posthog)
                }
        
                return response
            }
        
            return { init: init };
        })().init(config) } 
    }]
  }
})();\
"""  # noqa: W291, W293
        )

    def test_removes_deleted_site_functions(self):
        site_destination = HogFunction.objects.create(
            name="Site destination",
            type=HogFunctionType.SITE_DESTINATION,
            team=self.team,
            enabled=True,
            filters={
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                "filter_test_accounts": True,
            },
        )

        js = self.remote_config.get_config_js_via_token(self.team.api_token)

        assert str(site_destination.id) in js

        site_destination.deleted = True
        site_destination.save()

        js = self.remote_config.get_config_js_via_token(self.team.api_token)
        assert str(site_destination.id) not in js
