from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.business_knowledge.backend.api.serializers import BusinessKnowledgeSettingsUpdateSerializer
from products.business_knowledge.backend.api.settings import BusinessKnowledgeSettingsViewSet
from products.business_knowledge.backend.models import TeamBusinessKnowledgeConfig

SUPPORT_OFF_ERROR = "Turn on Support to learn from resolved tickets."


class TestBusinessKnowledgeSettingsUpdateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("enable_without_support", True, False, False),
            ("enable_with_support", True, True, True),
            ("disable_without_support", False, False, True),
        ]
    )
    def test_learn_from_support_requires_support_to_enable(
        self, _name: str, enabled: bool, support_enabled: bool, expect_valid: bool
    ) -> None:
        serializer = BusinessKnowledgeSettingsUpdateSerializer(
            data={"learn_from_support_enabled": enabled},
            context={"team": SimpleNamespace(conversations_enabled=support_enabled)},
        )

        assert serializer.is_valid() is expect_valid
        if not expect_valid:
            assert serializer.errors["learn_from_support_enabled"][0] == SUPPORT_OFF_ERROR


class TestBusinessKnowledgeSettingsScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("get", "GET", ["business_knowledge:read"]),
            ("patch", "PATCH", ["business_knowledge:write"]),
        ]
    )
    def test_required_scopes_split_by_method(self, _name: str, method: str, expected: list[str]) -> None:
        view = BusinessKnowledgeSettingsViewSet()
        view.action = "knowledge_settings"

        assert view.dangerously_get_required_scopes(APIRequestFactory().generic(method, "/"), view) == expected


@patch("posthoganalytics.feature_enabled", return_value=True)
class TestBusinessKnowledgeSettingsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/business_knowledge/settings/"

    def _enable_support(self, team: Team | None = None) -> None:
        team = team or self.team
        team.conversations_enabled = True
        team.save(update_fields=["conversations_enabled"])

    def _auth_with_pak(self, scopes: list[str]) -> None:
        key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

    def test_get_returns_defaults(self, _ff) -> None:
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "learn_from_support_enabled": False,
            "support_enabled": False,
        }

    def test_patch_round_trips(self, _ff) -> None:
        self._enable_support()

        enabled = self.client.patch(self.url, {"learn_from_support_enabled": True}, format="json")
        assert enabled.status_code == status.HTTP_200_OK, enabled.content
        assert enabled.json() == {
            "learn_from_support_enabled": True,
            "support_enabled": True,
        }
        assert self.client.get(self.url).json() == {
            "learn_from_support_enabled": True,
            "support_enabled": True,
        }

        disabled = self.client.patch(self.url, {"learn_from_support_enabled": False}, format="json")
        assert disabled.status_code == status.HTTP_200_OK, disabled.content
        assert disabled.json()["learn_from_support_enabled"] is False

    def test_cannot_enable_when_support_is_off(self, _ff) -> None:
        response = self.client.patch(self.url, {"learn_from_support_enabled": True}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == "learn_from_support_enabled"
        assert get_or_create_team_extension(self.team, TeamBusinessKnowledgeConfig).learn_from_support_enabled is False

    def test_can_disable_when_support_is_off(self, _ff) -> None:
        self._enable_support()
        enabled = self.client.patch(self.url, {"learn_from_support_enabled": True}, format="json")
        assert enabled.status_code == status.HTTP_200_OK, enabled.content

        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])

        response = self.client.patch(self.url, {"learn_from_support_enabled": False}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "learn_from_support_enabled": False,
            "support_enabled": False,
        }

    def test_empty_patch_is_a_noop(self, _ff) -> None:
        response = self.client.patch(self.url, {}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["learn_from_support_enabled"] is False

    def test_child_environment_writes_canonical_parent(self, _ff) -> None:
        self._enable_support()
        child = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            project=self.team.project,
            name="Child environment",
            conversations_enabled=True,
        )

        response = self.client.patch(
            f"/api/projects/{child.id}/business_knowledge/settings/",
            {"learn_from_support_enabled": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["learn_from_support_enabled"] is True
        assert self.client.get(f"/api/projects/{child.id}/business_knowledge/settings/").json() == {
            "learn_from_support_enabled": True,
            "support_enabled": True,
        }
        assert get_or_create_team_extension(self.team, TeamBusinessKnowledgeConfig).learn_from_support_enabled is True
        assert get_or_create_team_extension(child, TeamBusinessKnowledgeConfig).learn_from_support_enabled is False

    def test_child_get_returns_parent_learn_flag_and_own_support(self, _ff) -> None:
        self._enable_support()
        enabled = self.client.patch(self.url, {"learn_from_support_enabled": True}, format="json")
        assert enabled.status_code == status.HTTP_200_OK, enabled.content

        child = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            project=self.team.project,
            name="Child environment",
            conversations_enabled=False,
        )

        response = self.client.get(f"/api/projects/{child.id}/business_knowledge/settings/")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {
            "learn_from_support_enabled": True,
            "support_enabled": False,
        }

    def test_child_cannot_enable_when_its_support_is_off(self, _ff) -> None:
        self._enable_support()
        child = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            project=self.team.project,
            name="Child environment",
            conversations_enabled=False,
        )

        response = self.client.patch(
            f"/api/projects/{child.id}/business_knowledge/settings/",
            {"learn_from_support_enabled": True},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert get_or_create_team_extension(self.team, TeamBusinessKnowledgeConfig).learn_from_support_enabled is False
        assert get_or_create_team_extension(child, TeamBusinessKnowledgeConfig).learn_from_support_enabled is False

    def test_other_organization_is_forbidden(self, _ff) -> None:
        other_org = Organization.objects.create(name="Other org")
        other_team = Team.objects.create(organization=other_org, name="Other")

        response = self.client.get(f"/api/projects/{other_team.id}/business_knowledge/settings/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_read_scope_allows_get(self, _ff) -> None:
        self._auth_with_pak(["business_knowledge:read"])
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK, response.content

    def test_read_scope_cannot_patch(self, _ff) -> None:
        self._enable_support()
        self._auth_with_pak(["business_knowledge:read"])
        response = self.client.patch(self.url, {"learn_from_support_enabled": True}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_write_scope_allows_patch(self, _ff) -> None:
        self._enable_support()
        self._auth_with_pak(["business_knowledge:write"])
        response = self.client.patch(self.url, {"learn_from_support_enabled": True}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
