from typing import Any
from flaky import flaky


from ee.api.test.base import APILicensedTest
from posthog.models.signals import mute_selected_signals
from posthog.test.base import ClickhouseTestMixin, snapshot_clickhouse_queries
from posthog.test.test_journeys import journeys_for

DEFAULT_JOURNEYS_FOR_PAYLOAD: dict[str, list[dict[str, Any]]] = {
    # For a trend pageview metric
    "person1": [
        {
            "event": "$pageview",
            "timestamp": "2020-01-02",
            "properties": {"$feature/a-b-test": "test"},
        }
    ],
    "person2": [
        {
            "event": "$pageview",
            "timestamp": "2020-01-03",
            "properties": {"$feature/a-b-test": "control"},
        },
        {
            "event": "$pageview",
            "timestamp": "2020-01-03",
            "properties": {"$feature/a-b-test": "control"},
        },
    ],
    "person3": [
        {
            "event": "$pageview",
            "timestamp": "2020-01-04",
            "properties": {"$feature/a-b-test": "control"},
        }
    ],
    # doesn't have feature set
    "person_out_of_control": [{"event": "$pageview", "timestamp": "2020-01-03"}],
    "person_out_of_end_date": [
        {
            "event": "$pageview",
            "timestamp": "2020-08-03",
            "properties": {"$feature/a-b-test": "control"},
        }
    ],
    # wrong feature set somehow
    "person_out_of_feature_control": [
        {
            "event": "$pageview",
            "timestamp": "2020-01-03",
            "properties": {"$feature/a-b-test": "ablahebf"},
        }
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
        {"event": "$pageview_funnel", "timestamp": "2020-01-03"},
        {"event": "$pageleave_funnel", "timestamp": "2020-01-05"},
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
        }
    ],
    "person5_funnel": [
        {
            "event": "$pageview_funnel",
            "timestamp": "2020-01-04",
            "properties": {"$feature/a-b-test": "test"},
        }
    ],
}

