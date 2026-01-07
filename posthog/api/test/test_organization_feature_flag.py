from typing import Any

from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest.mock import ANY

from rest_framework import status

from posthog.api.dashboards.dashboard import Dashboard
from posthog.models import FeatureFlag
from posthog.models.cohort import Cohort
from posthog.models.cohort.util import sort_cohorts_topologically
from posthog.models.experiment import Experiment
from posthog.models.surveys.survey import Survey
from posthog.models.team.team import Team

from products.early_access_features.backend.models import EarlyAccessFeature


class TestOrganizationFeatureFlagGet(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)
        self.team_3 = Team.objects.create(organization=self.organization)

        # Set deterministic API tokens to ensure stable query snapshots
        self.team_1.api_token = "phc_test_token_1"
        self.team_1.save()
        self.team_2.api_token = "phc_test_token_2"
        self.team_2.save()
        self.team_3.api_token = "phc_test_token_3"
        self.team_3.save()

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

        assert response.status_code == status.HTTP_200_OK

        expected_data = [
            {
                "flag_id": flag.id,
                "team_id": flag.team.id,
                "created_by": ANY,
                "filters": flag.get_filters(),
                "created_at": flag.created_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                "active": flag.active,
            }
            for flag in [self.feature_flag_1, self.feature_flag_2]
        ]
        assert sorted(response.json()) == sorted(expected_data)

    def test_get_feature_flag_not_found(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/nonexistent-flag"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_get_feature_flag_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestOrganizationFeatureFlagCopy(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        # Set deterministic API tokens to ensure stable query snapshots
        self.team_1.api_token = "phc_test_copy_token_1"
        self.team_1.save()
        self.team_2.api_token = "phc_test_copy_token_2"
        self.team_2.save()

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

        assert response.status_code == status.HTTP_200_OK
        assert "success" in response.json()
        assert "failed" in response.json()

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": self.feature_flag_to_copy.filters,
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "rollout_percentage": self.rollout_percentage_to_copy,
            "deleted": False,
            "created_by": ANY,
            "id": ANY,
            "created_at": ANY,
            "updated_at": ANY,
            "usage_dashboard": ANY,
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
            "evaluation_tags": [],
            "user_access_level": "manager",
            "is_remote_configuration": False,
            "has_encrypted_payloads": False,
            "status": "ACTIVE",
            "version": 1,
            "last_modified_by": ANY,
            "last_called_at": None,
            "evaluation_runtime": "all",
            "bucketing_identifier": "distinct_id",
        }

        flag_response = response.json()["success"][0]

        assert flag_response == expected_flag_response
        assert flag_response["created_by"]["id"] == self.user.id

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

        assert response.status_code == status.HTTP_200_OK
        assert "success" in response.json()
        assert "failed" in response.json()

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": self.feature_flag_to_copy.filters,
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "rollout_percentage": self.rollout_percentage_to_copy,
            "deleted": False,
            "created_by": ANY,
            "is_simple_flag": True,
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "has_enriched_analytics": False,
            "tags": [],
            "evaluation_tags": [],
            "id": ANY,
            "created_at": ANY,
            "updated_at": ANY,
            "usage_dashboard": ANY,
            "experiment_set": ANY,
            "surveys": ANY,
            "features": ANY,
            "analytics_dashboards": ANY,
            "user_access_level": "manager",
            "is_remote_configuration": False,
            "has_encrypted_payloads": False,
            "status": "ACTIVE",
            "version": 2,
            "last_modified_by": ANY,
            "last_called_at": None,
            "evaluation_runtime": "all",
            "bucketing_identifier": "distinct_id",
        }

        flag_response = response.json()["success"][0]

        assert flag_response == expected_flag_response

        # Linked instances must remain linked
        assert flag_response["created_by"]["id"] == self.user.id
        assert experiment.id == flag_response["experiment_set"][0]
        assert str(survey.id) == flag_response["surveys"][0]["id"]
        assert str(feature.id) == flag_response["features"][0]["id"]
        assert analytics_dashboard.id == flag_response["analytics_dashboards"][0]
        assert usage_dashboard.id == flag_response["usage_dashboard"]

    def test_copy_feature_flag_with_old_legacy_flags(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-to-copy-here",
            filters={},
            rollout_percentage=self.rollout_percentage_to_copy,
        )

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["success"]) == 1
        assert len(response.json()["failed"]) == 0

    def test_copy_feature_flag_update_override_deleted(self):
        target_project = self.team_2
        target_project_2 = Team.objects.create(organization=self.organization)
        # Set deterministic API token for newly created team
        target_project_2.api_token = "phc_test_copy_token_3"
        target_project_2.save()
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

        assert response.status_code == status.HTTP_200_OK
        assert "success" in response.json()
        assert "failed" in response.json()

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": self.feature_flag_to_copy.filters,
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "rollout_percentage": self.rollout_percentage_to_copy,
            "deleted": False,
            "created_by": ANY,
            "is_simple_flag": True,
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "has_enriched_analytics": False,
            "tags": [],
            "evaluation_tags": [],
            "id": ANY,
            "created_at": ANY,
            "updated_at": ANY,
            "usage_dashboard": ANY,
            "experiment_set": ANY,
            "surveys": ANY,
            "features": ANY,
            "analytics_dashboards": ANY,
            "user_access_level": "manager",
            "is_remote_configuration": False,
            "has_encrypted_payloads": False,
            "status": "ACTIVE",
            "version": 1,
            "last_modified_by": ANY,
            "last_called_at": None,
            "evaluation_runtime": "all",
            "bucketing_identifier": "distinct_id",
        }
        flag_response = response.json()["success"][0]

        assert flag_response == expected_flag_response
        assert flag_response["created_by"]["id"] == self.user.id

        # Linked instances must be overridden for a soft-deleted flag
        assert flag_response["experiment_set"] == []
        assert flag_response["surveys"] == []
        assert flag_response["usage_dashboard"] != existing_deleted_flag.usage_dashboard.id
        assert flag_response["analytics_dashboards"] == []

        # target_project_2 should have failed
        assert len(response.json()["failed"]) == 1
        assert response.json()["failed"][0]["project_id"] == target_project_2.id
        assert response.json()["failed"][0]["errors"] == "[ErrorDetail(string='Feature flag with this key already exists and is used in an experiment. Please delete the experiment before deleting the flag.', code='invalid')]"

    def test_copy_feature_flag_missing_fields(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data: dict[str, Any] = {}
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    def test_copy_feature_flag_nonexistent_key(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": "nonexistent-key",
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    def test_copy_feature_flag_to_nonexistent_target(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        nonexistent_project_id = 999
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [nonexistent_project_id],
        }

        response = self.client.post(url, data)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["success"]) == 0
        assert len(response.json()["failed"]) == 1
        assert nonexistent_project_id == response.json()["failed"][0]["project_id"]

    def test_copy_feature_flag_unauthorized(self):
        self.client.logout()
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_copy_feature_flag_cohort_nonexistent_in_destination(self):
        cohorts = {}
        creation_order = []

        def create_cohort(name, children):
            creation_order.append(name)
            properties = [{"key": "$some_prop", "value": "nomatchihope", "type": "person", "operator": "exact"}]
            if children:
                properties = [{"key": "id", "type": "cohort", "value": child.pk} for child in children]

            cohorts[name] = Cohort.objects.create(
                team=self.team,
                name=str(name),
                filters={
                    "properties": {
                        "type": "AND",
                        "values": properties,
                    }
                },
            )

        # link cohorts
        create_cohort(1, None)
        create_cohort(3, None)
        create_cohort(2, [cohorts[1]])
        create_cohort(4, [cohorts[2], cohorts[3]])
        create_cohort(5, [cohorts[4]])
        create_cohort(6, None)
        create_cohort(7, [cohorts[5], cohorts[6]])  # "head" cohort

        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-with-cohort",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": cohorts[7].pk,  # link "head" cohort
                            }
                        ],
                    }
                ]
            },
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK

        # check all cohorts were created in the destination project
        for name in creation_order:
            found_cohort = Cohort.objects.filter(name=str(name), team_id=target_project.id).exists()
            assert found_cohort

    def test_copy_feature_flag_cohort_nonexistent_in_destination_2(self):
        feature_flag_key = "flag-with-cohort"
        cohorts = {}

        def create_cohort(name):
            cohorts[name] = Cohort.objects.create(
                team=self.team,
                name=name,
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "name", "value": "test", "type": "person", "operator": "exact"},
                        ],
                    }
                },
            )

        create_cohort("a")
        create_cohort("b")
        create_cohort("c")
        create_cohort("d")

        def connect(parent, child):
            cohorts[parent].filters["properties"]["values"][0] = {
                "key": "id",
                "value": cohorts[child].pk,
                "type": "cohort",
            }
            cohorts[parent].save()

        connect("d", "b")
        connect("a", "d")
        connect("c", "a")

        head_cohort = cohorts["c"]
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=feature_flag_key,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": head_cohort.pk,  # link "head" cohort
                            }
                        ],
                    }
                ]
            },
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK

        # check all cohorts were created in the destination project
        for name in cohorts.keys():
            found_cohort = Cohort.objects.filter(name=name, team_id=target_project.id)[0]
            assert found_cohort

        # destination flag contains the head cohort
        destination_flag = FeatureFlag.objects.get(key=feature_flag_key, team_id=target_project.id)
        destination_flag_head_cohort_id = destination_flag.filters["groups"][0]["properties"][0]["value"]
        destination_head_cohort = Cohort.objects.get(pk=destination_flag_head_cohort_id, team_id=target_project.id)
        assert destination_head_cohort.name == head_cohort.name
        assert destination_head_cohort.id != head_cohort.id

        # get topological order of the original cohorts
        original_cohorts_cache = {}
        for _, cohort in cohorts.items():
            original_cohorts_cache[cohort.id] = cohort
        original_cohort_ids = set(original_cohorts_cache.keys())
        topologically_sorted_original_cohort_ids = sort_cohorts_topologically(
            original_cohort_ids, original_cohorts_cache
        )

        # drill down the destination cohorts in the reverse topological order
        # the order of names should match the reverse topological order of the original cohort names
        topologically_sorted_original_cohort_ids_reversed = topologically_sorted_original_cohort_ids[::-1]

        def traverse(cohort, index):
            expected_cohort_id = topologically_sorted_original_cohort_ids_reversed[index]
            expected_name = original_cohorts_cache[expected_cohort_id].name
            assert expected_name == cohort.name

            prop = cohort.filters["properties"]["values"][0]
            if prop["type"] == "cohort":
                next_cohort_id = prop["value"]
                next_cohort = Cohort.objects.get(pk=next_cohort_id, team_id=target_project.id)
                traverse(next_cohort, index + 1)

        traverse(destination_head_cohort, 0)

    def test_copy_feature_flag_destination_cohort_not_overridden(self):
        cohort_name = "cohort-1"
        target_project = self.team_2
        original_cohort = Cohort.objects.create(
            team=self.team,
            name=cohort_name,
            groups=[{"properties": [{"key": "$some_prop", "value": "original_value", "type": "person"}]}],
        )

        destination_cohort_prop_value = "destination_value"
        Cohort.objects.create(
            team=target_project,
            name=cohort_name,
            groups=[{"properties": [{"key": "$some_prop", "value": destination_cohort_prop_value, "type": "person"}]}],
        )

        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-with-cohort",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": original_cohort.pk,
                            }
                        ],
                    }
                ]
            },
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK

        destination_cohort = Cohort.objects.filter(name=cohort_name, team=target_project).first()
        assert destination_cohort is not None
        # check destination value not overwritten

        if destination_cohort is not None:
            assert destination_cohort.groups[0]["properties"][0]["value"] == destination_cohort_prop_value

    def test_copy_remote_config_flag_preserves_type(self):
        """Test that copying a remote config flag preserves the is_remote_configuration field."""
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        remote_config_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="remote-config-flag",
            filters={"groups": [{"rollout_percentage": 100}], "payloads": {"true": '{"key": "value"}'}},
            rollout_percentage=100,
            is_remote_configuration=True,
            has_encrypted_payloads=False,
        )

        data = {
            "feature_flag_key": remote_config_flag.key,
            "from_project": remote_config_flag.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert "success" in response.json()
        assert len(response.json()["success"]) == 1

        flag_response = response.json()["success"][0]
        assert flag_response["is_remote_configuration"]
        assert not flag_response["has_encrypted_payloads"]
        assert flag_response["key"] == remote_config_flag.key

        # Verify the flag in the database
        copied_flag = FeatureFlag.objects.get(key=remote_config_flag.key, team=target_project)
        assert copied_flag.is_remote_configuration
        assert not copied_flag.has_encrypted_payloads

    def test_copy_encrypted_payloads_flag(self):
        """Test that copying a flag with encrypted payloads decrypts them before copying."""
        from posthog.helpers.encrypted_flag_payloads import encrypt_flag_payloads

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        # Create a flag with encrypted payloads
        flag_data = {
            "groups": [{"rollout_percentage": 100}],
            "payloads": {"true": '{"key": "secret_value"}'},
        }
        encrypt_flag_payloads({"has_encrypted_payloads": True, "filters": flag_data})

        encrypted_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="encrypted-flag",
            filters=flag_data,
            rollout_percentage=100,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        data = {
            "feature_flag_key": encrypted_flag.key,
            "from_project": encrypted_flag.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert "success" in response.json()
        assert len(response.json()["success"]) == 1

        flag_response = response.json()["success"][0]
        assert flag_response["is_remote_configuration"]
        assert flag_response["has_encrypted_payloads"]
        assert flag_response["key"] == encrypted_flag.key

        # Verify the flag in the database has encrypted payloads
        copied_flag = FeatureFlag.objects.get(key=encrypted_flag.key, team=target_project)
        assert copied_flag.is_remote_configuration
        assert copied_flag.has_encrypted_payloads

        # Verify the encrypted payload can be decrypted back to the original value
        from posthog.helpers.encrypted_flag_payloads import get_decrypted_flag_payload

        decrypted_payload = get_decrypted_flag_payload(copied_flag.filters["payloads"]["true"], should_decrypt=True)
        assert decrypted_payload == '{"key": "secret_value"}'

    def test_copy_encrypted_payloads_flag_to_multiple_projects(self):
        """Test that copying a flag with encrypted payloads to multiple projects works correctly."""
        from posthog.helpers.encrypted_flag_payloads import encrypt_flag_payloads, get_decrypted_flag_payload

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        # Create third team for testing multiple targets
        team_3 = Team.objects.create(organization=self.organization)
        team_3.api_token = "phc_test_copy_token_3"
        team_3.save()

        # Create a flag with encrypted payloads
        flag_data = {
            "groups": [{"rollout_percentage": 100}],
            "payloads": {"true": '{"key": "secret_value"}'},
        }
        encrypt_flag_payloads({"has_encrypted_payloads": True, "filters": flag_data})

        encrypted_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="encrypted-multi-flag",
            filters=flag_data,
            rollout_percentage=100,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        data = {
            "feature_flag_key": encrypted_flag.key,
            "from_project": encrypted_flag.team_id,
            "target_project_ids": [self.team_2.id, team_3.id],
        }
        response = self.client.post(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert "success" in response.json()
        assert len(response.json()["success"]) == 2

        # Verify both copied flags have correctly encrypted payloads
        for target_team in [self.team_2, team_3]:
            copied_flag = FeatureFlag.objects.get(key=encrypted_flag.key, team=target_team)
            assert copied_flag.is_remote_configuration
            assert copied_flag.has_encrypted_payloads

            # Verify the encrypted payload can be decrypted back to the original value
            decrypted_payload = get_decrypted_flag_payload(copied_flag.filters["payloads"]["true"], should_decrypt=True)
            assert decrypted_payload == '{"key": "secret_value"}'
