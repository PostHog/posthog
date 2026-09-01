import json
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.wizard.http import SETUP_WIZARD_CACHE_PREFIX, SETUP_WIZARD_CACHE_TIMEOUT
from posthog.cloud_utils import get_api_host
from posthog.llm.wizard_gateway_token import WizardGatewayMintError
from posthog.models import Organization, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle, refund_wizard_mint, reserve_wizard_mint


class SetupWizardTests(APIBaseTest):
    def setUp(self):
        self.initialize_url = reverse("wizard-initialize")
        self.data_url = reverse("wizard-data")
        self.query_url = reverse("wizard-query")
        self.hash = "testhash"
        self.cache_key = f"{SETUP_WIZARD_CACHE_PREFIX}{self.hash}"
        cache.set(
            self.cache_key,
            {"project_api_key": "test-key", "host": "http://localhost:8010", "team_id": self.team.id},
            SETUP_WIZARD_CACHE_TIMEOUT,
        )

    def test_initialize_creates_hash(self):
        response = self.client.post(self.initialize_url)
        assert response.status_code == status.HTTP_200_OK
        assert "hash" in response.data

    def test_data_endpoint_requires_hash_header(self):
        response = self.client.get(self.data_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_data_endpoint_returns_data(self):
        response = self.client.get(self.data_url, headers={"x-posthog-wizard-hash": self.hash})
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
                headers={"x-posthog-wizard-hash": self.hash},
            )
            assert response.status_code == status.HTTP_200_OK

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}
            ),
            content_type="application/json",
            headers={"x-posthog-wizard-hash": self.hash},
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
            headers={"x-posthog-wizard-hash": "invalidhash"},
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
            headers={"x-posthog-wizard-hash": self.hash},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"foo": "bar"}}
        assert mock_openai_instance.chat.completions.create.call_args.kwargs["posthog_properties"] == {
            "ai_product": "wizard",
            "ai_feature": "query",
            "team_id": self.team.id,
        }

    @patch("posthog.api.wizard.http.posthoganalytics.default_client", MagicMock())
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    @patch("posthog.api.wizard.http.OpenAI")
    def test_query_endpoint_uses_oauth_scoped_team(self, mock_openai, mock_authentication):
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps({"foo": "bar"})))]
        )
        mock_authenticator = mock_authentication.return_value
        mock_authenticator.authenticate.return_value = (self.user, None)
        mock_authenticator.access_token.scoped_teams = [self.team.id]

        response = self.client.post(
            self.query_url,
            data=json.dumps(
                {"message": "test", "json_schema": {"type": "object", "properties": {"name": {"type": "number"}}}}
            ),
            content_type="application/json",
            headers={"authorization": "Bearer pha_test"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert mock_openai_instance.chat.completions.create.call_args.kwargs["posthog_properties"] == {
            "ai_product": "wizard",
            "ai_feature": "query",
            "team_id": self.team.id,
        }

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
            headers={"x-posthog-wizard-hash": self.hash},
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
            headers={"x-posthog-wizard-hash": self.hash},
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
            headers={"x-posthog-wizard-hash": self.hash},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "gemini_success"}}
        assert mock_client_instance.models.generate_content.call_args.kwargs["posthog_properties"] == {
            "ai_product": "wizard",
            "ai_feature": "query",
            "team_id": self.team.id,
        }

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
            headers={"x-posthog-wizard-hash": self.hash},
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
            headers={"x-posthog-wizard-hash": self.hash, "x-posthog-wizard-fixture-generation": "true"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "mocked"}}

        # Verify that mock data was cached
        cached_data = cache.get(self.cache_key)
        assert cached_data is not None
        assert cached_data["project_api_key"] == "mock-project-api-key"
        assert cached_data["host"] == "http://localhost:8010"
        assert cached_data["user_distinct_id"] == "mock-user-id"
        assert cached_data["team_id"] == 1

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
            headers={"x-posthog-wizard-hash": self.hash, "x-posthog-wizard-fixture-generation": "true"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"data": {"result": "overridden"}}

        # Verify that cache was overridden with mock data
        cached_data = cache.get(self.cache_key)
        assert cached_data["project_api_key"] == "mock-project-api-key"
        assert cached_data["host"] == "http://localhost:8010"
        assert cached_data["user_distinct_id"] == "mock-user-id"
        assert cached_data["team_id"] == 1

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
            headers={"x-posthog-wizard-hash": self.hash, "x-posthog-wizard-fixture-generation": "true"},
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
            headers={"x-posthog-wizard-hash": self.hash},
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
        self.assertEqual(updated_data["team_id"], self.team.id)

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