DEFAULT_EXPERIMENT_CREATION_PAYLOAD = {
    "name": "Test Experiment",
    "description": "",
    "start_date": "2020-01-01T00:00",
    "end_date": "2020-01-06T00:00",
    "feature_flag_key": "a-b-test",
    "parameters": {},
    "secondary_metrics": [
        {
            "name": "trends whatever",
            "filters": {
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
        },
        {
            "name": "funnels whatever",
            "filters": {
                "insight": "funnels",
                "events": [
                    {"order": 0, "id": "$pageview_funnel"},
                    {"order": 1, "id": "$pageleave_funnel"},
                ],
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
        },
    ],
    # target metric insignificant since we're testing secondaries right now
    "filters": {"insight": "trends", "events": [{"order": 0, "id": "whatever"}]},
}


@flaky(max_runs=10, min_passes=1)
class ClickhouseTestExperimentSecondaryResults(ClickhouseTestMixin, APILicensedTest):
    @snapshot_clickhouse_queries
    def test_basic_secondary_metric_results(self):
        journeys_for(
            DEFAULT_JOURNEYS_FOR_PAYLOAD,
            self.team,
        )

        # :KLUDGE: Avoid calling sync_insight_caching_state which messes with snapshots
        with mute_selected_signals():
            # generates the FF which should result in the above events^
            creation_response = self.client.post(
                f"/api/projects/{self.team.id}/experiments/",
                DEFAULT_EXPERIMENT_CREATION_PAYLOAD,
            )

            id = creation_response.json()["id"]

            response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
            self.assertEqual(200, response.status_code)

            response_data = response.json()["result"]

            self.assertEqual(len(response_data["result"].items()), 2)

            self.assertEqual(response_data["result"]["control"], 3)
            self.assertEqual(response_data["result"]["test"], 1)

            response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
            self.assertEqual(200, response.status_code)

            response_data = response.json()["result"]

            self.assertEqual(len(response_data["result"].items()), 2)

            self.assertAlmostEqual(response_data["result"]["control"], 1)
            self.assertEqual(response_data["result"]["test"], round(1 / 3, 3))

    def test_basic_secondary_metric_results_cached(self):
        journeys_for(
            DEFAULT_JOURNEYS_FOR_PAYLOAD,
            self.team,
        )

        # generates the FF which should result in the above events^
        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            DEFAULT_EXPERIMENT_CREATION_PAYLOAD,
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        self.assertEqual(response_data.pop("is_cached"), False)

        response_data = response_data["result"]
        self.assertEqual(len(response_data["result"].items()), 2)

        self.assertEqual(response_data["result"]["control"], 3)
        self.assertEqual(response_data["result"]["test"], 1)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result_data = response_data["result"]

        self.assertEqual(len(result_data["result"].items()), 2)

        self.assertAlmostEqual(result_data["result"]["control"], 1)
        self.assertEqual(result_data["result"]["test"], round(1 / 3, 3))

        response2 = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        response2_data = response2.json()

        self.assertEqual(response2_data.pop("is_cached"), True)
        self.assertEqual(response2_data["result"], response_data["result"])

    def test_secondary_metric_results_for_multiple_variants(self):
        journeys_for(
            {
                # trend metric first
                "person1_2_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    }
                ],
                "person1_1_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_1_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person3_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person4_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview_trend", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # funnel metric second
                "person1_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                ],
                "person1_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                ],
                "person2_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                ],
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-01-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person6_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
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
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant 1",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant 2",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant 3",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "secondary_metrics": [
                    {
                        "name": "secondary metric",
                        "filters": {
                            "insight": "trends",
                            "events": [{"order": 0, "id": "$pageview_trend"}],
                        },
                    },
                    {
                        "name": "funnel metric",
                        "filters": {
                            "insight": "funnels",
                            "events": [
                                {"order": 0, "id": "$pageview"},
                                {"order": 1, "id": "$pageleave"},
                            ],
                        },
                    },
                ],
                # target metric insignificant since we're testing secondaries right now
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "whatever"}],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]

        # trend missing 'test' variant, so it's not in the results
        self.assertEqual(len(response_data["result"].items()), 3)

        self.assertEqual(response_data["result"]["control"], 3)
        self.assertEqual(response_data["result"]["test_1"], 2)
        self.assertEqual(response_data["result"]["test_2"], 1)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]

        # funnel not missing 'test' variant, so it's in the results
        self.assertEqual(len(response_data["result"].items()), 4)

        self.assertAlmostEqual(response_data["result"]["control"], 1)
        self.assertAlmostEqual(response_data["result"]["test"], round(1 / 3, 3))
        self.assertAlmostEqual(response_data["result"]["test_1"], round(2 / 3, 3))
        self.assertAlmostEqual(response_data["result"]["test_2"], 1)

    def test_secondary_metric_results_for_multiple_variants_with_trend_count_per_actor(self):
        journeys_for(
            {
                # trend metric first
                "person1_2_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    }
                ],
                "person1_1_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_1_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person3_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person4_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview_trend", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # avg count per user metric second
                "person1_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    },
                ],
                "person1_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                ],
                "person2_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test_1"},
                    },
                ],
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # non-converters with FF
                "person4": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person5": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
                "person6_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
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
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant 1",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant 2",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant 3",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "secondary_metrics": [
                    {
                        "name": "secondary metric",
                        "filters": {
                            "insight": "trends",
                            "events": [{"order": 0, "id": "$pageview_trend"}],
                        },
                    },
                    {
                        "name": "funnel metric",
                        "filters": {
                            "insight": "trends",
                            "events": [
                                {
                                    "order": 0,
                                    "id": "$pageview",
                                    "math": "avg_count_per_actor",
                                }
                            ],
                        },
                    },
                ],
                # target metric insignificant since we're testing secondaries right now
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "whatever"}],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]

        # trend missing 'test' variant, so it's not in the results
        self.assertEqual(len(response_data["result"].items()), 3)

        self.assertEqual(response_data["result"]["control"], 3)
        self.assertEqual(response_data["result"]["test_1"], 2)
        self.assertEqual(response_data["result"]["test_2"], 1)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]

        # funnel not missing 'test' variant, so it's in the results
        self.assertEqual(len(response_data["result"].items()), 4)

        self.assertAlmostEqual(response_data["result"]["control"], round(3.5 / 6, 3), 3)
        self.assertAlmostEqual(response_data["result"]["test"], 0.5)
        self.assertAlmostEqual(response_data["result"]["test_1"], 0.5)
        self.assertAlmostEqual(response_data["result"]["test_2"], round(1 / 3, 3), 3)

    def test_secondary_metric_results_for_multiple_variants_with_trend_count_per_property_value(self):
        journeys_for(
            {
                # trend metric first
                "person1_2_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2"},
                    }
                ],
                "person1_1_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_1_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1"},
                    }
                ],
                "person2_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person3_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                "person4_trend": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview_trend", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview_trend",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # avg per mathable property second
                "person1_2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_2", "mathable": 2},
                    },
                ],
                "person1_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1", "mathable": 1},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1", "mathable": 2},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test_1", "mathable": 3},
                    },
                ],
                "person2_1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "test_1", "mathable": 10},
                    },
                ],
                "person1": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-02",
                        "properties": {"$feature/a-b-test": "test", "mathable": 200},
                    },
                ],
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                "person3": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [
                    {"event": "$pageview", "timestamp": "2020-01-03"},
                    {"event": "$pageleave", "timestamp": "2020-01-05"},
                ],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageleave",
                        "timestamp": "2020-08-05",
                        "properties": {"$feature/a-b-test": "control"},
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
                    "feature_flag_variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_1",
                            "name": "Test Variant 1",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test_2",
                            "name": "Test Variant 2",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant 3",
                            "rollout_percentage": 25,
                        },
                    ]
                },
                "secondary_metrics": [
                    {
                        "name": "secondary metric",
                        "filters": {
                            "insight": "trends",
                            "events": [{"order": 0, "id": "$pageview_trend"}],
                        },
                    },
                    {
                        "name": "funnel metric",
                        "filters": {
                            "insight": "trends",
                            "events": [
                                {
                                    "order": 0,
                                    "id": "$pageview",
                                    "math": "avg",
                                    "math_property": "mathable",
                                }
                            ],
                        },
                    },
                ],
                # target metric insignificant since we're testing secondaries right now
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "whatever"}],
                },
            },
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]

        # trend missing 'test' variant, so it's not in the results
        self.assertEqual(len(response_data["result"].items()), 3)

        self.assertEqual(response_data["result"]["control"], 3)
        self.assertEqual(response_data["result"]["test_1"], 2)
        self.assertEqual(response_data["result"]["test_2"], 1)

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        self.assertEqual(200, response.status_code)

        response_data = response.json()["result"]

        self.assertEqual(len(response_data["result"].items()), 4)

        self.assertAlmostEqual(response_data["result"]["control"], 0, 3)
        self.assertAlmostEqual(response_data["result"]["test"], 33.3333, 3)
        self.assertAlmostEqual(response_data["result"]["test_1"], 2, 3)
        self.assertAlmostEqual(response_data["result"]["test_2"], 0.25, 3)

    def test_metrics_without_full_flag_information_are_valid(self):
        journeys_for(
            {
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview_funnel", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # has invalid feature set
                "person_out_of_all_controls": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "XYZABC"},
                    }
                ],
                # for a funnel conversion metric
                "person1_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-02",
                        # "properties": {"$feature/a-b-test": "test"},
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
                        # "properties": {"$feature/a-b-test": "control"},
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
                        # "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control_funnel": [
                    {"event": "$pageview_funnel", "timestamp": "2020-01-03"},
                    {"event": "$pageleave_funnel", "timestamp": "2020-01-05"},
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
                    }
                ],
                "person5_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
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
                "parameters": {},
                "secondary_metrics": [
                    {
                        "name": "funnels whatever",
                        "filters": {
                            "insight": "funnels",
                            "events": [
                                {"order": 0, "id": "$pageview_funnel"},
                                {"order": 1, "id": "$pageleave_funnel"},
                            ],
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
                    },
                ],
                # target metric insignificant since we're testing secondaries right now
                "filters": {
                    "insight": "trends",
                    "events": [{"order": 0, "id": "whatever"}],
                },
            },
        )

        id = creation_response.json()["id"]
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result_data = response_data["result"]

        self.assertEqual(len(result_data["result"].items()), 2)
        self.assertAlmostEqual(result_data["result"]["control"], 1)
        self.assertEqual(result_data["result"]["test"], round(1 / 3, 3))

        assert set(response_data["result"].keys()) == {
            "result",
            "insight",
            "filters",
            "probability",
            "significant",
            "significance_code",
            "expected_loss",
            "credible_intervals",
            "variants",
        }

        assert response_data["result"]["variants"] == [
            {
                "failure_count": 0,
                "key": "control",
                "success_count": 2,
            },
            {
                "failure_count": 2,
                "key": "test",
                "success_count": 1,
            },
        ]

        assert response_data["result"]["significant"] is False
        assert response_data["result"]["significance_code"] == "not_enough_exposure"

    def test_no_metric_validation_errors_for_secondary_metrics(self):
        journeys_for(
            {
                # for trend metric, no test
                "person2": [
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                    {
                        "event": "$pageview",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "control"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control": [{"event": "$pageview_funnel", "timestamp": "2020-01-03"}],
                "person_out_of_end_date": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-08-03",
                        "properties": {"$feature/a-b-test": "control"},
                    }
                ],
                # has invalid feature set
                "person_out_of_all_controls": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-03",
                        "properties": {"$feature/a-b-test": "XYZABC"},
                    }
                ],
                # for a funnel conversion metric - no control variant
                "person1_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-02",
                        # "properties": {"$feature/a-b-test": "test"},
                    },
                    {
                        "event": "$pageleave_funnel",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    },
                ],
                # doesn't have feature set
                "person_out_of_control_funnel": [
                    {"event": "$pageview_funnel", "timestamp": "2020-01-03"},
                    {"event": "$pageleave_funnel", "timestamp": "2020-01-05"},
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
                    }
                ],
                "person5_funnel": [
                    {
                        "event": "$pageview_funnel",
                        "timestamp": "2020-01-04",
                        "properties": {"$feature/a-b-test": "test"},
                    }
                ],
            },
            self.team,
        )

        creation_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            DEFAULT_EXPERIMENT_CREATION_PAYLOAD,
        )

        id = creation_response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=0")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result_data = response_data["result"]

        assert set(response_data["result"].keys()) == {
            "result",
            "insight",
            "filters",
        }

        self.assertEqual(result_data["result"]["control"], 2)
        assert "test" not in result_data["result"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{id}/secondary_results?id=1")
        self.assertEqual(200, response.status_code)

        response_data = response.json()
        result_data = response_data["result"]

        self.assertEqual(len(response_data["result"].items()), 3)

        assert set(response_data["result"].keys()) == {
            "result",
            "insight",
            "filters",
        }

        assert "control" not in result_data["result"]

        self.assertEqual(result_data["result"]["test"], round(1 / 3, 3))
