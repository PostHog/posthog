from rest_framework import status

from posthog.models.experiment import Experiment, ExperimentToSavedMetric

from ee.api.test.base import APILicensedTest


class TestExperimentSavedMetricsCRUD(APILicensedTest):
    def test_can_list_experiment_saved_metrics(self):
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_validation_of_query_metric(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Query is required to create a saved metric")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"not-kind": "ExperimentTrendsQuery"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "not-ExperimentTrendsQuery"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "TrendsQuery"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["detail"],
            "Metric query kind must be 'ExperimentMetric', 'ExperimentTrendsQuery' or 'ExperimentFunnelsQuery'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "ExperimentTrendsQuery"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("'loc': ('count_query',), 'msg': 'Field required'" in response.json()["detail"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_update_experiment_saved_metrics(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview"}],
                    },
                },
                "tags": ["tag1"],
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric")
        self.assertEqual(response.json()["description"], "Test description")
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)
        self.assertEqual(response.json()["tags"], ["tag1"])
        # Generate experiment to have saved metric
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
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "secondary"}}],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        exp_id = response.json()["id"]

        self.assertEqual(response.json()["name"], "Test Experiment")
        self.assertEqual(response.json()["feature_flag_key"], ff_key)

        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        self.assertEqual(experiment_to_saved_metric.metadata, {"type": "secondary"})
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            },
        )

        # Now try updating saved metric
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}",
            {
                "name": "Test Experiment saved metric 2",
                "description": "Test description 2",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric 2")
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
            },
        )

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentTrendsQuery",
                "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageleave"}]},
            },
        )
        self.assertEqual(saved_metric.name, "Test Experiment saved metric 2")
        self.assertEqual(saved_metric.description, "Test description 2")

        # now delete saved metric
        response = self.client.delete(f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 0)
        self.assertEqual(ExperimentToSavedMetric.objects.filter(experiment_id=exp_id).count(), 0)

    def test_create_saved_metric_with_experiment_metric(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric")
        self.assertEqual(response.json()["description"], "Test description")
        self.assertEqual(response.json()["query"]["kind"], "ExperimentMetric")
        self.assertEqual(response.json()["query"]["metric_type"], "mean")

    def test_create_saved_metric_with_experiment_metric_invalid_metric_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "invalid",
                    "source": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "ExperimentMetric metric_type must be 'mean', 'funnel', 'ratio', or 'retention'", response.json()["detail"]
        )

    def test_create_saved_metric_with_experiment_metric_ratio(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment ratio metric",
                "description": "Test description for ratio",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {
                        "kind": "EventsNode",
                        "event": "$purchase",
                    },
                    "denominator": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment ratio metric")
        self.assertEqual(response.json()["description"], "Test description for ratio")
        self.assertEqual(response.json()["query"]["kind"], "ExperimentMetric")
        self.assertEqual(response.json()["query"]["metric_type"], "ratio")
        self.assertEqual(response.json()["query"]["numerator"]["event"], "$purchase")
        self.assertEqual(response.json()["query"]["denominator"]["event"], "$pageview")

    def test_create_saved_metric_with_experiment_metric_ratio_missing_fields(self):
        # Test missing numerator
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment ratio metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "denominator": {
                        "kind": "EventsNode",
                        "event": "$pageview",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("'loc': ('numerator',), 'msg': 'Field required'" in response.json()["detail"])

        # Test missing denominator
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment ratio metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "ratio",
                    "numerator": {
                        "kind": "EventsNode",
                        "event": "$purchase",
                    },
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue("'loc': ('denominator',), 'msg': 'Field required'" in response.json()["detail"])

    def test_invalid_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": None,  # invalid
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This field may not be null.")

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "xyz",
                "query": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Query is required to create a saved metric")

    def test_pagination(self):
        # Create multiple saved metrics
        for i in range(35):
            self.client.post(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/",
                data={
                    "name": f"Test Metric {i}",
                    "description": f"Description {i}",
                    "query": {
                        "kind": "ExperimentTrendsQuery",
                        "count_query": {
                            "kind": "TrendsQuery",
                            "series": [{"kind": "EventsNode", "event": "$pageview"}],
                        },
                    },
                },
                format="json",
            )

        # Test first page with limit
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=10&offset=0")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 10)
        self.assertEqual(data["count"], 35)
        self.assertIsNotNone(data.get("next"))
        self.assertIsNone(data.get("previous"))

        # Test second page
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=10&offset=10")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 10)
        self.assertEqual(data["count"], 35)
        self.assertIsNotNone(data.get("next"))
        self.assertIsNotNone(data.get("previous"))

        # Test last page
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=10&offset=30")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 5)  # Only 5 remaining
        self.assertEqual(data["count"], 35)
        self.assertIsNone(data.get("next"))
        self.assertIsNotNone(data.get("previous"))

        # Verify no overlap between pages
        page1_ids = {
            item["id"]
            for item in self.client.get(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=10&offset=0"
            ).json()["results"]
        }
        page2_ids = {
            item["id"]
            for item in self.client.get(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=10&offset=10"
            ).json()["results"]
        }
        self.assertEqual(len(page1_ids & page2_ids), 0)

    def test_search(self):
        # Create saved metrics with different names and descriptions
        self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Revenue Metric",
                "description": "Tracks total revenue",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Conversion Rate",
                "description": "Measures conversion rate",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "User Engagement",
                "description": "Revenue per user",
                "query": {
                    "kind": "ExperimentTrendsQuery",
                    "count_query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
                },
            },
            format="json",
        )

        # Search by name
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?search=Revenue")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 2)  # "Revenue Metric" and "User Engagement" (description contains "Revenue")
        self.assertTrue(
            all(
                "revenue" in item["name"].lower() or "revenue" in (item.get("description") or "").lower()
                for item in data["results"]
            )
        )

        # Search by description
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?search=conversion")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["name"], "Conversion Rate")

        # Search with no matches
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?search=Nonexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(len(data["results"]), 0)

    def test_search_with_pagination(self):
        # Create multiple saved metrics with searchable names
        for i in range(15):
            self.client.post(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/",
                data={
                    "name": f"Revenue Metric {i}",
                    "description": f"Revenue tracking {i}",
                    "query": {
                        "kind": "ExperimentTrendsQuery",
                        "count_query": {
                            "kind": "TrendsQuery",
                            "series": [{"kind": "EventsNode", "event": "$pageview"}],
                        },
                    },
                },
                format="json",
            )

        # Search with pagination - following the pattern from test_survey.py
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?search=Revenue&limit=10")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["results"]), 10)  # Should return only 10 results
        self.assertTrue(data["next"] is not None)  # Should have next page
        self.assertTrue(data["count"] > 10)  # Total count should be more than 10
