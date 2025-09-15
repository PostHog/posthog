from posthog.test.base import APIBaseTest, FuzzyInt, QueryMatchingTest
from unittest.mock import patch

from django.core.cache import cache

from inline_snapshot import snapshot
from rest_framework import status

# The remote config stuff plus plugin and hog function queries
CONFIG_REFRESH_QUERY_COUNT = 5


class TestRemoteConfig(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.client.logout()

        self.team.recording_domains = ["https://*.example.com"]
        self.team.session_recording_opt_in = True
        self.team.surveys_opt_in = True
        self.team.save()

        # Force synchronous RemoteConfig creation for tests since signals are async now
        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        try:
            RemoteConfig.objects.get(team=self.team)
        except RemoteConfig.DoesNotExist:
            update_team_remote_config(self.team.id)

        cache.clear()

    def test_missing_tokens(self):
        with self.assertNumQueries(FuzzyInt(1, 3)):
            response = self.client.get("/array/missing/config")
            assert response.status_code == status.HTTP_404_NOT_FOUND

        with self.assertNumQueries(0):
            response = self.client.get("/array/missing/config")
            assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_invalid_tokens(self):
        response = self.client.get("/array/§$%$&/config")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid token"

        response = self.client.get("/array/I-am_technically_v4lid/config")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_valid_config(self):
        # Not sure why but there is sometimes one extra query here
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(f"/array/{self.team.api_token}/config", HTTP_ORIGIN="https://foo.example.com")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/config", HTTP_ORIGIN="https://foo.example.com")

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/json"
        assert response.json() == snapshot(
            {
                "token": "token123",
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
                    "scriptConfig": None,
                    "triggerMatchType": None,
                },
                "errorTracking": {"autocaptureExceptions": False, "suppressionRules": []},
                "surveys": False,
                "heatmaps": False,
                "defaultIdentifiedOnly": True,
                "siteApps": [],
            }
        )

    def test_vary_header_response(self):
        response = self.client.get(f"/array/{self.team.api_token}/config", HTTP_ORIGIN="https://foo.example.com")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "Origin" in response.headers["Vary"]
        assert "Referer" in response.headers["Vary"]

    def test_different_response_for_other_domains(self):
        # Not sure why but there is sometimes one extra query here
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT, CONFIG_REFRESH_QUERY_COUNT + 2)):
            response = self.client.get(f"/array/{self.team.api_token}/config", HTTP_ORIGIN="https://foo.example.com")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["sessionRecording"]

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/config", HTTP_ORIGIN="https://foo.example.com")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["sessionRecording"]

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/config", HTTP_ORIGIN="https://bar.other.com")
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert not response.json()["sessionRecording"]

    def test_valid_config_js(self):
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT - 1, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(f"/array/{self.team.api_token}/config.js", HTTP_ORIGIN="https://foo.example.com")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/config.js", HTTP_ORIGIN="https://foo.example.com")

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/javascript"

        assert response.content == snapshot(
            b'(function() {\n  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};\n  window._POSTHOG_REMOTE_CONFIG[\'token123\'] = {\n    config: {"token": "token123", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},\n    siteApps: []\n  }\n})();'
        )

    @patch("posthog.models.remote_config.get_array_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_valid_array_js(self, mock_get_array_js_content):
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT - 1, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(f"/array/{self.team.api_token}/array.js", HTTP_ORIGIN="https://foo.example.com")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/array.js", HTTP_ORIGIN="https://foo.example.com")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/javascript"
        assert response.content

        assert response.content == snapshot(
            b'[MOCKED_ARRAY_JS_CONTENT]\n\n(function() {\n  window._POSTHOG_REMOTE_CONFIG = window._POSTHOG_REMOTE_CONFIG || {};\n  window._POSTHOG_REMOTE_CONFIG[\'token123\'] = {\n    config: {"token": "token123", "supportedCompression": ["gzip", "gzip-js"], "hasFeatureFlags": false, "captureDeadClicks": false, "capturePerformance": {"network_timing": true, "web_vitals": false, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "autocaptureExceptions": false, "analytics": {"endpoint": "/i/v0/e/"}, "elementsChainAsString": true, "errorTracking": {"autocaptureExceptions": false, "suppressionRules": []}, "sessionRecording": {"endpoint": "/s/", "consoleLogRecordingEnabled": true, "recorderVersion": "v2", "sampleRate": null, "minimumDurationMilliseconds": null, "linkedFlag": null, "networkPayloadCapture": null, "masking": null, "urlTriggers": [], "urlBlocklist": [], "eventTriggers": [], "triggerMatchType": null, "scriptConfig": null}, "heatmaps": false, "surveys": false, "defaultIdentifiedOnly": true},\n    siteApps: []\n  }\n})();'
        )

        # NOT actually testing the content here as it will change dynamically

    @patch("posthog.models.remote_config.get_array_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_valid_array_uses_config_js_cache(self, mock_get_array_js_content):
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(f"/array/{self.team.api_token}/config.js", HTTP_ORIGIN="https://foo.example.com")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/array.js", HTTP_ORIGIN="https://foo.example.com")
        assert response.status_code == status.HTTP_200_OK
