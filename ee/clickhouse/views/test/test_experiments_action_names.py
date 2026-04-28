from parameterized import parameterized
from rest_framework import status

from posthog.models.action.action import Action

from ee.api.test.base import APILicensedTest


class TestExperimentActionNameRefresh(APILicensedTest):
    @parameterized.expand(
        [
            ("primary_metrics", "metrics"),
            ("secondary_metrics", "metrics_secondary"),
        ]
    )
    def test_inline_metric_refreshes_action_names(self, _name, metrics_field):
        # Create an action
        action = Action.objects.create(team=self.team, name="Original Action Name")

        # Create an experiment with an inline metric using the action
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": f"Test Experiment {metrics_field}",
                "description": "Test experiment with action metric",
                "type": "web",
                "feature_flag_key": f"test-flag-{metrics_field}",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                metrics_field: [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {
                            "kind": "ActionsNode",
                            "id": action.id,
                            "name": "Original Action Name",  # Stale name stored
                        },
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Rename the action
        action.name = "Renamed Action"
        action.save()

        # Fetch the experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the action name was refreshed in the inline metric
        metrics = response.json()[metrics_field]
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["source"]["name"], "Renamed Action")
        # ID can be int or string depending on how it was stored
        self.assertIn(metrics[0]["source"]["id"], [action.id, str(action.id)])

    @parameterized.expand(
        [
            ("integer_id", int),
            ("string_id", str),
        ]
    )
    def test_inline_metric_with_different_id_types(self, _name, id_type):
        # Create an action
        action = Action.objects.create(team=self.team, name="Action Name")

        # Create an experiment with an inline metric using the action
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": f"Test Experiment {_name}",
                "description": "Test experiment with action ID type",
                "type": "web",
                "feature_flag_key": f"test-flag-{_name}",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {
                            "kind": "ActionsNode",
                            "id": id_type(action.id),  # Use the specified ID type
                            "name": "Action Name",
                        },
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Rename the action
        action.name = "Action Name Renamed"
        action.save()

        # Fetch the experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the action name was refreshed regardless of ID type
        metrics = response.json()["metrics"]
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["source"]["name"], "Action Name Renamed")

    def test_inline_metric_preserves_name_for_deleted_action(self):
        # Create an action
        action = Action.objects.create(team=self.team, name="Action to Delete")
        action_id = action.id

        # Create an experiment with an inline metric using the action
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": "Test Experiment",
                "description": "Test experiment with deleted action",
                "type": "web",
                "feature_flag_key": "test-flag-deleted",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                "metrics": [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "mean",
                        "source": {
                            "kind": "ActionsNode",
                            "id": action_id,
                            "name": "Action to Delete",
                        },
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Delete the action
        action.deleted = True
        action.save()

        # Fetch the experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the old name is preserved
        metrics = response.json()["metrics"]
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["source"]["name"], "Action to Delete")
        # ID can be int or string depending on how it was stored
        self.assertIn(metrics[0]["source"]["id"], [action_id, str(action_id)])

    @parameterized.expand(
        [
            ("primary_metrics", "metrics"),
            ("secondary_metrics", "metrics_secondary"),
        ]
    )
    def test_funnel_metric_refreshes_action_names(self, _name, metrics_field):
        # Create two actions for funnel steps
        action1 = Action.objects.create(team=self.team, name="Funnel Step 1 Original")
        action2 = Action.objects.create(team=self.team, name="Funnel Step 2 Original")

        # Create an experiment with a funnel metric using actions
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": f"Test Funnel Experiment {metrics_field}",
                "description": "Test experiment with funnel action metrics",
                "type": "web",
                "feature_flag_key": f"test-flag-funnel-{metrics_field}",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                metrics_field: [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "funnel",
                        "series": [
                            {
                                "kind": "ActionsNode",
                                "id": action1.id,
                                "name": "Funnel Step 1 Original",
                            },
                            {
                                "kind": "ActionsNode",
                                "id": action2.id,
                                "name": "Funnel Step 2 Original",
                            },
                        ],
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Rename both actions
        action1.name = "Funnel Step 1 Renamed"
        action1.save()
        action2.name = "Funnel Step 2 Renamed"
        action2.save()

        # Fetch the experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify both action names were refreshed
        metrics = response.json()[metrics_field]
        self.assertEqual(len(metrics), 1)
        self.assertEqual(len(metrics[0]["series"]), 2)
        self.assertEqual(metrics[0]["series"][0]["name"], "Funnel Step 1 Renamed")
        self.assertEqual(metrics[0]["series"][1]["name"], "Funnel Step 2 Renamed")

    @parameterized.expand(
        [
            ("primary_metrics", "metrics"),
            ("secondary_metrics", "metrics_secondary"),
        ]
    )
    def test_ratio_metric_refreshes_action_names(self, _name, metrics_field):
        # Create two actions for numerator and denominator
        numerator_action = Action.objects.create(team=self.team, name="Numerator Original")
        denominator_action = Action.objects.create(team=self.team, name="Denominator Original")

        # Create an experiment with a ratio metric using actions
        response = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {
                "name": f"Test Ratio Experiment {metrics_field}",
                "description": "Test experiment with ratio action metrics",
                "type": "web",
                "feature_flag_key": f"test-flag-ratio-{metrics_field}",
                "parameters": {
                    "feature_flag_variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                metrics_field: [
                    {
                        "kind": "ExperimentMetric",
                        "metric_type": "ratio",
                        "numerator": {
                            "kind": "ActionsNode",
                            "id": numerator_action.id,
                            "name": "Numerator Original",
                        },
                        "denominator": {
                            "kind": "ActionsNode",
                            "id": denominator_action.id,
                            "name": "Denominator Original",
                        },
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        experiment_id = response.json()["id"]

        # Rename both actions
        numerator_action.name = "Numerator Renamed"
        numerator_action.save()
        denominator_action.name = "Denominator Renamed"
        denominator_action.save()

        # Fetch the experiment
        response = self.client.get(f"/api/projects/{self.team.id}/experiments/{experiment_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify both action names were refreshed
        metrics = response.json()[metrics_field]
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["numerator"]["name"], "Numerator Renamed")
        self.assertEqual(metrics[0]["denominator"]["name"], "Denominator Renamed")
