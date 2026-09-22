from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.experiments.backend.models.experiment import Experiment, ExperimentHoldout
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest


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


class TestExperimentHoldoutApprovals(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

        self.holdout = ExperimentHoldout.objects.create(
            team=self.team,
            name="Gated holdout",
            filters=[{"properties": [], "rollout_percentage": 20, "variant": "holdout-1"}],
            created_by=self.user,
        )
        self.holdout.filters = [{**self.holdout.filters[0], "variant": f"holdout-{self.holdout.id}"}]
        self.holdout.save()

        self.flag = FeatureFlag.objects.create(
            team=self.team,
            key="experiment-in-holdout",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "holdout": {"holdout_id": self.holdout.id, "exclusion_percentage": 20},
            },
        )
        self.experiment = Experiment.objects.create(
            team=self.team, name="Experiment in holdout", feature_flag=self.flag, holdout=self.holdout
        )

    def _create_policy(self, action_key: str, conditions: dict | None = None, approver_ids: list[int] | None = None):
        from products.approvals.backend.models import ApprovalPolicy

        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions=conditions or {},
            approver_config={"quorum": 1, "users": approver_ids or [self.user.id], "roles": []},
            allow_self_approve=True,
            created_by=self.user,
        )

    def _patch_exclusion(self, percentage: int, **extra):
        return self.client.patch(
            f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}",
            data={"filters": [{"properties": [], "rollout_percentage": percentage, "variant": "holdout"}], **extra},
            format="json",
        )

    def _approve(self, change_request):
        return self.client.post(
            f"/api/environments/{self.team.id}/change_requests/{change_request.id}/approve/",
            {"reason": "ok"},
        )

    def _change_request(self, action_key: str):
        from products.approvals.backend.models import ChangeRequest

        return ChangeRequest.objects.get(team=self.team, action_key=action_key)

    def test_gated_update_writes_nothing_and_keeps_its_change_request(self):
        self._create_policy("experiment_holdout.update")

        response = self._patch_exclusion(40)

        assert response.status_code == status.HTTP_409_CONFLICT
        change_request = self._change_request("experiment_holdout.update")
        assert response.json()["change_request_id"] == str(change_request.id)
        assert change_request.intent["current_state"]["exclusion_percentage"] == 20
        assert change_request.intent["gated_changes"]["exclusion_percentage"] == 40
        assert [e["flag_key"] for e in change_request.intent["affected_experiments"]] == [self.flag.key]

        self.holdout.refresh_from_db()
        self.flag.refresh_from_db()
        assert self.holdout.filters[0]["rollout_percentage"] == 20
        assert self.flag.filters["holdout"]["exclusion_percentage"] == 20

    def test_approving_an_update_rewrites_the_holdout_and_every_flag(self):
        self._create_policy("experiment_holdout.update")
        self._patch_exclusion(40, name="Renamed holdout")

        response = self._approve(self._change_request("experiment_holdout.update"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "applied"
        self.holdout.refresh_from_db()
        self.flag.refresh_from_db()
        assert self.holdout.name == "Renamed holdout"
        assert self.holdout.filters[0]["rollout_percentage"] == 40
        assert self.flag.filters["holdout"]["exclusion_percentage"] == 40

    def test_update_is_stale_when_the_holdout_moved_after_the_request(self):
        self._create_policy("experiment_holdout.update")
        self._patch_exclusion(40)
        change_request = self._change_request("experiment_holdout.update")

        self.holdout.filters = [{**self.holdout.filters[0], "rollout_percentage": 35}]
        self.holdout.save()
        response = self._approve(change_request)

        self.holdout.refresh_from_db()
        assert self.holdout.filters[0]["rollout_percentage"] == 35
        assert response.json().get("status") != "applied"

    def test_update_is_stale_when_an_experiment_joined_the_holdout(self):
        self._create_policy("experiment_holdout.update")
        self._patch_exclusion(40)
        change_request = self._change_request("experiment_holdout.update")

        joined_flag = FeatureFlag.objects.create(team=self.team, key="joined-later", created_by=self.user)
        Experiment.objects.create(team=self.team, name="Joined later", feature_flag=joined_flag, holdout=self.holdout)
        response = self._approve(change_request)

        self.holdout.refresh_from_db()
        assert self.holdout.filters[0]["rollout_percentage"] == 20
        assert response.json().get("status") != "applied"

    def test_gated_delete_keeps_the_holdout_until_approval(self):
        self._create_policy("experiment_holdout.delete")

        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}")

        assert response.status_code == status.HTTP_409_CONFLICT
        change_request = self._change_request("experiment_holdout.delete")
        assert ExperimentHoldout.objects.filter(id=self.holdout.id).exists()
        self.flag.refresh_from_db()
        assert self.flag.filters["holdout"]["exclusion_percentage"] == 20

        approve = self._approve(change_request)

        assert approve.status_code == status.HTTP_200_OK
        assert not ExperimentHoldout.objects.filter(id=self.holdout.id).exists()
        self.flag.refresh_from_db()
        assert self.flag.filters.get("holdout") is None

    @parameterized.expand(
        [
            ("update", "experiment_holdout.update", {}),
            ("delete", "experiment_holdout.delete", {}),
            (
                "update_with_flag_field_condition",
                "experiment_holdout.update",
                {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50},
            ),
        ]
    )
    def test_a_flag_policy_alone_still_gates_a_holdout_change(self, operation, action_key, conditions):
        flag_policy = self._create_policy("feature_flag.update", conditions=conditions)

        if operation == "delete":
            response = self.client.delete(f"/api/projects/{self.team.id}/experiment_holdouts/{self.holdout.id}")
        else:
            response = self._patch_exclusion(40)

        assert response.status_code == status.HTTP_409_CONFLICT
        change_request = self._change_request(action_key)
        assert change_request.get_policy() == flag_policy
        self.flag.refresh_from_db()
        assert self.flag.filters["holdout"]["exclusion_percentage"] == 20

    def test_a_holdout_policy_takes_precedence_over_a_flag_policy(self):
        other_approver = User.objects.create_and_join(self.organization, "approver@posthog.com", None)
        self._create_policy("feature_flag.update")
        holdout_policy = self._create_policy("experiment_holdout.update", approver_ids=[other_approver.id])

        response = self._patch_exclusion(40)

        assert response.status_code == status.HTTP_409_CONFLICT
        change_request = self._change_request("experiment_holdout.update")
        assert change_request.get_policy() == holdout_policy
        assert change_request.policy_snapshot["users"] == [other_approver.id]
