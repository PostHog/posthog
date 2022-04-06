import pytest
from flaky import flaky
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.constants import ExperimentSignificanceCode
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag


class TestExperimentCRUD(APILicensedTest):

    # List experiments
    def test_can_list_experiments(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_archived_experiments(self):
        archived_experiment = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": "a-b-tests",
                "archived": True,
                "parameters": None,
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )
        non_archived_experiment = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": "a-b-tests2",
                "parameters": None,
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )
        response = self.client.get(f"/api/projects/{self.team.id}/experiments?archived=true",)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], archived_experiment.json()["id"])

    @pytest.mark.skip_on_multitenancy
    def test_cannot_list_experiments_without_proper_license(self):
        self.organization.available_features = []
        self.organization.save()
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/")
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.json(), self.license_required_response())

    def test_creating_updating_basic_experiment(self):
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
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"][0]["key"], "$geoip_country_name")

        id = response.json()["id"]
        end_date = "2021-12-10T00:00"

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}", {"description": "Bazinga", "end_date": end_date,},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")
        self.assertEqual(experiment.end_date.strftime("%Y-%m-%dT%H:%M"), end_date)

    def test_invalid_create(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": None,  # invalid
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},  # also invalid
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "None",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {},  # still invalid
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Filters are required to create an Experiment")

    def test_invalid_update(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "filters": {}, "feature_flag_key": "new_key",},  # invalid
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update keys: get_feature_flag_key on Experiment")

    def test_cant_reuse_existing_feature_flag(self):
        ff_key = "a-b-test"
        FeatureFlag.objects.create(
            team=self.team, rollout_percentage=50, name="Beta feature", key=ff_key, created_by=self.user,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {"events": []},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "There is already a feature flag with this key.")

    def test_draft_experiment_doesnt_have_FF_active(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

    def test_draft_experiment_doesnt_have_FF_active_even_after_updates(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}", {"description": "Bazinga", "filters": {},},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)  # didn't change to enabled while still draft

        # Now launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}", {"start_date": "2021-12-01T10:23",},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertTrue(created_ff.active)

    def test_draft_experiment_participants_update_updates_FF(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)

        # Now update
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)  # didn't change to enabled while still draft
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"][0]["key"], "$geoip_country_name")

        # Now launch experiment
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}", {"start_date": "2021-12-01T10:23",},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertTrue(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"][0]["key"], "$geoip_country_name")

    def test_launching_draft_experiment_activates_FF(self):
        # Draft experiment
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {},
                "filters": {"events": []},
            },
        )

        id = response.json()["id"]
        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "start_date": "2021-12-01T10:23"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertTrue(updated_ff.active)

    def test_create_multivariate_experiment(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                        {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                        {"key": "test_2", "name": "Test Variant", "rollout_percentage": 34},
                    ]
                },
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.active, True)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test_1")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][2]["key"], "test_2")
        self.assertEqual(created_ff.filters["groups"][0]["properties"][0]["key"], "$geoip_country_name")

        id = response.json()["id"]

        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {"feature_flag_variants": [{"key": "control", "name": "X", "rollout_percentage": 33}]},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update feature_flag_variants on Experiment")

        # Now try changing FF rollout %s
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 34},
                        {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                        {"key": "test_2", "name": "Test Variant", "rollout_percentage": 32},
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update feature_flag_variants on Experiment")

        # Now try changing FF keys
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                        {"key": "test", "name": "Test Variant", "rollout_percentage": 33},
                        {"key": "test2", "name": "Test Variant", "rollout_percentage": 34},
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update feature_flag_variants on Experiment")

        # Now try updating other parameter keys
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {"description": "Bazinga", "parameters": {"recommended_sample_size": 1500},},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["parameters"]["recommended_sample_size"], 1500)

    def test_creating_invalid_multivariate_experiment_no_control(self):
        ff_key = "a-b-test"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        # no control
                        {"key": "test_0", "name": "Control Group", "rollout_percentage": 33},
                        {"key": "test_1", "name": "Test Variant", "rollout_percentage": 33},
                        {"key": "test_2", "name": "Test Variant", "rollout_percentage": 33},
                    ]
                },
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Feature flag variants must contain a control variant")

    def test_deleting_experiment_soft_deletes_feature_flag(self):
        ff_key = "a-b-tests"
        data = {
            "name": "Test Experiment",
            "description": "",
            "start_date": "2021-12-01T10:23",
            "end_date": None,
            "feature_flag_key": ff_key,
            "parameters": None,
            "filters": {
                "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                "properties": [
                    {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                ],
            },
        }
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        id = response.json()["id"]

        # Now delete the experiment
        response = self.client.delete(f"/api/projects/{self.team.id}/experiments/{id}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(Experiment.DoesNotExist):
            Experiment.objects.get(pk=id)

        # soft deleted
        self.assertEqual(FeatureFlag.objects.get(pk=created_ff.id).deleted, True)

        # can recreate new experiment with same FF key
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_deleting_feature_flag_deletes_experiment(self):
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
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        id = response.json()["id"]

        # Now delete the feature flag
        response = self.client.delete(f"/api/projects/{self.team.id}/feature_flags/{created_ff.pk}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FeatureFlag.objects.filter(pk=created_ff.pk).exists())

        with self.assertRaises(Experiment.DoesNotExist):
            Experiment.objects.get(pk=id)

    def test_creating_updating_experiment_with_group_aggregation(self):
        ff_key = "a-b-tests"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": None,
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": ["technology"],
                            "operator": "exact",
                            "group_type_index": 1,
                        }
                    ],
                    "aggregation_group_type_index": 1,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        created_ff = FeatureFlag.objects.get(key=ff_key)

        self.assertEqual(created_ff.key, ff_key)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"][0]["key"], "industry")
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 1)

        id = response.json()["id"]

        # Now update group type index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [],
                    "aggregation_group_type_index": 0,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"], [])
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], 0)

        # Now remove group type index
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "filters": {
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                    # "aggregation_group_type_index": None, # removed key
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment = Experiment.objects.get(pk=id)
        self.assertEqual(experiment.description, "Bazinga")

        created_ff = FeatureFlag.objects.get(key=ff_key)
        self.assertEqual(created_ff.key, ff_key)
        self.assertFalse(created_ff.active)
        self.assertEqual(created_ff.filters["multivariate"]["variants"][0]["key"], "control")
        self.assertEqual(created_ff.filters["multivariate"]["variants"][1]["key"], "test")
        self.assertEqual(created_ff.filters["groups"][0]["properties"][0]["key"], "$geoip_country_name")
        self.assertEqual(created_ff.filters["aggregation_group_type_index"], None)


@flaky(max_runs=10, min_passes=1)
class ClickhouseTestFunnelExperimentResults(ClickhouseTestMixin, APILicensedTest):
    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results(self):
        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03",},
                    {"event": "$pageleave", "timestamp": "2020-01-05",},
                ],
                "person_out_of_end_date": [
                    {"event": "$pageview", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-08-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                # non-converters with FF
                "person4": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person5": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test"},},
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "funnels",
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                        # properties superceded by FF breakdown
                    ],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        # Variant with test: Beta(2, 3) and control: Beta(3, 1) distribution
        # The variant has very low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.114, places=2)
        self.assertEqual(response_data["significance_code"], ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_for_three_test_variants(self):
        journeys_for(
            {
                "person1_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_2"},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test_2"},},
                ],
                "person1_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test_1"},},
                ],
                "person2_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test_1"},},
                ],
                "person1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03",},
                    {"event": "$pageleave", "timestamp": "2020-01-05",},
                ],
                "person_out_of_end_date": [
                    {"event": "$pageview", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-08-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                # non-converters with FF
                "person4": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person5": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person6_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 25},
                        {"key": "test_1", "name": "Test Variant 1", "rollout_percentage": 25},
                        {"key": "test_2", "name": "Test Variant 2", "rollout_percentage": 25},
                        {"key": "test", "name": "Test Variant 3", "rollout_percentage": 25},
                    ]
                },
                "filters": {
                    "insight": "funnels",
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                        # properties superceded by FF breakdown
                    ],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = sorted(response_data["insight"], key=lambda x: x[0]["breakdown_value"][0])

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("control", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 2)
        self.assertEqual("control", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 3)
        self.assertEqual("test", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 1)
        self.assertEqual("test", result[1][1]["breakdown_value"][0])

        self.assertAlmostEqual(response_data["probability"]["test"], 0.031, places=1)
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.158, places=1)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.324, places=1)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.486, places=1)
        self.assertEqual(response_data["significance_code"], ExperimentSignificanceCode.NOT_ENOUGH_EXPOSURE)
        self.assertAlmostEqual(response_data["expected_loss"], 1, places=2)


