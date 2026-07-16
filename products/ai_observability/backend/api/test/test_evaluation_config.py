from uuid import uuid4

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, Project, Team, User

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


def _setup_team():
    org = Organization.objects.create(name="test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=str(uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    User.objects.create_and_join(org, f"test-eval-config-{uuid4()}@posthog.com", "testpassword123")
    return team


class TestEvaluationConfigViewSet(APIBaseTest):
    def test_unauthenticated_user_cannot_access_config(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_get_evaluation_config(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("active_provider_key", response.data)
        self.assertIsNone(response.data["active_provider_key"])
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)

    def test_get_creates_config_if_missing(self):
        self.assertEqual(EvaluationConfig.objects.filter(team=self.team).count(), 0)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(EvaluationConfig.objects.filter(team=self.team).count(), 1)

    def test_get_returns_existing_config(self):
        existing = EvaluationConfig.objects.create(team=self.team)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(EvaluationConfig.objects.filter(team=self.team).count(), 1)
        self.assertEqual(EvaluationConfig.objects.get(team=self.team).pk, existing.pk)

    def test_can_set_active_key(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-test"},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["active_provider_key"]["id"], str(key.id))

        config = EvaluationConfig.objects.get(team=self.team)
        self.assertEqual(config.active_provider_key, key)

    def test_cannot_set_invalid_key_as_active(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Invalid Key",
            state=LLMProviderKey.State.INVALID,
            error_message="Invalid API key",
            encrypted_config={"api_key": "sk-invalid"},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("invalid", response.data["detail"].lower())

    def test_cannot_set_unknown_key_as_active(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Unknown State Key",
            state=LLMProviderKey.State.UNKNOWN,
            encrypted_config={"api_key": "sk-unknown"},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("validate", response.data["detail"].lower())

    def test_cannot_set_nonexistent_key_as_active(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(uuid4())},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_set_other_teams_key_as_active(self):
        other_team = _setup_team()
        other_key = LLMProviderKey.objects.create(
            team=other_team,
            provider="openai",
            name="Other Team Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-other"},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(other_key.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_active_key_requires_key_id(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["attr"], "key_id")
        self.assertEqual(response.data["code"], "required")

    def test_can_change_active_key(self):
        key1 = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key 1",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-key1"},
            created_by=self.user,
        )
        key2 = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Key 2",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-key2"},
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(key1.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["active_provider_key"]["id"], str(key1.id))

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/set_active_key/",
            {"key_id": str(key2.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["active_provider_key"]["id"], str(key2.id))

        config = EvaluationConfig.objects.get(team=self.team)
        self.assertEqual(config.active_provider_key, key2)

    def test_active_key_serialized_with_details(self):
        key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="My Production Key",
            state=LLMProviderKey.State.OK,
            encrypted_config={"api_key": "sk-prod-12345"},
            created_by=self.user,
        )
        EvaluationConfig.objects.create(team=self.team, active_provider_key=key)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/evaluation_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        active_key = response.data["active_provider_key"]
        self.assertEqual(active_key["id"], str(key.id))
        self.assertEqual(active_key["name"], "My Production Key")
        self.assertEqual(active_key["provider"], "openai")
        self.assertEqual(active_key["state"], "ok")
        self.assertIn("api_key_masked", active_key)
