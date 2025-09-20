import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from rest_framework import status

from posthog.api.wizard.http import SETUP_WIZARD_CACHE_PREFIX, SETUP_WIZARD_CACHE_TIMEOUT
from posthog.cloud_utils import get_api_host
from posthog.models import Organization, User


class SetupWizardTests(APIBaseTest):
    def setUp(self):
        self.initialize_url = reverse("wizard-initialize")
        self.data_url = reverse("wizard-data")
        self.query_url = reverse("wizard-query")
        self.hash = "testhash"
        self.cache_key = f"{SETUP_WIZARD_CACHE_PREFIX}{self.hash}"
        cache.set(
            self.cache_key, {"project_api_key": "test-key", "host": "http://localhost:8010"}, SETUP_WIZARD_CACHE_TIMEOUT
        )

    def test_initialize_creates_hash(self):
        response = self.client.post(self.initialize_url)
        assert response.status_code == status.HTTP_200_OK
        assert "hash" in response.data

    def test_data_endpoint_requires_hash_header(self):
        response = self.client.get(self.data_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_data_endpoint_returns_data(self):
        response = self.client.get(self.data_url, HTTP_X_POSTHOG_WIZARD_HASH=self.hash)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["project_api_key"] == "test-key"
        assert response.data["host"] == "http://localhost:8010"

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_requires_hash_header(self, mock_openai):
        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}
            ),
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    @patch("django.conf.settings.DEBUG", False)
    def test_query_endpoint_rate_limit(self, mock_openai):
        mock_openai_instance = mock_openai.return_value
        # Simulate an OpenAI response with JSON {"foo": "bar"}
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"foo": "bar"})))]
        )

        for _ in range(20):  # Limit taken from rate_limit.py
            response = self.client.post(
                self.query_url,
                data=json.dumps(
                    {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}
                ),
                content_type="application/json",
                HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
            )
            assert response.status_code == status.HTTP_200_OK

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_invalid_hash(self, mock_openai):
        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH="invalidhash",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint(self, mock_openai):
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"foo": "bar"})))]
        )

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "number"}}}}
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"foo": "bar"}}

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_uses_default_model(self, mock_openai):
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"result": "success"})))]
        )

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test message",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "success"}}

        mock_openai_instance.chat.completions.create.assert_called_once()

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_accepts_valid_openai_model(self, mock_openai):
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"result": "openai_success"})))]
        )

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test message",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                    "model": "o4-mini",
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "openai_success"}}
        mock_openai_instance.chat.completions.create.assert_called_once()

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.genai.Client")
    @patch("django.conf.settings.GEMINI_API_KEY", "test-key")
    def test_query_endpoint_accepts_valid_gemini_model(self, mock_genai_client):
        mock_client_instance = mock_genai_client.return_value
        mock_response = MagicMock()
        mock_response.parsed = {"result": "gemini_success"}
        mock_client_instance.models.generate_content.return_value = mock_response

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test message",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                    "model": "gemini-2.5-flash",
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "gemini_success"}}
        mock_client_instance.models.generate_content.assert_called_once()

    def test_query_endpoint_rejects_invalid_model(self):
        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test message",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                    "model": "invalid-model",
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "model" in response.json()
        assert "not supported" in response.json()["model"][0]

    @patch("django.conf.settings.DEBUG", True)
    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_mock_wizard_data_in_debug_with_fixture_header(self, mock_openai):
        """Test that mock wizard data is used when DEBUG=True and X-PostHog-Wizard-Fixture-Generation header is present"""
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"result": "mocked"})))]
        )

        # Clear any existing cache data
        cache.delete(self.cache_key)

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
            HTTP_X_POSTHOG_WIZARD_FIXTURE_GENERATION="true",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "mocked"}}

        # Verify that mock data was cached
        cached_data = cache.get(self.cache_key)
        assert cached_data is not None
        assert cached_data["project_api_key"] == "mock-project-api-key"
        assert cached_data["host"] == "http://localhost:8010"
        assert cached_data["user_distinct_id"] == "mock-user-id"

    @patch("django.conf.settings.DEBUG", True)
    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_mock_wizard_data_overrides_existing_cache(self, mock_openai):
        """Test that mock wizard data overrides existing cache data when conditions are met"""
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"result": "overridden"})))]
        )

        # Set existing cache data
        cache.set(
            self.cache_key, {"project_api_key": "real-key", "host": "https://real-host.com"}, SETUP_WIZARD_CACHE_TIMEOUT
        )

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
            HTTP_X_POSTHOG_WIZARD_FIXTURE_GENERATION="true",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "overridden"}}

        # Verify that cache was overridden with mock data
        cached_data = cache.get(self.cache_key)
        assert cached_data["project_api_key"] == "mock-project-api-key"
        assert cached_data["host"] == "http://localhost:8010"
        assert cached_data["user_distinct_id"] == "mock-user-id"

    @patch("django.conf.settings.DEBUG", False)
    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_no_mock_when_debug_false(self, mock_openai):
        """Test that mock wizard data is NOT used when DEBUG=False even with fixture header"""
        # Clear any existing cache data
        cache.delete(self.cache_key)

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
            HTTP_X_POSTHOG_WIZARD_FIXTURE_GENERATION="true",
        )

        # Should fail authentication because no cache data exists and mock is not used
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("django.conf.settings.DEBUG", True)
    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_no_mock_without_fixture_header(self, mock_openai):
        """Test that mock wizard data is NOT used when DEBUG=True but fixture header is missing"""
        # Clear any existing cache data
        cache.delete(self.cache_key)

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {
                    "message": "test",
                    "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                }
            ),
            content_type="application/json",
            HTTP_X_POSTHOG_WIZARD_HASH=self.hash,
        )

        # Should fail authentication because no cache data exists and mock is not used
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_authenticate_requires_hash(self):
        response = self.client.post(f"/api/wizard/authenticate", data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_authenticate_invalid_hash(self):
        response = self.client.post(
            f"/api/wizard/authenticate",
            data={"hash": "nonexistent", "projectId": self.team.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_authenticate_missing_projectId(self):
        response = self.client.post(
            f"/api/wizard/authenticate",
            data={"hash": "valid_hash"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_authenticate_invalid_projectId(self):
        response = self.client.post(
            f"/api/wizard/authenticate",
            data={"hash": "valid_hash", "projectId": 999999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_authenticate_successful(self):
        self.client.force_login(self.user)
        cache_key = f"{SETUP_WIZARD_CACHE_PREFIX}valid_hash"
        cache.set(cache_key, {}, SETUP_WIZARD_CACHE_TIMEOUT)

        response = self.client.post(
            f"/api/wizard/authenticate",
            data={"hash": "valid_hash", "projectId": self.team.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"success": True})

        updated_data = cache.get(cache_key)
        self.assertIsNotNone(updated_data)
        self.assertEqual(updated_data["project_api_key"], self.team.api_token)
        self.assertEqual(updated_data["host"], get_api_host())
        self.assertEqual(updated_data["user_distinct_id"], self.user.distinct_id)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    @patch("posthog.rate_limit.SetupWizardAuthenticationRateThrottle.rate", new="2/day")
    def test_authenticate_rate_limited(self):
        self.client.force_login(self.user)
        cache_key = f"{SETUP_WIZARD_CACHE_PREFIX}valid_hash"
        cache.set(cache_key, {}, SETUP_WIZARD_CACHE_TIMEOUT)

        url = f"/api/wizard/authenticate"
        data = {"hash": "valid_hash", "projectId": self.team.id}

        response_1 = self.client.post(url, data=data, format="json")
        self.assertEqual(response_1.status_code, status.HTTP_200_OK)

        response_2 = self.client.post(url, data=data, format="json")
        self.assertEqual(response_2.status_code, status.HTTP_200_OK)

        response_3 = self.client.post(url, data=data, format="json")
        self.assertEqual(response_3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            },
        }
    )
    def test_authenticate_user_without_project_access(self):
        other_org = Organization.objects.create(name="Other Org")
        other_user = User.objects.create_and_join(other_org, "other@example.com", None)

        self.client.force_login(other_user)
        cache_key = f"{SETUP_WIZARD_CACHE_PREFIX}valid_hash"
        cache.set(cache_key, {}, SETUP_WIZARD_CACHE_TIMEOUT)

        url = f"/api/wizard/authenticate"
        data = {"hash": "valid_hash", "projectId": self.team.id}

        response = self.client.post(url, data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()
        self.assertEqual(response_data["code"], "permission_denied")
        self.assertEqual(response_data["detail"], "You don't have access to this project.")
        self.assertEqual(response_data["attr"], "projectId")

    def tearDown(self):
        super().tearDown()
        cache.clear()  # Clears out all DRF throttle data
