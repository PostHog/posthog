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
            {"description": "Bazinga", "filters": {}, "feature_flag_key": "new_key",},  # invalid  # invalid
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


class ClickhouseTestFunnelExperimentResults(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_experiment_flow_with_event_results(self):
        journeys_for(
            {
                "person1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                    {"event": "$pageleave", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "test"},},
                ],
                # doesn't have feature set
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
                "person3": [
                    {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
                    {"event": "$pageleave", "timestamp": "2020-01-05", "properties": {"$feature/a-b-test": "control"}},
                ],
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
                    "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
                    "properties": [
                        {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
                    ],
                },
            },
        )

        id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result = response_data["funnel"]

        self.assertEqual(result[0][0]["name"], "$pageview")
        self.assertEqual(result[0][0]["count"], 2)
        self.assertEqual("test", result[0][0]["breakdown_value"][0])

        self.assertEqual(result[0][1]["name"], "$pageleave")
        self.assertEqual(result[0][1]["count"], 1)
        self.assertEqual("test", result[0][1]["breakdown_value"][0])

        self.assertEqual(result[1][0]["name"], "$pageview")
        self.assertEqual(result[1][0]["count"], 2)
        self.assertEqual("control", result[1][0]["breakdown_value"][0])

        self.assertEqual(result[1][1]["name"], "$pageleave")
        self.assertEqual(result[1][1]["count"], 2)
        self.assertEqual("control", result[1][1]["breakdown_value"][0])

        # Variant with True: Beta(2, 3) and empty: Beta(3, 1) distribution
        # probability tells the variant has low probability of being better.
        self.assertTrue(response_data["probability"] < 0.5)
