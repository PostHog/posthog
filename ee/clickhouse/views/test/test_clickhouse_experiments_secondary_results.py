from datetime import datetime

from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from ee.clickhouse.test.test_journeys import journeys_for
from ee.clickhouse.util import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.test.base import APIBaseTest


class ClickhouseTestExperimentSecondaryResults(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_basic_secondary_metric_results(self):
        journeys_for(
            {
                # For a trend pageview metric
                "person1": [
                    {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test"},},
                ],
                "person2": [
                    {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
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
                # for a funnel conversion metric
                "person1_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave_funnel",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave_funnel",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave_funnel",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control_funnel": [
                    {"event": "$pageview_funnel", "timestamp": "2020-01-03",},
                    {"event": "$pageleave_funnel", "timestamp": "2020-01-05",},
                ],
                "person_out_of_end_date_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave_funnel",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person5_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
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
                "parameters": {
                    "secondary_metrics": [
                        {
                            "insight": "trends",
                            "events": [{"order": 0, "id": "$pageview"}],
                            "properties": [
                                {
                                    "key": "$geoip_country_name",
                                    "type": "person",
                                    "value": ["france"],
                                    "operator": "exact",
                                }
                                # properties superceded by FF breakdown
                            ],
                        },
                        {
                            "insight": "funnels",
                            "events": [{"order": 0, "id": "$pageview_funnel"}, {"order": 1, "id": "$pageleave_funnel"}],
                            "properties": [
                                {
                                    "key": "$geoip_country_name",
                                    "type": "person",
                                    "value": ["france"],
                                    "operator": "exact",
                                }
                                # properties superceded by FF breakdown
                            ],
                        },
                    ]
                },
                # target metric insignificant since we're testing secondaries right now
                "filters": {"insight": "trends", "events": [{"order": 0, "id": "whatever"}],},
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()

        self.assertEqual(len(response_data["result"].items()), 2)

        self.assertEqual(response_data["result"]["control"], 3)
        self.assertEqual(response_data["result"]["test"], 1)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        self.assertEqual(200, response.status_code)

        response_data = response.json()

        self.assertEqual(len(response_data["result"].items()), 2)

        self.assertAlmostEqual(response_data["result"]["control"], 1)
        self.assertEqual(response_data["result"]["test"], 1 / 3)

    # @snapshot_clickhouse_queries
    # def test_experiment_flow_with_event_results_for_three_test_variants(self):
    #     journeys_for(
    #         {
    #             "person1_2": [
    #                 {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_2"},},
    #             ],
    #             "person1_1": [
    #                 {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
    #             ],
    #             "person2_1": [
    #                 {"event": "$pageview", "timestamp": "2020-01-02", "properties": {"$feature/a-b-test": "test_1"},},
    #             ],
    #             "person2": [
    #                 {"event": "$pageview", "timestamp": "2020-01-03", "properties": {"$feature/a-b-test": "control"}},
    #             ],
    #             "person3": [
    #                 {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
    #             ],
    #             "person4": [
    #                 {"event": "$pageview", "timestamp": "2020-01-04", "properties": {"$feature/a-b-test": "control"}},
    #             ],
    #             # doesn't have feature set
    #             "person_out_of_control": [{"event": "$pageview", "timestamp": "2020-01-03",},],
    #             "person_out_of_end_date": [
    #                 {"event": "$pageview", "timestamp": "2020-08-03", "properties": {"$feature/a-b-test": "control"}},
    #             ],
    #         },
    #         self.team,
    #     )

    #     ff_key = "a-b-test"
    #     # generates the FF which should result in the above events^
    #     response = self.client.post(
    #         f"/api/projects/{self.team.id}/experiments/",
    #         {
    #             "name": "Test Experiment",
    #             "description": "",
    #             "start_date": "2020-01-01T00:00",
    #             "end_date": "2020-01-06T00:00",
    #             "feature_flag_key": ff_key,
    #             "parameters": {
    #                 "feature_flag_variants": [
    #                     {"key": "control", "name": "Control Group", "rollout_percentage": 25},
    #                     {"key": "test_1", "name": "Test Variant 1", "rollout_percentage": 25},
    #                     {"key": "test_2", "name": "Test Variant 2", "rollout_percentage": 25},
    #                     {"key": "test", "name": "Test Variant 3", "rollout_percentage": 25},
    #                 ]
    #             },
    #             "filters": {
    #                 "insight": "trends",
    #                 "events": [{"order": 0, "id": "$pageview"}, {"order": 1, "id": "$pageleave"}],
    #                 "properties": [
    #                     {"key": "$geoip_country_name", "type": "person", "value": ["france"], "operator": "exact"}
    #                     # properties superceded by FF breakdown
    #                 ],
    #             },
    #         },
    #     )

    #     id = response.json()["id"]

    #     response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/results")
    #     self.assertEqual(200, response.status_code)

    #     response_data = response.json()
    #     result = sorted(response_data["insight"], key=lambda x: x["breakdown_value"])

    #     self.assertEqual(result[0]["count"], 3)
    #     self.assertEqual("control", result[0]["breakdown_value"])

    #     self.assertEqual(result[1]["count"], 2)
    #     self.assertEqual("test_1", result[1]["breakdown_value"])

    #     self.assertEqual(result[2]["count"], 1)
    #     self.assertEqual("test_2", result[2]["breakdown_value"])

    #     # test missing from results, since no events
    #     self.assertAlmostEqual(response_data["probability"]["test_1"], 0.299, places=2)
    #     self.assertAlmostEqual(response_data["probability"]["test_2"], 0.119, places=2)
    #     self.assertAlmostEqual(response_data["probability"]["control"], 0.583, places=2)
