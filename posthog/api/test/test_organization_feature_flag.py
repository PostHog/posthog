from rest_framework import status
from posthog.models.user import User
from posthog.models.team.team import Team
from ee.models.organization_resource_access import OrganizationResourceAccess
from posthog.constants import AvailableFeature
from posthog.models import FeatureFlag
from posthog.models.experiment import Experiment
from posthog.models.feedback.survey import Survey
from posthog.models.early_access_feature import EarlyAccessFeature
from posthog.api.dashboards.dashboard import Dashboard
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from typing import Any, Dict


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
            {
                "flag_id": flag.id,
                "team_id": flag.team.id,
                "created_by": {
                    "id": self.user.id,
                    "uuid": str(self.user.uuid),
                    "distinct_id": self.user.distinct_id,
                    "first_name": self.user.first_name,
                    "email": self.user.email,
                    "is_email_verified": self.user.is_email_verified,
                },
                "filters": flag.filters,
                "created_at": flag.created_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                "active": flag.active,
            }
            for flag in [self.feature_flag_1, self.feature_flag_2]
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

        existing_flag = FeatureFlag.objects.create(
            team=target_project,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            rollout_percentage=rollout_percentage_existing,
            ensure_experience_continuity=False,
        )

        # The following instances must remain linked to the existing flag after overwriting it
        experiment = Experiment.objects.create(team=self.team_2, created_by=self.user, feature_flag_id=existing_flag.id)
        survey = Survey.objects.create(team=self.team, created_by=self.user, linked_flag=existing_flag)
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            feature_flag=existing_flag,
        )
        analytics_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )
        existing_flag.analytics_dashboards.set([analytics_dashboard])
        usage_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )
        existing_flag.usage_dashboard = usage_dashboard
        existing_flag.save()

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
            "is_simple_flag": True,
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "has_enriched_analytics": False,
            "tags": [],
            "id": "__ignore__",
            "created_at": "__ignore__",
            "usage_dashboard": "__ignore__",
            "experiment_set": "__ignore__",
            "surveys": "__ignore__",
            "features": "__ignore__",
            "analytics_dashboards": "__ignore__",
        }

        flag_response = response.json()["success"][0]

        for key, expected_value in expected_flag_response.items():
            self.assertIn(key, flag_response)
            if expected_value != "__ignore__":
                if key == "created_by":
                    self.assertEqual(flag_response[key]["id"], expected_value)
                else:
                    self.assertEqual(flag_response[key], expected_value)

        # Linked instances must remain linked
        self.assertEqual(experiment.id, flag_response["experiment_set"][0])
        self.assertEqual(str(survey.id), flag_response["surveys"][0]["id"])
        self.assertEqual(str(feature.id), flag_response["features"][0]["id"])
        self.assertEqual(analytics_dashboard.id, flag_response["analytics_dashboards"][0])
        self.assertEqual(usage_dashboard.id, flag_response["usage_dashboard"])

        self.assertSetEqual(
            set(expected_flag_response.keys()),
            set(flag_response.keys()),
        )

    def test_copy_feature_flag_update_override_deleted(self):
        target_project = self.team_2
        target_project_2 = Team.objects.create(organization=self.organization)
        rollout_percentage_existing = 99

        existing_deleted_flag = FeatureFlag.objects.create(
            team=target_project,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            rollout_percentage=rollout_percentage_existing,
            ensure_experience_continuity=False,
            deleted=True,
        )
        existing_deleted_flag2 = FeatureFlag.objects.create(
            team=target_project_2,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            rollout_percentage=rollout_percentage_existing,
            ensure_experience_continuity=False,
            deleted=True,
        )

        # The following instances must be overriden for a soft-deleted flag
        Survey.objects.create(team=self.team, created_by=self.user, linked_flag=existing_deleted_flag)

        analytics_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )
        existing_deleted_flag.analytics_dashboards.set([analytics_dashboard])
        usage_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )

        existing_deleted_flag.usage_dashboard = usage_dashboard
        existing_deleted_flag.save()

        # Experiments restrict deleting soft-deleted flags
        Experiment.objects.create(
            team=target_project_2, created_by=self.user, feature_flag_id=existing_deleted_flag2.id
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id, target_project_2.id],
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
            "is_simple_flag": True,
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "has_enriched_analytics": False,
            "tags": [],
            "id": "__ignore__",
            "created_at": "__ignore__",
            "usage_dashboard": "__ignore__",
            "experiment_set": "__ignore__",
            "surveys": "__ignore__",
            "features": "__ignore__",
            "analytics_dashboards": "__ignore__",
        }
        flag_response = response.json()["success"][0]

        for key, expected_value in expected_flag_response.items():
            self.assertIn(key, flag_response)
            if expected_value != "__ignore__":
                if key == "created_by":
                    self.assertEqual(flag_response[key]["id"], expected_value)
                else:
                    self.assertEqual(flag_response[key], expected_value)

        # Linked instances must be overriden for a soft-deleted flag
        self.assertEqual(flag_response["experiment_set"], [])
        self.assertEqual(flag_response["surveys"], [])
        self.assertNotEqual(flag_response["usage_dashboard"], existing_deleted_flag.usage_dashboard.id)
        self.assertEqual(flag_response["analytics_dashboards"], [])

        self.assertSetEqual(
            set(expected_flag_response.keys()),
            set(flag_response.keys()),
        )

        # target_project_2 should have failed
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertEqual(response.json()["failed"][0]["project_id"], target_project_2.id)
        self.assertEqual(
            response.json()["failed"][0]["errors"],
            "[ErrorDetail(string='Feature flag with this key already exists and is used in an experiment. Please delete the experiment before deleting the flag.', code='invalid')]",
        )

    def test_copy_feature_flag_missing_fields(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data: Dict[str, Any] = {}
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

    def test_copy_feature_flag_cannot_edit(self):
        self.organization.available_features = [AvailableFeature.ROLE_BASED_ACCESS]
        self.organization.save()

        OrganizationResourceAccess.objects.create(
            resource=OrganizationResourceAccess.Resources.FEATURE_FLAGS,
            access_level=OrganizationResourceAccess.AccessLevel.CAN_ONLY_VIEW,
            organization=self.organization,
        )
        self.assertEqual(self.user.role_memberships.count(), 0)
        user_a = User.objects.create_and_join(self.organization, "a@potato.com", None)
        untouchable_flag = FeatureFlag.objects.create(
            created_by=user_a,
            key="flag_a",
            name="Flag A",
            team=self.team,
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": untouchable_flag.key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
