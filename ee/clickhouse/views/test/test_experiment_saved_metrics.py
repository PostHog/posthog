from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.actions.backend.models.action import Action
from products.experiments.backend.experiment_saved_metric_service import ExperimentSavedMetricService
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric

from ee.api.test.base import APILicensedTest


class TestExperimentSavedMetricsCRUD(APILicensedTest):
    def test_http_saved_metric_validation_runs_once(self) -> None:
        original_validate_query = ExperimentSavedMetricService.validate_query
        validate_query_call_count = 0

        def counting_validate_query(cls, query: dict | None) -> None:
            nonlocal validate_query_call_count
            validate_query_call_count += 1
            original_validate_query(query)

        with patch.object(ExperimentSavedMetricService, "validate_query", classmethod(counting_validate_query)):
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/",
                data={
                    "name": "Test Experiment saved metric",
                    "query": {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageview"},
                    },
                },
                format="json",
            )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(validate_query_call_count, 1)

        saved_metric_id = create_response.json()["id"]
        validate_query_call_count = 0

        with patch.object(ExperimentSavedMetricService, "validate_query", classmethod(counting_validate_query)):
            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}",
                data={
                    "query": {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {"kind": "EventsNode", "event": "$pageleave"},
                    }
                },
                format="json",
            )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(validate_query_call_count, 1)

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
            "Metric query kind must be 'ExperimentMetric'",
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
            "Metric query kind must be 'ExperimentMetric'",
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
            "Metric query kind must be 'ExperimentMetric'",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {"kind": "ExperimentMetric"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("ExperimentMetric requires a metric_type", response.json()["detail"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
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
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                "tags": ["tag1"],
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric")
        self.assertEqual(response.json()["description"], "Test description")
        saved_metric_uuid = response.json()["query"]["uuid"]
        self.assertTrue(saved_metric_uuid)
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
                "uuid": saved_metric_uuid,
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
        self.assertEqual(Experiment.objects.get(pk=exp_id).secondary_metrics_ordered_uuids, [saved_metric_uuid])
        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        assert experiment_to_saved_metric is not None
        self.assertEqual(experiment_to_saved_metric.metadata, {"type": "secondary"})
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        assert saved_metric is not None
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageview"},
                "uuid": saved_metric_uuid,
            },
        )

        # Now try updating saved metric
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}",
            {
                "name": "Test Experiment saved metric 2",
                "description": "Test description 2",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageleave"},
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test Experiment saved metric 2")
        self.assertEqual(
            response.json()["query"],
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageleave"},
                "uuid": saved_metric_uuid,
            },
        )

        # make sure experiment in question was updated as well
        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        saved_metric = Experiment.objects.get(pk=exp_id).saved_metrics.first()
        assert saved_metric is not None
        self.assertEqual(saved_metric.id, saved_metric_id)
        self.assertEqual(
            saved_metric.query,
            {
                "kind": "ExperimentMetric",
                "metric_type": "mean",
                "source": {"kind": "EventsNode", "event": "$pageleave"},
                "uuid": saved_metric_uuid,
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

    def test_create_saved_metric_without_uuid_added_to_experiment_is_ordered(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        saved_metric_uuid = response.json()["query"]["uuid"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(saved_metric_uuid)

        experiment_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "feature_flag_key": "saved-metric-uuid-ordering",
                "parameters": None,
                "saved_metrics_ids": [{"id": saved_metric_id, "metadata": {"type": "primary"}}],
            },
            format="json",
        )

        self.assertEqual(experiment_response.status_code, status.HTTP_201_CREATED)
        self.assertIn(saved_metric_uuid, experiment_response.json()["primary_metrics_ordered_uuids"])

    def test_update_saved_metric_tags(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
                "tags": ["tag1"],
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["tags"], ["tag1"])

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}",
            {
                "tags": ["tag2", "tag3"],
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(update_response.json()["tags"], ["tag2", "tag3"])

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

    def test_create_experiment_with_saved_metric_breakdowns(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric with breakdown",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ff_key = "a-b-test-breakdown"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment with Breakdown",
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
                "saved_metrics_ids": [
                    {
                        "id": saved_metric_id,
                        "metadata": {
                            "type": "primary",
                            "breakdowns": [
                                {"property": "$browser", "type": "event"},
                                {"property": "$os", "type": "event"},
                            ],
                        },
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        exp_id = response.json()["id"]

        self.assertEqual(Experiment.objects.get(pk=exp_id).saved_metrics.count(), 1)
        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        assert experiment_to_saved_metric is not None
        self.assertEqual(
            experiment_to_saved_metric.metadata,
            {
                "type": "primary",
                "breakdowns": [
                    {"property": "$browser", "type": "event"},
                    {"property": "$os", "type": "event"},
                ],
            },
        )

    def test_update_experiment_saved_metric_breakdowns(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Experiment saved metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ff_key = "a-b-test-update-breakdown"
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
                    ],
                    "properties": [],
                },
                "saved_metrics_ids": [
                    {
                        "id": saved_metric_id,
                        "metadata": {"type": "primary", "breakdowns": [{"property": "$browser", "type": "event"}]},
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        exp_id = response.json()["id"]

        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        assert experiment_to_saved_metric is not None
        self.assertEqual(
            experiment_to_saved_metric.metadata,
            {"type": "primary", "breakdowns": [{"property": "$browser", "type": "event"}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{exp_id}",
            {
                "saved_metrics_ids": [
                    {
                        "id": saved_metric_id,
                        "metadata": {
                            "type": "primary",
                            "breakdowns": [
                                {"property": "$browser", "type": "event"},
                                {"property": "$device_type", "type": "event"},
                            ],
                        },
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        experiment_to_saved_metric = Experiment.objects.get(pk=exp_id).experimenttosavedmetric_set.first()
        assert experiment_to_saved_metric is not None
        self.assertEqual(
            experiment_to_saved_metric.metadata,
            {
                "type": "primary",
                "breakdowns": [
                    {"property": "$browser", "type": "event"},
                    {"property": "$device_type", "type": "event"},
                ],
            },
        )

    def test_multiple_experiments_with_different_breakdowns_for_same_metric(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Shared Metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        exp1_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Experiment 1",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": "exp-1-key",
                "parameters": None,
                "filters": {"events": [{"order": 0, "id": "$pageview"}], "properties": []},
                "saved_metrics_ids": [
                    {
                        "id": saved_metric_id,
                        "metadata": {"type": "primary", "breakdowns": [{"property": "$browser", "type": "event"}]},
                    }
                ],
            },
        )
        self.assertEqual(exp1_response.status_code, status.HTTP_201_CREATED)
        exp1_id = exp1_response.json()["id"]

        exp2_response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Experiment 2",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": "exp-2-key",
                "parameters": None,
                "filters": {"events": [{"order": 0, "id": "$pageview"}], "properties": []},
                "saved_metrics_ids": [
                    {
                        "id": saved_metric_id,
                        "metadata": {
                            "type": "primary",
                            "breakdowns": [
                                {"property": "$os", "type": "event"},
                                {"property": "$device_type", "type": "event"},
                            ],
                        },
                    }
                ],
            },
        )
        self.assertEqual(exp2_response.status_code, status.HTTP_201_CREATED)
        exp2_id = exp2_response.json()["id"]

        exp1_to_saved_metric = Experiment.objects.get(pk=exp1_id).experimenttosavedmetric_set.first()
        exp2_to_saved_metric = Experiment.objects.get(pk=exp2_id).experimenttosavedmetric_set.first()

        assert exp1_to_saved_metric is not None
        assert exp2_to_saved_metric is not None

        self.assertEqual(
            exp1_to_saved_metric.metadata,
            {"type": "primary", "breakdowns": [{"property": "$browser", "type": "event"}]},
        )
        self.assertEqual(
            exp2_to_saved_metric.metadata,
            {
                "type": "primary",
                "breakdowns": [
                    {"property": "$os", "type": "event"},
                    {"property": "$device_type", "type": "event"},
                ],
            },
        )

    def test_api_response_includes_breakdowns_in_metadata(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Test Metric",
                "description": "Test description",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )

        saved_metric_id = response.json()["id"]
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ff_key = "test-api-response"
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment API Response",
                "description": "",
                "start_date": "2021-12-01T10:23",
                "end_date": None,
                "feature_flag_key": ff_key,
                "parameters": None,
                "filters": {"events": [{"order": 0, "id": "$pageview"}], "properties": []},
                "saved_metrics_ids": [
                    {
                        "id": saved_metric_id,
                        "metadata": {
                            "type": "primary",
                            "breakdowns": [{"property": "$browser", "type": "event"}],
                        },
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        exp_id = response.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{exp_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        saved_metrics = response.json()["saved_metrics"]
        self.assertEqual(len(saved_metrics), 1)
        self.assertEqual(saved_metrics[0]["name"], "Test Metric")
        self.assertEqual(
            saved_metrics[0]["metadata"],
            {
                "type": "primary",
                "breakdowns": [{"property": "$browser", "type": "event"}],
            },
        )
        self.assertIn("query", saved_metrics[0])
        self.assertEqual(saved_metrics[0]["query"]["kind"], "ExperimentMetric")

    def test_cannot_create_duplicate_named_saved_metric(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Unique Metric Name",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Unique Metric Name",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageleave"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("A shared metric with this name already exists", str(response.json()))

    def test_can_update_saved_metric_keeping_same_name(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": "Keep This Name",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}",
            data={
                "name": "Keep This Name",
                "description": "Updated description",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_saved_metric_refreshes_action_names(self):
        """Test that saved metrics show current action names when actions are renamed."""
        from products.actions.backend.models.action import Action

        # Create an action
        action = Action.objects.create(team=self.team, name="Original Action Name")

        # Create a saved metric using the action
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Metric with Action",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {
                        "kind": "ActionsNode",
                        "id": action.id,
                        "name": "Original Action Name",  # Stale name
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = response.json()["id"]

        # Rename the action
        action.name = "Renamed Action"
        action.save()

        # Fetch the saved metric
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the action name was refreshed
        self.assertEqual(response.json()["query"]["source"]["name"], "Renamed Action")
        self.assertEqual(response.json()["query"]["source"]["id"], action.id)

    def test_saved_metric_preserves_name_for_deleted_action(self):
        """Test that saved metrics preserve old names when actions are deleted."""
        from products.actions.backend.models.action import Action

        # Create an action
        action = Action.objects.create(team=self.team, name="Action to Delete")
        action_id = action.id

        # Create a saved metric using the action
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            {
                "name": "Test Metric with Deleted Action",
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {
                        "kind": "ActionsNode",
                        "id": action_id,
                        "name": "Action to Delete",
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        saved_metric_id = response.json()["id"]

        # Delete the action
        action.deleted = True
        action.save()

        # Fetch the saved metric
        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/{saved_metric_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the old name is preserved
        self.assertEqual(response.json()["query"]["source"]["name"], "Action to Delete")
        self.assertEqual(response.json()["query"]["source"]["id"], action_id)

    def _create_saved_metric(self, name: str, description: str = "", tags: list[str] | None = None) -> int:
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/",
            data={
                "name": name,
                "description": description,
                "tags": tags or [],
                "query": {
                    "kind": "ExperimentMetric",
                    "metric_type": "mean",
                    "source": {"kind": "EventsNode", "event": "$pageview"},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return response.json()["id"]

    @parameterized.expand(
        [
            ("by_name", "alpha", {"Alpha conversion"}),
            ("by_description", "revenue tracker", {"Beta signups"}),
            ("by_tag", "growth", {"Beta signups"}),
            ("no_match", "zzz-nothing", set()),
        ]
    )
    def test_search_filters_saved_metrics(self, _name: str, search: str, expected_names: set[str]) -> None:
        self._create_saved_metric("Alpha conversion", description="checkout funnel")
        self._create_saved_metric("Beta signups", description="revenue tracker thing", tags=["growth"])

        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?search={search}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned = {row["name"] for row in response.json()["results"]}
        self.assertEqual(returned, expected_names)

    def test_search_returns_each_metric_once_with_multiple_matching_tags(self) -> None:
        self._create_saved_metric("Tagged metric", description="", tags=["growth", "growth-team"])

        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?search=growth")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(len(body["results"]), 1)

    def test_list_paginates_with_limit_and_offset(self) -> None:
        for i in range(5):
            self._create_saved_metric(f"Metric {i:02d}")

        page1 = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=2&offset=0").json()
        page2 = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/?limit=2&offset=2").json()

        self.assertEqual(page1["count"], 5)
        self.assertEqual(len(page1["results"]), 2)
        self.assertEqual(len(page2["results"]), 2)
        ids_page1 = {row["id"] for row in page1["results"]}
        ids_page2 = {row["id"] for row in page2["results"]}
        self.assertEqual(ids_page1 & ids_page2, set())

    def _seed_metrics_for_event_filter(self) -> None:
        # Created via the ORM so the stored query JSON is exactly what the filter inspects. The action fires
        # on the "signup" event, so its metric is discoverable by that event — not by the action's label.
        signup_action = Action.objects.create(team=self.team, name="Completed signup", steps_json=[{"event": "signup"}])
        for name, source in [
            ("Pageview mean", {"kind": "EventsNode", "event": "$pageview"}),
            ("Purchase mean", {"kind": "EventsNode", "event": "purchase"}),
            ("Signup via action", {"kind": "ActionsNode", "id": signup_action.id, "name": "Completed signup"}),
        ]:
            ExperimentSavedMetric.objects.create(
                team=self.team,
                created_by=self.user,
                name=name,
                query={"kind": "ExperimentMetric", "metric_type": "mean", "source": source},
            )

    @parameterized.expand(
        [
            # `event` matches the events a metric references — directly, or via an action's step events.
            ("direct_event", "$pageview", {"Pageview mean"}),
            ("another_direct_event", "purchase", {"Purchase mean"}),
            ("event_behind_an_action", "signup", {"Signup via action"}),
            # It matches events, not the action's label, nor query structure/type tokens.
            ("action_label_not_matched", "Completed signup", set()),
            ("metric_type_token_not_matched", "mean", set()),
            ("node_kind_token_not_matched", "EventsNode", set()),
            ("no_match", "not_an_event", set()),
        ]
    )
    def test_event_filter_matches_referenced_events_only(
        self, _name: str, event: str, expected_names: set[str]
    ) -> None:
        self._seed_metrics_for_event_filter()

        response = self.client.get(f"/api/projects/{self.team.id}/experiment_saved_metrics/", data={"event": event})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned = {row["name"] for row in response.json()["results"]}
        self.assertEqual(returned, expected_names)

    def test_event_filter_composes_with_search(self) -> None:
        # `event` (references) and `search` (name/description/tags) apply through different mechanisms;
        # both must narrow the result set together (AND), not clobber each other.
        purchase_query = {
            "kind": "ExperimentMetric",
            "metric_type": "mean",
            "source": {"kind": "EventsNode", "event": "purchase"},
        }
        for name in ["Alpha purchase", "Beta purchase"]:
            ExperimentSavedMetric.objects.create(team=self.team, created_by=self.user, name=name, query=purchase_query)

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/?event=purchase&search=Alpha"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned = {row["name"] for row in response.json()["results"]}
        self.assertEqual(returned, {"Alpha purchase"})

    def test_event_param_does_not_filter_detail_retrieve(self) -> None:
        # `event` is a list-only filter; it must never narrow a detail lookup into a 404.
        metric_id = self._create_saved_metric("Pageview mean")

        response = self.client.get(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{metric_id}?event=not_an_event"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], metric_id)
