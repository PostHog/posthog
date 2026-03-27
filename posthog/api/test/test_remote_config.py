from decimal import Decimal

from posthog.test.base import APIBaseTest, FuzzyInt, QueryMatchingTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

# The remote config stuff plus plugin and hog function queries
CONFIG_REFRESH_QUERY_COUNT = 5


class TestRemoteConfig(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.client.logout()

        # Mock get_disk_js_hash to avoid reading frontend/dist/array.js (absent in CI)
        self._disk_hash_patcher = patch("posthog.models.remote_config.get_disk_js_hash", return_value="mocked_hash")
        self._disk_hash_patcher.start()

        self.team.recording_domains = ["https://*.example.com"]
        self.team.session_recording_opt_in = True
        self.team.surveys_opt_in = True
        self.team.extra_settings = {"recorder_script": "posthog-recorder"}
        self.team.save()

        # Force synchronous RemoteConfig creation for tests since signals are async now
        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        try:
            RemoteConfig.objects.get(team=self.team)
        except RemoteConfig.DoesNotExist:
            update_team_remote_config(self.team.id)

        # Clear the HyperCache (both Redis and S3) to properly test cache miss behavior
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

    def tearDown(self):
        self._disk_hash_patcher.stop()
        super().tearDown()

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
            response = self.client.get(
                f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
            )

        with self.assertNumQueries(0):
            response = self.client.get(
                f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/json"
        assert response.json() == self.snapshot

    def test_vary_header_response(self):
        response = self.client.get(
            f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert "Origin" in response.headers["Vary"]
        assert "Referer" in response.headers["Vary"]

    def test_different_response_for_other_domains(self):
        # Not sure why but there is sometimes one extra query here
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT, CONFIG_REFRESH_QUERY_COUNT + 2)):
            response = self.client.get(
                f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["sessionRecording"]

        with self.assertNumQueries(0):
            response = self.client.get(
                f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json()["sessionRecording"]

        with self.assertNumQueries(0):
            response = self.client.get(
                f"/array/{self.team.api_token}/config", headers={"origin": "https://bar.other.com"}
            )
            assert response.status_code == status.HTTP_200_OK, response.json()
            assert not response.json()["sessionRecording"]

    def test_valid_config_js(self):
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT - 1, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(
                f"/array/{self.team.api_token}/config.js", headers={"origin": "https://foo.example.com"}
            )

        with self.assertNumQueries(0):
            response = self.client.get(
                f"/array/{self.team.api_token}/config.js", headers={"origin": "https://foo.example.com"}
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/javascript"
        assert response.content == self.snapshot

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_valid_array_js(self, mock_get_array_js_content):
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT - 1, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(
                f"/array/{self.team.api_token}/array.js", headers={"origin": "https://foo.example.com"}
            )

        with self.assertNumQueries(0):
            response = self.client.get(
                f"/array/{self.team.api_token}/array.js", headers={"origin": "https://foo.example.com"}
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "application/javascript"
        assert response.content
        assert response.content == self.snapshot

        # NOT actually testing the content here as it will change dynamically

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_array_js_includes_cache_headers(self, mock_get_array_js_content):
        response = self.client.get(f"/array/{self.team.api_token}/array.js")
        assert response.status_code == status.HTTP_200_OK
        assert "ETag" in response.headers
        assert response.headers["ETag"].startswith('"') and response.headers["ETag"].endswith('"')
        assert (
            response.headers["Cache-Control"]
            == "public, max-age=3600, stale-while-revalidate=86400, stale-if-error=86400"
        )
        assert f"token:{self.team.api_token}" in response.headers["Cache-Tag"]
        assert "posthog-js-" in response.headers["Cache-Tag"]

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_array_js_returns_304_on_etag_match(self, mock_get_array_js_content):
        response = self.client.get(f"/array/{self.team.api_token}/array.js")
        etag = response.headers["ETag"]

        response = self.client.get(
            f"/array/{self.team.api_token}/array.js",
            HTTP_IF_NONE_MATCH=etag,
        )
        assert response.status_code == status.HTTP_304_NOT_MODIFIED
        assert response.headers["ETag"] == etag

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_array_js_returns_200_on_etag_mismatch(self, mock_get_array_js_content):
        response = self.client.get(
            f"/array/{self.team.api_token}/array.js",
            HTTP_IF_NONE_MATCH='"stale-etag"',
        )
        assert response.status_code == status.HTTP_200_OK

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT_V1]")
    def test_array_js_etag_changes_when_config_changes(self, mock_get_array_js_content):
        response1 = self.client.get(f"/array/{self.team.api_token}/array.js")
        etag1 = response1.headers["ETag"]

        # Change a team setting to force a different config hash
        from posthog.models.remote_config import RemoteConfig

        self.team.capture_dead_clicks = True
        self.team.save()
        remote_config = RemoteConfig.objects.get(team=self.team)
        remote_config.sync(force=True)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response2 = self.client.get(f"/array/{self.team.api_token}/array.js")
        etag2 = response2.headers["ETag"]

        assert etag1 != etag2

        # Old ETag should no longer produce a 304
        response3 = self.client.get(
            f"/array/{self.team.api_token}/array.js",
            HTTP_IF_NONE_MATCH=etag1,
        )
        assert response3.status_code == status.HTTP_200_OK

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_array_js_304_includes_cache_control(self, mock_get_array_js_content):
        response = self.client.get(f"/array/{self.team.api_token}/array.js")
        etag = response.headers["ETag"]

        response = self.client.get(
            f"/array/{self.team.api_token}/array.js",
            HTTP_IF_NONE_MATCH=etag,
        )
        assert response.status_code == status.HTTP_304_NOT_MODIFIED
        assert (
            response.headers["Cache-Control"]
            == "public, max-age=3600, stale-while-revalidate=86400, stale-if-error=86400"
        )

    @patch("posthog.models.remote_config.get_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
    def test_valid_array_uses_config_js_cache(self, mock_get_array_js_content):
        with self.assertNumQueries(FuzzyInt(CONFIG_REFRESH_QUERY_COUNT, CONFIG_REFRESH_QUERY_COUNT + 1)):
            response = self.client.get(
                f"/array/{self.team.api_token}/config.js", headers={"origin": "https://foo.example.com"}
            )

        with self.assertNumQueries(0):
            response = self.client.get(
                f"/array/{self.team.api_token}/array.js", headers={"origin": "https://foo.example.com"}
            )
        assert response.status_code == status.HTTP_200_OK

    def test_session_recording_v1_config(self):
        """Test that legacy session recording config returns v1 format"""
        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = Decimal("0.5")
        self.team.session_recording_event_trigger_config = ["pageview", "click"]
        self.team.session_recording_url_trigger_config = [{"url": "/checkout", "matching": "regex"}]
        self.team.session_recording_trigger_match_type_config = "any"
        self.team.session_recording_trigger_groups = None  # No v2 config
        self.team.save()

        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(
            f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
        )
        assert response.status_code == status.HTTP_200_OK

        config = response.json()
        assert config["sessionRecording"]["version"] == 1
        assert config["sessionRecording"]["sampleRate"] == "0.5"
        assert config["sessionRecording"]["eventTriggers"] == ["pageview", "click"]
        assert config["sessionRecording"]["urlTriggers"] == [{"url": "/checkout", "matching": "regex"}]
        assert config["sessionRecording"]["triggerMatchType"] == "any"
        # V1 fields should be present
        assert "sampleRate" in config["sessionRecording"]
        assert "eventTriggers" in config["sessionRecording"]
        # V2 fields should NOT be present
        assert "triggerGroups" not in config["sessionRecording"]
        assert "groupEvaluationMode" not in config["sessionRecording"]

    def test_session_recording_v2_config(self):
        """Test that trigger groups config returns v2 format"""
        self.team.session_recording_opt_in = True
        self.team.session_recording_trigger_groups = {
            "version": 2,
            "groups": [
                {
                    "id": "errors",
                    "name": "Error Tracking",
                    "sampleRate": 1.0,
                    "minDurationMs": 0,
                    "conditions": {
                        "matchType": "any",
                        "events": ["error", "crash"],
                        "urls": [{"url": "/checkout.*", "matching": "regex"}],
                    },
                },
                {
                    "id": "feature-test",
                    "sampleRate": 0.5,
                    "minDurationMs": 10000,
                    "conditions": {
                        "matchType": "all",
                        "flag": "new-feature",
                    },
                },
            ],
        }
        # Set V1 fields for backward compatibility fallback
        self.team.session_recording_sample_rate = Decimal("0.1")
        self.team.session_recording_event_trigger_config = []
        self.team.session_recording_url_trigger_config = []
        self.team.session_recording_trigger_match_type_config = None
        self.team.save()

        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(
            f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
        )
        assert response.status_code == status.HTTP_200_OK

        config = response.json()
        assert config["sessionRecording"]["version"] == 2
        assert len(config["sessionRecording"]["triggerGroups"]) == 2
        assert config["sessionRecording"]["triggerGroups"][0]["id"] == "errors"
        assert config["sessionRecording"]["triggerGroups"][0]["sampleRate"] == 1.0
        assert config["sessionRecording"]["triggerGroups"][0]["minDurationMs"] == 0
        assert config["sessionRecording"]["triggerGroups"][1]["id"] == "feature-test"
        assert config["sessionRecording"]["triggerGroups"][1]["minDurationMs"] == 10000
        # V2 fields should be present
        assert "triggerGroups" in config["sessionRecording"]
        # Removed fields should NOT be present
        assert "groupEvaluationMode" not in config["sessionRecording"]
        assert "fallbackSampleRate" not in config["sessionRecording"]
        # V1 fields SHOULD be present for backward compatibility with old SDKs
        assert config["sessionRecording"]["sampleRate"] == "0.1"
        assert config["sessionRecording"]["eventTriggers"] == []
        assert config["sessionRecording"]["linkedFlag"] is None
        assert config["sessionRecording"]["urlTriggers"] == []
        assert config["sessionRecording"]["triggerMatchType"] is None

    @parameterized.expand(
        [
            ("v1_no_trigger_groups", None, 1),
            (
                "v2_with_trigger_groups",
                {"version": 2, "groups": [{"id": "test", "sampleRate": 0.5, "conditions": {"matchType": "any"}}]},
                2,
            ),
        ],
    )
    def test_session_recording_url_blocklist_in_both_versions(self, _name, trigger_groups_config, expected_version):
        """Test that URL blocklist is included in both v1 and v2 configs"""
        url_blocklist = [{"url": "/admin.*", "matching": "regex"}, {"url": "/internal.*", "matching": "regex"}]

        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = Decimal("0.5")
        self.team.session_recording_url_blocklist_config = url_blocklist
        self.team.session_recording_trigger_groups = trigger_groups_config
        self.team.save()

        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(
            f"/array/{self.team.api_token}/config", headers={"origin": "https://foo.example.com"}
        )
        assert response.status_code == status.HTTP_200_OK

        config = response.json()
        assert config["sessionRecording"]["version"] == expected_version
        assert config["sessionRecording"]["urlBlocklist"] == url_blocklist
