from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import OrganizationMembership, Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.models import TeamLogsConfig


class TestTeamLogsConfig(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/logs_config/"

    def test_get_returns_default_attribute_key(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "posthogDistinctId"})

    def test_patch_updates_attribute_key(self):
        response = self.client.patch(
            self.url,
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "user.id"})

        config = get_or_create_team_extension(self.team, TeamLogsConfig)
        self.assertEqual(config.logs_distinct_id_attribute_key, "user.id")

    def test_patch_persists_across_requests(self):
        self.client.patch(
            self.url,
            {"logs_distinct_id_attribute_key": "posthog.distinct_id"},
            format="json",
        )

        response = self.client.get(self.url)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "posthog.distinct_id"})

    def test_patch_rejects_key_over_max_length(self):
        response = self.client.patch(
            self.url,
            {"logs_distinct_id_attribute_key": "x" * 201},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_regular_member_can_patch(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(
            self.url,
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "user.id"})

    def test_config_is_scoped_per_environment(self):
        # Each environment under a project must keep its own config. A write on this
        # environment must not leak to a sibling environment that shares its project.
        sibling = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="sibling-env",
        )

        self.client.patch(
            self.url,
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )

        sibling_response = self.client.get(f"/api/environments/{sibling.id}/logs_config/")
        self.assertEqual(
            sibling_response.json(),
            {"logs_distinct_id_attribute_key": "posthogDistinctId"},
        )
