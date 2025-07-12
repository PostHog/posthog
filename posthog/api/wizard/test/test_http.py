from unittest.mock import MagicMock, patch
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.core.cache import cache
from posthog.api.wizard.http import SETUP_WIZARD_CACHE_PREFIX, SETUP_WIZARD_CACHE_TIMEOUT
import json


class SetupWizardTests(APITestCase):
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

    def tearDown(self):
        super().tearDown()
        cache.clear()  # Clears out all DRF throttle data