@flaky(max_runs=10, min_passes=1)
class ClickhouseTestTrendExperimentResults(ClickhouseTestMixin, APILicensedTest):
    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results(self):
        journeys_for(
            {
                "person1": [
                    # 5 counts, single person
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    # exposure measured via $feature_flag_called events
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                    # 1 exposure, but more absolute counts
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageview", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03",},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "random"},
                    },
                ],
                "person_out_of_end_date": [
                    {"event": "$pageview", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {
                    "insight": "TRENDS",
                    "events": [{"order": 0, "id": "$pageview"}],
                    "display": "ActionsLineGraphCumulative",
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                        # properties superceded by FF breakdown
                    ],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 5)
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Gamma(5, 0.5) and control: Gamma(5, 1) distribution
        # The variant has high probability of being better. (effectively Gamma(10,1))
        self.assertAlmostEqual(response_data["probability"]["test"], 0.923, places=2)
        self.assertFalse(response_data["significant"])

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_for_three_test_variants(self):
        journeys_for(
            {
                "person1_2": [
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_2"},},
                ],
                "person1_1": [
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                ],
                "person2_1": [
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                ],
                # "person1": [
                #     {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                # ],
                "person2": [
                    {"event": "$pageview1", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview1", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person4": [
                    {"event": "$pageview1", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview1", "timestamp": "2020-01-03",},],
                "person_out_of_end_date": [
                    {"event": "$pageview1", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 25},
                        {"key": "test_1", "name": "Test Variant 1", "rollout_percentage": 25},
                        {"key": "test_2", "name": "Test Variant 2", "rollout_percentage": 25},
                        {"key": "test", "name": "Test Variant 3", "rollout_percentage": 25},
                    ]
                },
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "$pageview1"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                        # properties superceded by FF breakdown
                    ],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 3)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 2)
        self.assertEqual("test_1", result[1]["breakdown_value"])

        self.assertEqual(result[2]["count"], 1)
        self.assertEqual("test_2", result[2]["breakdown_value"])

        # test missing from results, since no events
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.299, places=2)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.119, places=2)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.583, places=2)

    def test_experiment_flow_with_event_results_for_two_test_variants_with_varying_exposures(self):
        journeys_for(
            {
                "person1_2": [
                    # for count data
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_2"},},
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_2"},},
                    # for exposure counting (counted as 1 only)
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_2"},
                    },
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_2"},
                    },
                ],
                "person1_1": [
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_1"},
                    },
                ],
                "person2_1": [
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                    {"event": "$pageview1", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "test_1"},
                    },
                ],
                "person2": [
                    {"event": "$pageview1", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageview1", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                    # 0 exposure shouldn't ideally happen, but it's possible
                ],
                "person3": [
                    {"event": "$pageview1", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                "person4": [
                    {"event": "$pageview1", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview1", "timestamp": "2020-01-03",},],
                "person_out_of_end_date": [
                    {"event": "$pageview1", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
                    {
                        "event": "$feature_flag_called",
                        "timestamp": "2020-08-02",
                        "properties": {"$feature_flag": "a-b-test", "$feature_flag_response": "control"},
                    },
                ],
            },
            self.team,
        )

        ff_key = "a-b-test"
        # generates the FF which should result in the above events^
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "",
                "start_date": "2020-01-01T00:00",
                "end_date": "2020-01-06T00:00",
                "feature_flag_key": ff_key,
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control Group", "rollout_percentage": 33},
                        {"key": "test_1", "name": "Test Variant 1", "rollout_percentage": 33},
                        {"key": "test_2", "name": "Test Variant 2", "rollout_percentage": 34},
                    ]
                },
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "$pageview1"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                        # properties superceded by FF breakdown
                    ],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 4)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 3)
        self.assertEqual("test_1", result[1]["breakdown_value"])

        self.assertEqual(result[2]["count"], 2)
        self.assertEqual("test_2", result[2]["breakdown_value"])

        # control: Gamma(4, 1)
        # test1: Gamma(3, 1)
        # test2: Gamma(2, 0.5)
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.177, places=2)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.488, places=2)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.334, places=2)
