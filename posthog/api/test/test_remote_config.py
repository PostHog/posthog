from inline_snapshot import snapshot
from rest_framework import status
from django.core.cache import cache

from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestRemoteConfig(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.client.logout()

        cache.clear()

    def test_missing_tokens(self):
        with self.assertNumQueries(1):
            response = self.client.get("/array/missing/config")
            assert response.status_code == status.HTTP_404_NOT_FOUND

        with self.assertNumQueries(0):
            response = self.client.get("/array/missing/config")
            assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_invalid_tokens(self):
        response = self.client.get("/array/§$%$&----/config")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Invalid token"

    def test_valid_config(self):
        with self.assertNumQueries(2):
            response = self.client.get(f"/array/{self.team.api_token}/config")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/config")

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
                "sessionRecording": False,
                "surveys": False,
                "heatmaps": False,
                "defaultIdentifiedOnly": False,
                "siteApps": [],
            }
        )

    def test_valid_config_js(self):
        with self.assertNumQueries(3):
            response = self.client.get(f"/array/{self.team.api_token}/config.js")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/config.js")

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/javascript"
        assert response.content == snapshot(
            b'(function() {\n  window._POSTHOG_CONFIG = {"token": "token123", "surveys": false, "heatmaps": false, "siteApps": [], "analytics": {"endpoint": "/i/v0/e/"}, "hasFeatureFlags": false, "sessionRecording": false, "captureDeadClicks": false, "capturePerformance": {"web_vitals": false, "network_timing": true, "web_vitals_allowed_metrics": null}, "autocapture_opt_out": false, "supportedCompression": ["gzip", "gzip-js"], "autocaptureExceptions": false, "defaultIdentifiedOnly": false, "elementsChainAsString": true};\n  window._POSTHOG_JS_APPS = [];\n})();'
        )

    def test_valid_array_js(self):
        with self.assertNumQueries(3):
            response = self.client.get(f"/array/{self.team.api_token}/array.js")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/array.js")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/javascript"
        assert response.content

        # NOT actually testing the content here as it will change dynamically

    def test_valid_array_uses_config_js_cache(self):
        with self.assertNumQueries(3):
            response = self.client.get(f"/array/{self.team.api_token}/config.js")

        with self.assertNumQueries(0):
            response = self.client.get(f"/array/{self.team.api_token}/array.js")
        assert response.status_code == status.HTTP_200_OK
