from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest
from ee.models.rbac.access_control import AccessControl


class TestExperimentHoldoutCRUD(APILicensedTest):
    def test_can_list_experiment_holdouts(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_update_experiment_holdouts(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "Test Experiment holdout",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 20,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        holdout_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment holdout")
        self.assertEqual(
            response.json()["filters"],
            [{"properties": [], "rollout_percentage": 20, "variant": f"holdout-{holdout_id}"}],
        )

        # Generate experiment to be part of holdout
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [
                        {"order": 0, "id": "$pageview"},
                        {"order": 1, "id": "$pageleave"},
                    ],
                    "properties": [],
                },
                "holdout_id": holdout_id,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(
            created_ff.filters["holdout"],
            {"id": holdout_id, "exclusion_percentage": 20},
        )

        exp_id = response.json()["id"]
        # Now try updating holdout
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_holdouts/{holdout_id}",
            {
                "name": "Test Experiment holdout 2",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 30,
                        "variant": "holdout",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Experiment holdout 2")
        self.assertEqual(
            response.json()["filters"],
            [{"properties": [], "rollout_percentage": 30, "variant": f"holdout-{holdout_id}"}],
        )

        # make sure flag for experiment in question was updated as well
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(
            created_ff.filters["holdout"],
            {"id": holdout_id, "exclusion_percentage": 30},
        )

        # now delete holdout
        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_holdouts/{holdout_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # make sure flag for experiment in question was updated as well
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.filters["holdout"], None)

        # and same for experiment
        exp = Experiment.objects.get(pk=exp_id)
        self.assertEqual(exp.holdout, None)

    def test_invalid_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": None,  # invalid
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 20,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "xyz",
                "filters": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Filters must not be empty.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts",
            data={
                "name": "xyz",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": 150,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Rollout percentage must be between 0 and 100.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts",
            data={
                "name": "xyz",
                "filters": [
                    {
                        "properties": [],
                        "rollout_percentage": -10,
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Rollout percentage must be between 0 and 100.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts",
            data={
                "name": "xyz",
                "filters": [
                    {
                        "properties": [],
                        "variant": "holdout",
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Rollout percentage must be present.")

    def test_update_with_empty_filters_is_rejected(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_holdouts/",
            data={
                "name": "Test holdout",
                "filters": [{"properties": [], "rollout_percentage": 20, "variant": "holdout"}],
            },
            format="json",
        )
        holdout_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_holdouts/{holdout_id}",
            {"filters": []},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestExperimentHoldoutAccessControl(APILicensedTest):
    """Holdouts are a first-class access-control resource that inherits experiment access.

    A user must have resource-level (project-wide) experiment access to manage holdouts; an
    object-level grant on a single experiment must not admit them, since holdouts are shared
    project config and have no per-object grants of their own.
    """

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        # Owned by a different user — creators always get highest access, which would mask
        # the access-control behavior under test.
        self.other_user = User.objects.create_and_join(self.organization, "holdout-owner@posthog.com", None)
        self.holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Held-out users",
            created_by=self.other_user,
            filters=[{"properties": [], "rollout_percentage": 20, "variant": "holdout"}],
        )
        self.feature_flag = FeatureFlag.objects.create(team=self.team, key="exp-flag", created_by=self.other_user)
        self.experiment = Experiment.objects.create(
            team=self.team, name="Exp", feature_flag=self.feature_flag, created_by=self.other_user
        )

    def _set_experiment_resource_level(self, access_level: str) -> None:
        AccessControl.objects.update_or_create(
            team=self.team,
            resource="experiment",
            resource_id=None,
            organization_member=None,
            role=None,
            defaults={"access_level": access_level},
        )

    def _grant_experiment_object_access(self, access_level: str) -> None:
        AccessControl.objects.update_or_create(
            team=self.team,
            resource="experiment",
            resource_id=str(self.experiment.id),
            organization_member=self.organization_membership,
            role=None,
            defaults={"access_level": access_level},
        )

    def test_single_experiment_object_grant_does_not_admit_to_holdouts(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._set_experiment_resource_level("none")
        self._grant_experiment_object_access("editor")

        # Sanity: the object grant does let them see that one experiment...
        exp_list = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(exp_list.status_code, status.HTTP_200_OK)

        # ...but it must not leak holdouts.
        list_res = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/")
        self.assertEqual(list_res.status_code, status.HTTP_403_FORBIDDEN)

        retrieve_res = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/")
        self.assertEqual(retrieve_res.status_code, status.HTTP_403_FORBIDDEN)

        update_res = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/",
            {"name": "renamed"},
            format="json",
        )
        self.assertEqual(update_res.status_code, status.HTTP_403_FORBIDDEN)

        delete_res = self.client.delete(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/")
        self.assertEqual(delete_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_resource_level_experiment_access_grants_holdout_crud(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._set_experiment_resource_level("editor")

        list_res = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/")
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)

        retrieve_res = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/")
        self.assertEqual(retrieve_res.status_code, status.HTTP_200_OK)

        update_res = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/",
            {"name": "renamed"},
            format="json",
        )
        self.assertEqual(update_res.status_code, status.HTTP_200_OK)

        delete_res = self.client.delete(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/")
        self.assertEqual(delete_res.status_code, status.HTTP_204_NO_CONTENT)

    def test_holdout_access_controls_endpoint_not_exposed(self):
        # Holdouts inherit experiment access and must not support per-object grants. The
        # access_controls action would otherwise let a holdout-specific grant bypass
        # resource-level experiment access. Even an org admin must get 404 — the route is absent.
        get_res = self.client.get(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/access_controls")
        self.assertEqual(get_res.status_code, status.HTTP_404_NOT_FOUND)

        put_res = self.client.put(
            f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}/access_controls",
            {"access_level": "editor"},
            format="json",
        )
        self.assertEqual(put_res.status_code, status.HTTP_404_NOT_FOUND)
