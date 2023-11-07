from rest_framework import status
from posthog.models.team.team import Team
from posthog.models import FeatureFlag
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries


class OrganizationFeatureFlagViewTests(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        self.feature_flag_key = "key-1"

        self.feature_flag_1 = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key=self.feature_flag_key
        )
        self.feature_flag_1 = FeatureFlag.objects.create(
            team=self.team_2, created_by=self.user, key=self.feature_flag_key
        )

        super().setUp()

    @snapshot_postgres_queries
    def test_get_feature_flag_success(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_data = [{"team_id": self.team_1.id, "active": True}, {"team_id": self.team_2.id, "active": True}]
        self.assertCountEqual(response.json(), expected_data)

    def test_get_feature_flag_not_found(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/nonexistent-flag"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

    def test_get_feature_flag_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