@override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="wizard-client-id")
class SetupWizardCloudRunTests(APIBaseTest):
    CLOUD_RUN_URL = "/api/wizard/cloud_run"

    @override_settings(WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID="")
    def test_returns_404_when_feature_not_configured(self):
        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_creates_run_and_returns_ids(self, mock_create):
        mock_create.return_value = MagicMock(task_id="task-uuid", latest_run=MagicMock(id="run-uuid", status="queued"))

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app", "branch": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"task_id": "task-uuid", "run_id": "run-uuid", "status": "queued"}
        assert mock_create.call_count == 1
        kwargs = mock_create.call_args.kwargs
        assert kwargs["repository"] == "acme/app"
        assert kwargs["user_id"] == self.user.id
        assert kwargs["branch"] is None
        assert kwargs["team"].id == self.team.id

    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_rejects_invalid_repository_format(self, mock_create):
        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "not-a-repo"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_create.assert_not_called()

    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_rejects_personal_api_key_auth(self, mock_create):
        # Cloud run is a UI/session-only action — an API token must not be able to start a run,
        # even with a broad scope, since the project visibility check below wouldn't honor token scopes.
        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Test API Key",
            secure_value=hash_key_value(api_key_value),
            scopes=["*"],
        )
        self.client.logout()

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
            headers={"authorization": f"Bearer {api_key_value}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_create.assert_not_called()

    def test_rejects_project_without_access(self):
        other_org = Organization.objects.create(name="Other Cloud Run Org")
        other_user = User.objects.create_and_join(other_org, "other-cloud-run@example.com", None)
        self.client.force_login(other_user)

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.tasks.backend.facade.api.recent_wizard_cloud_run_times")
    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_throttles_when_quota_counting_runs_reports_the_cap(self, mock_create, mock_run_times):
        # Wiring guard for the outcome-aware throttles: the endpoint must consult the facade's
        # run count (the exclusion behavior itself is covered in the tasks product's facade tests).
        mock_run_times.return_value = [timezone.now() - timedelta(minutes=5), timezone.now() - timedelta(minutes=1)]

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        mock_create.assert_not_called()

    @patch("posthog.api.wizard.http.WIZARD_CLOUD_RUN_DAILY_ATTEMPT_CAP", 2)
    @patch("products.tasks.backend.facade.api.recent_wizard_cloud_run_times")
    @patch("posthog.api.wizard.http.tasks_facade.create_wizard_cloud_run")
    def test_attempt_reservation_is_a_hard_ceiling_regardless_of_run_outcome(self, mock_create, mock_run_times):
        # The DB-counted throttles ignore failed/cancelled runs, so the atomic reservation is
        # the only thing bounding a start-fail or start-cancel loop.
        mock_run_times.return_value = []
        mock_create.return_value = MagicMock(task_id="task-uuid", latest_run=MagicMock(id="run-uuid", status="queued"))

        for _ in range(2):
            response = self.client.post(
                self.CLOUD_RUN_URL,
                data={"project_id": self.team.id, "repository": "acme/app"},
                format="json",
            )
            assert response.status_code == status.HTTP_200_OK, response.content

        response = self.client.post(
            self.CLOUD_RUN_URL,
            data={"project_id": self.team.id, "repository": "acme/app"},
            format="json",
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert mock_create.call_count == 2

    def tearDown(self):
        super().tearDown()
        cache.clear()  # Clears out all DRF throttle data


class SetupWizardGatewayTokenThrottleTests(APIBaseTest):
    def tearDown(self):
        super().tearDown()
        cache.clear()

    def test_key_ignores_a_caller_supplied_forwarded_for(self):
        from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle

        throttle = SetupWizardGatewayTokenRateThrottle()
        factory = APIRequestFactory()

        first = factory.post("/api/wizard/gateway_token", HTTP_X_FORWARDED_FOR="1.2.3.4")
        second = factory.post("/api/wizard/gateway_token", HTTP_X_FORWARDED_FOR="5.6.7.8, 9.9.9.9")

        # Same untrusted origin, two different forwarded headers: the bucket
        # must not move, or the cap is bypassed by rotating the header.
        assert throttle.get_cache_key(Request(first), None) == throttle.get_cache_key(Request(second), None)

    @patch("posthog.rate_limit.OAuthAccessTokenAuthentication")
    def test_key_follows_the_authenticated_user(self, mock_authentication):
        from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle

        throttle = SetupWizardGatewayTokenRateThrottle()
        factory = APIRequestFactory()
        mock_authentication.return_value.authenticate.return_value = (self.user, None)

        keyed = throttle.get_cache_key(Request(factory.post("/api/wizard/gateway_token")), None)
        mock_authentication.return_value.authenticate.return_value = None
        anonymous = throttle.get_cache_key(Request(factory.post("/api/wizard/gateway_token")), None)

        assert keyed != anonymous


@override_settings(
    WIZARD_GATEWAY_MINT_KEY="phs_wizard_mint",
    WIZARD_GATEWAY_URL="https://ai-gateway.us.posthog.com",
    WIZARD_GATEWAY_CLIENT_IDS=["wizard-client-id"],
    WIZARD_GATEWAY_PROGRAM_IDS=["integration"],
)
class SetupWizardGatewayTokenTests(APIBaseTest):
    GATEWAY_TOKEN_URL = "/api/wizard/gateway_token"

    MINTED = {"token": "phe_test_token", "expires_at": "2026-08-22T00:00:00Z", "cap_usd": "50"}

    def tearDown(self):
        super().tearDown()
        cache.clear()  # Clears out all DRF throttle data

    def _mock_oauth(self, mock_authentication, scope=None, scoped_teams=None, client_id="wizard-client-id"):
        mock_authenticator = mock_authentication.return_value
        mock_authenticator.authenticate.return_value = (self.user, None)
        mock_authenticator.access_token.scope = "llm_gateway:read" if scope is None else scope
        mock_authenticator.access_token.scoped_teams = scoped_teams if scoped_teams is not None else [self.team.id]
        mock_authenticator.access_token.application.client_id = client_id
        return mock_authenticator

    @override_settings(WIZARD_GATEWAY_MINT_KEY="")
    def test_unconfigured_is_404(self):
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_mints_for_scoped_oauth_token(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["token"] == "phe_test_token"
        assert body["expires_at"] == self.MINTED["expires_at"]
        assert body["gateway_url"] == "https://ai-gateway.us.posthog.com"
        assert body["team_id"] == self.team.id
        assert mock_mint.call_args.kwargs == {
            "obo": str(self.team.organization_id),
            "user": str(self.user.distinct_id),
            "product": "wizard:integration",
        }

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=False)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_flag_off_is_404(self, mock_authentication, mock_flag, mock_authorized):
        self._mock_oauth(mock_authentication)
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_missing_gateway_scope_is_401(self, mock_authentication):
        # "*" must not subsume the privileged scope.
        self._mock_oauth(mock_authentication, scope="*")
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_token_from_another_application_is_401(self, mock_authentication, mock_authorized):
        self._mock_oauth(mock_authentication, client_id="sandbox-client-id")
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=False)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_revoked_project_access_is_403(self, mock_authentication, mock_flag, mock_authorized):
        self._mock_oauth(mock_authentication)
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_request_is_rejected(self):
        # No authenticator mock: the real one must refuse a request with no
        # bearer, on a viewset whose permission_classes is empty.
        self.client.logout()
        response = self.client.post(self.GATEWAY_TOKEN_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_session_cookie_alone_is_rejected(self):
        # APIBaseTest leaves a logged-in session; it must not authorize a mint.
        response = self.client.post(self.GATEWAY_TOKEN_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_multi_team_scope_is_400(self, mock_authentication):
        self._mock_oauth(mock_authentication, scoped_teams=[self.team.id, self.team.id + 1])
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch(
        "posthog.api.wizard.http.mint_wizard_gateway_token",
        side_effect=WizardGatewayMintError("refused"),
    )
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_mint_failure_is_503(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)
        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def _reserved_counter_value(self, key="refund-test-key"):
        """The live value of the reservation counter for a pinned cache key."""
        import time

        from django.core.cache import cache as django_cache

        from posthog.rate_limit import SetupWizardGatewayTokenRateThrottle

        window = int(time.time()) // SetupWizardGatewayTokenRateThrottle().duration
        return django_cache.get(f"{key}:{window}")

    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_failure_that_issued_no_token_returns_the_slot(
        self, mock_authentication, mock_flag, mock_authorized, mock_key
    ):
        # Nothing below the helper's unit tests covers deleting or inverting this.
        self._mock_oauth(mock_authentication)
        with patch(
            "posthog.api.wizard.http.mint_wizard_gateway_token",
            side_effect=WizardGatewayMintError("refused", token_may_exist=False),
        ):
            response = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert self._reserved_counter_value() == 0

    @override_settings(DEBUG=False)
    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_induced_failures_cannot_buy_extra_tokens(self, mock_authentication, mock_flag, mock_authorized, mock_key):
        """The counter must equal the tokens actually issued, however many failures ran.

        The refund exists so an outage does not burn a user's quota, which invites
        the mirror question: induce failures on purpose and keep the slot each time.
        That is only safe while a refund is impossible on any path that hands back a
        token, so the ceiling has to bind on issued tokens rather than on attempts.
        """
        self._mock_oauth(mock_authentication)

        with patch(
            "posthog.api.wizard.http.mint_wizard_gateway_token",
            side_effect=WizardGatewayMintError("unreachable", token_may_exist=False),
        ):
            for _ in range(20):
                failed = self.client.post(
                    self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
                )
                assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

        assert self._reserved_counter_value() == 0

        with patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=self.MINTED) as mock_mint:
            for _ in range(5):
                ok = self.client.post(
                    self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
                )
                assert ok.status_code == status.HTTP_201_CREATED
            # The ceiling counts issued tokens, so the 20 refunded failures bought
            # nothing: the sixth mint is refused even though 25 requests preceded it.
            refused = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )

        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert mock_mint.call_count == 5
        assert self._reserved_counter_value() == 6

    @patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="refund-test-key")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_failure_that_may_have_issued_a_token_keeps_the_slot(
        self, mock_authentication, mock_flag, mock_authorized, mock_key
    ):
        # The paired negative: the gateway may hold this token.
        self._mock_oauth(mock_authentication)
        with patch(
            "posthog.api.wizard.http.mint_wizard_gateway_token",
            side_effect=WizardGatewayMintError("unreadable", token_may_exist=True),
        ):
            response = self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert self._reserved_counter_value() == 1

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_unlisted_program_is_refused(self, mock_authentication, mock_flag, mock_authorized, mock_mint):
        self._mock_oauth(mock_authentication)
        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "invented"}, headers={"authorization": "Bearer pha_test"}
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_mint.assert_not_called()

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_missing_program_is_refused(self, mock_authentication, mock_flag, mock_authorized, mock_mint):
        self._mock_oauth(mock_authentication)
        response = self.client.post(self.GATEWAY_TOKEN_URL, headers={"authorization": "Bearer pha_test"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_mint.assert_not_called()

    @patch("posthog.api.wizard.http.mint_wizard_gateway_token")
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_non_string_program_is_refused_not_a_500(
        self, mock_authentication, mock_flag, mock_authorized, mock_mint
    ):
        # An unhashable value raises on the set membership, inside a throttle that
        # runs before authentication.
        self._mock_oauth(mock_authentication)
        response = self.client.post(
            self.GATEWAY_TOKEN_URL,
            data=json.dumps({"program": ["integration"]}),
            content_type="application/json",
            headers={"authorization": "Bearer pha_test"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_mint.assert_not_called()

    @override_settings(DEBUG=False)
    @patch("posthog.api.wizard.http.oauth_credential_authorized", return_value=True)
    @patch("posthog.api.wizard.http.mint_wizard_gateway_token", return_value=MINTED)
    @patch("posthog.api.wizard.http.posthoganalytics.feature_enabled", return_value=True)
    @patch("posthog.api.wizard.http.OAuthAccessTokenAuthentication")
    def test_a_throttled_mint_is_counted(self, mock_authentication, mock_flag, mock_mint, mock_authorized):
        self._mock_oauth(mock_authentication)
        before = _gateway_token_outcome("throttled")

        for _ in range(5):
            self.client.post(
                self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
            )
        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_test"}
        )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert _gateway_token_outcome("throttled") == before + 1

    def test_an_unresolvable_bearer_is_counted(self):
        before = _gateway_token_outcome("invalid_token")

        response = self.client.post(
            self.GATEWAY_TOKEN_URL, {"program": "integration"}, headers={"authorization": "Bearer pha_unknown"}
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert _gateway_token_outcome("invalid_token") == before + 1


def _gateway_token_outcome(outcome: str) -> float:
    """Current value of one outcome counter. An unrecorded label reads as zero."""
    return REGISTRY.get_sample_value("posthog_wizard_gateway_token_requests_total", {"outcome": outcome}) or 0.0


class TestReserveWizardMint:
    """The ceiling is atomic and sits on the mint, not on arrival."""

    @pytest.fixture(autouse=True)
    def _settings(self):
        with override_settings(WIZARD_GATEWAY_PROGRAM_IDS=["integration"], DEBUG=False):
            yield

    def _request(self):
        factory = APIRequestFactory()
        return Request(factory.post("/api/wizard/gateway_token", {"program": "integration"}))

    def test_the_sixth_reservation_in_a_window_is_refused(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            for _ in range(5):
                reserve_wizard_mint(req, None)
            with pytest.raises(Throttled):
                reserve_wizard_mint(req, None)

    def test_the_reservation_returns_the_counter_it_charged(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            counter = reserve_wizard_mint(req, None)
        assert counter is not None
        assert counter.startswith("k:")
        assert django_cache.get(counter) == 1

    def test_a_refund_returns_the_slot_to_that_counter(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            counter = reserve_wizard_mint(req, None)
            refund_wizard_mint(counter)
            # The refunded slot is spendable again rather than merely not charged.
            for _ in range(5):
                reserve_wizard_mint(req, None)
            with pytest.raises(Throttled):
                reserve_wizard_mint(req, None)

    def test_a_vanished_key_is_re_established_so_its_counter_is_refundable(self):
        from django.core.cache import cache as django_cache

        django_cache.clear()
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", return_value="k"):
            with patch("posthog.rate_limit.cache.incr", side_effect=ValueError("no key")):
                counter = reserve_wizard_mint(req, None)

        assert counter is not None
        assert django_cache.get(counter) == 1
        refund_wizard_mint(counter)
        assert django_cache.get(counter) == 0

    def test_a_refund_without_a_counter_is_a_no_op(self):
        refund_wizard_mint(None)

    def test_a_cache_failure_fails_open(self):
        # Load-shedding posture: the per-token cap and the wallet also bound this,
        # and a Redis blip must not turn a minted token into a 500.
        req = self._request()
        with patch.object(SetupWizardGatewayTokenRateThrottle, "get_cache_key", side_effect=RuntimeError("redis down")):
            reserve_wizard_mint(req, None)
