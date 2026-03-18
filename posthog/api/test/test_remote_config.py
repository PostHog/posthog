from posthog.test.base import APIBaseTest, FuzzyInt, QueryMatchingTest
from unittest.mock import patch

from rest_framework import status

# The remote config stuff plus plugin and hog function queries
CONFIG_REFRESH_QUERY_COUNT = 5


class TestRemoteConfig(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.client.logout()

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

    @patch("posthog.models.remote_config.get_array_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
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

    @patch("posthog.models.remote_config.get_array_js_content", return_value="[MOCKED_ARRAY_JS_CONTENT]")
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
        self.team.session_recording_sample_rate = 0.5
        self.team.session_recording_event_trigger_config = ["pageview", "click"]
        self.team.session_recording_url_trigger_config = [{"url": "/checkout", "matching": "regex"}]
        self.team.session_recording_trigger_match_type_config = "any"
        self.team.session_recording_trigger_groups = None  # No v2 config
        self.team.save()

        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(f"/array/{self.team.api_token}/config")
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
        self.team.session_recording_trigger_groups = {
            "version": 2,
            "groups": [
                {
                    "id": "errors",
                    "name": "Error Tracking",
                    "sampleRate": 1.0,
                    "order": 0,
                    "conditions": {
                        "matchType": "any",
                        "events": ["error", "crash"],
                        "urls": [{"url": "/checkout.*", "matching": "regex"}],
                    },
                },
                {
                    "id": "feature-test",
                    "sampleRate": 0.5,
                    "order": 1,
                    "conditions": {
                        "matchType": "all",
                        "flags": ["new-feature"],
                    },
                },
            ],
            "groupEvaluationMode": "first_match",
            "fallbackSampleRate": 0.01,
        }
        # Clear legacy fields to ensure v2 is used
        self.team.session_recording_sample_rate = None
        self.team.session_recording_event_trigger_config = []
        self.team.save()

        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(f"/array/{self.team.api_token}/config")
        assert response.status_code == status.HTTP_200_OK

        config = response.json()
        assert config["sessionRecording"]["version"] == 2
        assert len(config["sessionRecording"]["triggerGroups"]) == 2
        assert config["sessionRecording"]["triggerGroups"][0]["id"] == "errors"
        assert config["sessionRecording"]["triggerGroups"][0]["sampleRate"] == 1.0
        assert config["sessionRecording"]["triggerGroups"][1]["id"] == "feature-test"
        assert config["sessionRecording"]["groupEvaluationMode"] == "first_match"
        assert config["sessionRecording"]["fallbackSampleRate"] == 0.01
        # V2 fields should be present
        assert "triggerGroups" in config["sessionRecording"]
        assert "groupEvaluationMode" in config["sessionRecording"]
        # V1 fields should NOT be present
        assert "sampleRate" not in config["sessionRecording"]
        assert "eventTriggers" not in config["sessionRecording"]
        assert "linkedFlag" not in config["sessionRecording"]
        assert "triggerMatchType" not in config["sessionRecording"]

    def test_session_recording_url_blocklist_in_both_versions(self):
        """Test that URL blocklist is included in both v1 and v2 configs"""
        url_blocklist = [{"url": "/admin.*", "matching": "regex"}, {"url": "/internal.*", "matching": "regex"}]
        self.team.session_recording_url_blocklist_config = url_blocklist

        # Test V1 (legacy)
        self.team.session_recording_sample_rate = 0.5
        self.team.session_recording_trigger_groups = None
        self.team.save()

        from posthog.models.remote_config import RemoteConfig
        from posthog.tasks.remote_config import update_team_remote_config

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(f"/array/{self.team.api_token}/config")
        assert response.status_code == status.HTTP_200_OK
        config_v1 = response.json()
        assert config_v1["sessionRecording"]["version"] == 1
        assert config_v1["sessionRecording"]["urlBlocklist"] == url_blocklist

        # Test V2 (trigger groups)
        self.team.session_recording_trigger_groups = {
            "version": 2,
            "groups": [{"id": "test", "sampleRate": 0.5, "order": 0, "conditions": {"matchType": "any"}}],
        }
        self.team.save()

        update_team_remote_config(self.team.id)
        RemoteConfig.get_hypercache().clear_cache(self.team.api_token)

        response = self.client.get(f"/array/{self.team.api_token}/config")
        assert response.status_code == status.HTTP_200_OK
        config_v2 = response.json()
        assert config_v2["sessionRecording"]["version"] == 2
        assert config_v2["sessionRecording"]["urlBlocklist"] == url_blocklist
