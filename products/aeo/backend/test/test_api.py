from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.aeo.backend.models import AEOPrompt


class TestAEOPromptAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "products.aeo.backend.presentation.views.posthog_feature_flag_enabled",
            return_value=True,
        )
        self.feature_enabled = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        self.url = f"/api/projects/{self.team.id}/aeo_prompts/"

    def test_requires_the_rollout_flag(self) -> None:
        self.feature_enabled.return_value = False

        assert self.client.get(self.url).status_code == status.HTTP_403_FORBIDDEN
        response = self.client.post(f"{self.url}bulk_import/", {"prompts": [{"prompt": "q?"}]}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not AEOPrompt.objects.for_team(self.team.id).exists()

    def test_bulk_import_then_deactivate_survives_a_reimport(self) -> None:
        payload = {
            "prompts": [
                {"prompt": "Best session replay tool?", "topic": "Session replay", "external_visibility": 42.5},
                {"prompt": "Best feature flag tool?", "topic": "Feature flags"},
                {"prompt": "   "},
            ]
        }
        response = self.client.post(f"{self.url}bulk_import/", payload, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"created": 2, "updated": 0, "skipped": 1}

        listed = {row["prompt"]: row for row in self.client.get(self.url).json()["results"]}
        assert listed["Best session replay tool?"]["topic"] == "Session replay"
        assert listed["Best session replay tool?"]["external_visibility"] == 42.5
        assert listed["Best feature flag tool?"]["external_visibility"] is None

        replay_id = listed["Best session replay tool?"]["id"]
        response = self.client.patch(f"{self.url}{replay_id}/", {"active": False, "topic": "ignored"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["active"] is False
        assert response.json()["topic"] == "Session replay"

        response = self.client.post(f"{self.url}bulk_import/", payload, format="json")
        assert response.json() == {"created": 0, "updated": 2, "skipped": 1}
        assert AEOPrompt.objects.for_team(self.team.id).get(id=replay_id).active is False

    def test_list_pages_without_overlap(self) -> None:
        prompts = [{"prompt": f"q{i}?", "topic": "same topic"} for i in range(5)]
        self.client.post(f"{self.url}bulk_import/", {"prompts": prompts}, format="json")

        first = self.client.get(f"{self.url}?limit=3").json()
        second = self.client.get(f"{self.url}?limit=3&offset=3").json()

        assert first["count"] == 5
        assert first["next"] is not None and second["next"] is None
        ids = [row["id"] for row in first["results"] + second["results"]]
        assert len(ids) == len(set(ids)) == 5

    @parameterized.expand([("above_range", 140), ("not_a_number", "NaN"), ("infinite", "Infinity")])
    def test_bulk_import_rejects_invalid_visibility(self, _name: str, visibility: object) -> None:
        response = self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "q?", "external_visibility": visibility}]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not AEOPrompt.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            ("write_scope", ["web_analytics:write"], status.HTTP_200_OK),
            ("read_scope_only", ["web_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_bulk_import_with_a_personal_api_key(self, _name: str, scopes: list[str], expected: int) -> None:
        # Session auth skips scope checks, so only a scoped key catches a custom action left out of the write actions.
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="aeo import", secure_value=hash_key_value(value), scopes=scopes
        )
        self.client.logout()

        response = self.client.post(
            f"{self.url}bulk_import/",
            {"prompts": [{"prompt": "Best session replay tool?"}]},
            format="json",
            headers={"authorization": f"Bearer {value}"},
        )

        assert response.status_code == expected, response.json()
