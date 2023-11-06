from rest_framework import status
from posthog.models.team.team import Team
from posthog.models import FeatureFlag
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries


class TestOrganizationFeatureFlagGet(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        self.feature_flag_key = "key-1"

        self.feature_flag_1 = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key=self.feature_flag_key
        )
        self.feature_flag_2 = FeatureFlag.objects.create(
            team=self.team_2, created_by=self.user, key=self.feature_flag_key
        )

        super().setUp()

    @snapshot_postgres_queries
    def test_get_feature_flag_success(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_data = [
            {"flag_id": self.feature_flag_1.id, "team_id": self.team_1.id, "active": True},
            {"flag_id": self.feature_flag_2.id, "team_id": self.team_2.id, "active": True},
        ]
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


class TestOrganizationFeatureFlagCopy(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        self.feature_flag_key = "copied-flag-key"
        self.feature_flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=self.feature_flag_key,
            filters={"groups": [{"rollout_percentage": 65}]},
        )

        super().setUp()

    @snapshot_postgres_queries
    def test_copy_feature_flag_success(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertIn("failed", response.json())

        # copied flag is present in the response
        self.assertEqual(self.feature_flag_key, response.json()["success"][0]["key"])

        # copied flag is present in the DB
        copied_flag = FeatureFlag.objects.filter(team=self.team_2, key=self.feature_flag_key).exists()
        self.assertTrue(copied_flag)

    def test_copy_feature_flag_missing_fields(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    def test_copy_feature_flag_nonexistent_key(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": "nonexistent-key",
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.json())

    def test_copy_feature_flag_to_nonexistent_target(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        nonexistent_project_id = 999
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [nonexistent_project_id],
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertEqual(nonexistent_project_id, response.json()["failed"][0]["project_id"])

    def test_copy_feature_flag_unauthorized(self):
        self.client.logout()
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
