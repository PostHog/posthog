from datetime import datetime

from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.test.base import APIBaseTest


class TestExperimentCRUD(APIBaseTest):
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
        self.assertEqual(response.json()["detail"], "Can't update keys: filters, get_feature_flag_key on Experiment")

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
                "filters": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Feature Flag key already exists. Please select a unique key")

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
        end_date = "2021-12-10T00:00"

        # Now try updating FF
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{id}",
            {
                "description": "Bazinga",
                "parameters": {"feature_flag_variants": [{"key": "control", "name": "X", "rollout_percentage": 100}]},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Can't update keys: parameters on Experiment")

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


class ClickhouseTestFunnelExperimentResults(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
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
        self.assertAlmostEqual(response_data["probability"]["test"], 0.2619, places=3)

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

        self.assertAlmostEqual(response_data["probability"]["test"], 0.095, places=3)
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.193, places=3)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.372, places=3)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.340, places=3)


class ClickhouseTestTrendExperimentResults(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results(self):
        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview", "timestamp": "2020-01-03",},],
                "person_out_of_end_date": [
                    {"event": "$pageview", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
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
                    "insight": "trends",
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

        self.assertEqual(result[0]["count"], 2)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 1)
        self.assertEqual("test", result[1]["breakdown_value"])

        # Variant with test: Beta(2, 1) and control: Beta(3, 1) distribution
        # The variant has low probability of being better.
        self.assertAlmostEqual(response_data["probability"]["test"], 0.313, places=3)

    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results_for_three_test_variants(self):
        journeys_for(
            {
                "person1_2": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_2"},},
                ],
                "person1_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                ],
                "person2_1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
                ],
                # "person1": [
                #     {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                # ],
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person4": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview", "timestamp": "2020-01-03",},],
                "person_out_of_end_date": [
                    {"event": "$pageview", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
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
        result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

        self.assertEqual(result[0]["count"], 3)
        self.assertEqual("control", result[0]["breakdown_value"])

        self.assertEqual(result[1]["count"], 2)
        self.assertEqual("test_1", result[1]["breakdown_value"])

        self.assertEqual(result[2]["count"], 1)
        self.assertEqual("test_2", result[2]["breakdown_value"])

        # test missing from results, since no events
        self.assertAlmostEqual(response_data["probability"]["test_1"], 0.299, places=3)
        self.assertAlmostEqual(response_data["probability"]["test_2"], 0.119, places=3)
        self.assertAlmostEqual(response_data["probability"]["control"], 0.583, places=3)
