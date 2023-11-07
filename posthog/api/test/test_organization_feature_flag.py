from rest_framework import status
from posthog.models.team.team import Team
from posthog.models import FeatureFlag
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries


class TestOrganizationFeatureFlagGet(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)
        self.team_3 = Team.objects.create(organization=self.organization)

        self.feature_flag_key = "key-1"

        self.feature_flag_1 = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key=self.feature_flag_key
        )
        self.feature_flag_2 = FeatureFlag.objects.create(
            team=self.team_2, created_by=self.user, key=self.feature_flag_key
        )
        self.feature_flag_deleted = FeatureFlag.objects.create(
            team=self.team_3, created_by=self.user, key=self.feature_flag_key, deleted=True
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
        self.rollout_percentage_to_copy = 65
        self.feature_flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=self.feature_flag_key,
            filters={"groups": [{"rollout_percentage": self.rollout_percentage_to_copy}]},
            rollout_percentage=self.rollout_percentage_to_copy,
        )

        super().setUp()

    @snapshot_postgres_queries
    def test_copy_feature_flag_create_new(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertIn("failed", response.json())

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": self.feature_flag_to_copy.filters,
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "rollout_percentage": self.rollout_percentage_to_copy,
            "deleted": False,
            "created_by": self.user.id,
            "id": "__ignore__",
            "created_at": "__ignore__",
            "usage_dashboard": "__ignore__",
            "is_simple_flag": True,
            "experiment_set": [],
            "surveys": [],
            "features": [],
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "analytics_dashboards": [],
            "has_enriched_analytics": False,
            "tags": [],
        }

        flag_response = response.json()["success"][0]

        for key, expected_value in expected_flag_response.items():
            self.assertIn(key, flag_response)
            if expected_value != "__ignore__":
                if key == "created_by":
                    self.assertEqual(flag_response[key]["id"], expected_value)
                else:
                    self.assertEqual(flag_response[key], expected_value)

        self.assertSetEqual(
            set(expected_flag_response.keys()),
            set(flag_response.keys()),
        )

    def test_copy_feature_flag_update_existing(self):
        target_project = self.team_2
        rollout_percentage_existing = 99
        self.feature_flag_existing = FeatureFlag.objects.create(
            team=target_project,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            rollout_percentage=rollout_percentage_existing,
            ensure_experience_continuity=False,
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertIn("failed", response.json())

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": self.feature_flag_to_copy.filters,
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "rollout_percentage": self.rollout_percentage_to_copy,
            "deleted": False,
            "created_by": self.user.id,
            "id": "__ignore__",
            "created_at": "__ignore__",
            "usage_dashboard": "__ignore__",
            "is_simple_flag": True,
            "experiment_set": [],
            "surveys": [],
            "features": [],
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "analytics_dashboards": [],
            "has_enriched_analytics": False,
            "tags": [],
        }

        flag_response = response.json()["success"][0]

        for key, expected_value in expected_flag_response.items():
            self.assertIn(key, flag_response)
            if expected_value != "__ignore__":
                if key == "created_by":
                    self.assertEqual(flag_response[key]["id"], expected_value)
                else:
                    self.assertEqual(flag_response[key], expected_value)

        self.assertSetEqual(
            set(expected_flag_response.keys()),
            set(flag_response.keys()),
        )

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

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
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
        self.assertEqual(len(response.json()["success"]), 0)
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
