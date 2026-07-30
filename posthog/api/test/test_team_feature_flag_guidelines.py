from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.models import TeamFeatureFlagGuidelinesConfig


class TestTeamFeatureFlagGuidelines(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/feature_flag_guidelines/"

    def test_get_returns_defaults_for_fresh_team(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"enabled": False, "url": ""})

    def test_put_stores_enabled_and_url(self):
        response = self.client.put(
            self.url,
            {"enabled": True, "url": "https://www.notion.so/feature-flag-sop"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {"enabled": True, "url": "https://www.notion.so/feature-flag-sop"},
        )

    def test_put_enabled_only_keeps_existing_url(self):
        config = get_or_create_team_extension(self.team, TeamFeatureFlagGuidelinesConfig)
        config.url = "https://example.com/docs"
        config.save()

        response = self.client.put(self.url, {"enabled": True}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"enabled": True, "url": "https://example.com/docs"})

    @parameterized.expand(
        [
            ("not_a_url", "not-a-url"),
            ("missing_scheme", "www.notion.so/sop"),
        ]
    )
    def test_put_rejects_invalid_url(self, _name, bad_url):
        response = self.client.put(self.url, {"enabled": True, "url": bad_url}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_can_read_but_not_write(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.put(
            self.url,
            {"enabled": True, "url": "https://example.com/docs"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_serializer_exposes_guidelines(self):
        config = get_or_create_team_extension(self.team, TeamFeatureFlagGuidelinesConfig)
        config.enabled = True
        config.url = "https://example.com/docs"
        config.save()

        response = self.client.get(f"/api/projects/{self.team.project_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["feature_flag_guidelines"],
            {"enabled": True, "url": "https://example.com/docs"},
        )
