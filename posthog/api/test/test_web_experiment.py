from datetime import datetime, timedelta
from unittest.mock import ANY, patch

from rest_framework import status

from posthog.models import WebExperiment
from posthog.test.base import APIBaseTest


class TestWebExperiment(APIBaseTest):
    def _create_web_experiment(self, name="Zero to Web Experiment"):
        return self.client.post(
            f"/api/projects/{self.team.id}/web_experiments/",
            data={
                "name": name,
                "variants": {
                    "control": {
                        "transforms": [
                            {"html": "", "text": "There goes Superman!", "selector": "#page > #body > .header h1"}
                        ],
                        "rollout_percentage": 70,
                    },
                    "test": {
                        "transforms": [
                            {"html": "", "text": "Up, UP and Away!", "selector": "#page > #body > .header h1"}
                        ],
                        "rollout_percentage": 30,
                    },
                },
            },
            format="json",
        )

    @patch("posthog.api.feature_flag.report_user_action")
    def test_can_create_basic_web_experiment(self, mock_capture):
        response = self._create_web_experiment()
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        id = response_data["id"]
        web_experiment = WebExperiment.objects.get(id=id)
        assert web_experiment is not None
        linked_flag = web_experiment.feature_flag
        assert linked_flag is not None
        assert linked_flag.filters is not None
        multivariate = linked_flag.filters.get("multivariate", None)
        assert multivariate is not None
        variants = multivariate.get("variants", None)
        assert variants is not None
        assert variants[0].get("key") == "control"
        assert variants[0].get("rollout_percentage") == 70
        assert variants[1].get("key") == "test"
        assert variants[1].get("rollout_percentage") == 30

        assert web_experiment.created_by == self.user

        assert web_experiment.variants is not None
        assert web_experiment.type == "web"
        assert web_experiment.variants.get("control") is not None
        assert web_experiment.variants.get("test") is not None
        mock_capture.assert_called_once_with(
            ANY,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": True,
                "variants_count": 2,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": linked_flag.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
                "creation_context": "web_experiments",
            },
        )

    def test_can_list_active_web_experiments(self):
        response = self._create_web_experiment("active_web_experiment")
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        response = self._create_web_experiment("completed_web_experiment")
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        completed_web_exp_id = response_data["id"]
        completed_web_exp = WebExperiment.objects.get(id=completed_web_exp_id)
        completed_web_exp.start_date = datetime.now().utcnow() - timedelta(days=2)
        completed_web_exp.end_date = datetime.now().utcnow()
        completed_web_exp.save()
        list_response = self.client.get(f"/api/web_experiments?token={self.team.api_token}")
        assert list_response.status_code == status.HTTP_200_OK, list_response
        response_data = list_response.json()
        assert len(response_data["experiments"]) == 1
        assert response_data["experiments"][0]["name"] == "active_web_experiment"

    def test_can_delete_web_experiment(self):
        response = self._create_web_experiment()
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        experiment_id = response_data["id"]
        assert WebExperiment.objects.filter(id=experiment_id).exists()
        del_response = self.client.delete(f"/api/projects/{self.team.id}/web_experiments/{experiment_id}")
        assert del_response.status_code == status.HTTP_204_NO_CONTENT
        assert WebExperiment.objects.filter(id=experiment_id).exists() is False

    def test_web_experiments_endpoint_handles_missing_feature_flag_data(self):
        """Test that the endpoint gracefully handles cases where feature flag data is missing or invalid"""
        # Create experiment
        response = self._create_web_experiment("edge_case_experiment")
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        experiment_id = response_data["id"]

        # Get the experiment and corrupt its feature flag data
        web_experiment = WebExperiment.objects.get(id=experiment_id)
        feature_flag = web_experiment.feature_flag

        # Test case 1: Empty multivariate data
        feature_flag.filters = {"multivariate": {}}
        feature_flag.save()

        list_response = self.client.get(f"/api/web_experiments?token={self.team.api_token}")
        assert list_response.status_code == status.HTTP_200_OK
        response_data = list_response.json()

        experiment_data = response_data["experiments"][0]
        variants = experiment_data["variants"]
        # Should fall back to original experiment variants
        assert variants["control"]["rollout_percentage"] == 70  # Original value
        assert variants["test"]["rollout_percentage"] == 30  # Original value

        # Test case 2: Missing multivariate entirely
        feature_flag.filters = {}
        feature_flag.save()

        list_response = self.client.get(f"/api/web_experiments?token={self.team.api_token}")
        assert list_response.status_code == status.HTTP_200_OK
        response_data = list_response.json()

        experiment_data = response_data["experiments"][0]
        variants = experiment_data["variants"]
        # Should still fall back to original experiment variants
        assert variants["control"]["rollout_percentage"] == 70  # Original value
        assert variants["test"]["rollout_percentage"] == 30  # Original value

    def test_list_excludes_deleted_web_experiments(self):
        # Create two web experiments
        response1 = self._create_web_experiment("Active Experiment")
        response_data1 = response1.json()
        assert response1.status_code == status.HTTP_201_CREATED
        active_id = response_data1["id"]

        response2 = self._create_web_experiment("Deleted Experiment")
        response_data2 = response2.json()
        assert response2.status_code == status.HTTP_201_CREATED
        deleted_id = response_data2["id"]

        # Soft delete one experiment
        deleted_experiment = WebExperiment.objects.get(id=deleted_id)
        deleted_experiment.deleted = True
        deleted_experiment.save()

        # List experiments via API - should only show active experiment
        list_response = self.client.get(f"/api/projects/{self.team.id}/web_experiments/")
        assert list_response.status_code == status.HTTP_200_OK
        response_data = list_response.json()

        # Should only contain the active experiment
        assert len(response_data["results"]) == 1
        assert response_data["results"][0]["id"] == active_id
        assert response_data["results"][0]["name"] == "Active Experiment"

    def test_detail_can_access_deleted_web_experiment(self):
        # Create a web experiment
        response = self._create_web_experiment("Test Experiment")
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED
        experiment_id = response_data["id"]

        # Soft delete the experiment
        experiment = WebExperiment.objects.get(id=experiment_id)
        experiment.deleted = True
        experiment.save()

        # Try to retrieve the deleted experiment via detail endpoint
        detail_response = self.client.get(f"/api/projects/{self.team.id}/web_experiments/{experiment_id}/")

        # Should return 200 since safely_get_queryset only filters for list actions
        assert detail_response.status_code == status.HTTP_200_OK
        response_data = detail_response.json()
        assert response_data["id"] == experiment_id
        assert response_data["name"] == "Test Experiment"

    def test_web_experiments_endpoint_returns_correct_exposure_values(self):
        """Test that the web_experiments endpoint returns the actual rollout percentages from the feature flag"""
        # Create experiment
        response = self._create_web_experiment("exposure_test_experiment")
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        experiment_id = response_data["id"]

        # Get the experiment and its feature flag
        web_experiment = WebExperiment.objects.get(id=experiment_id)
        feature_flag = web_experiment.feature_flag

        # Update the feature flag with different rollout percentages
        updated_filters = feature_flag.filters.copy()
        updated_filters["multivariate"]["variants"] = [
            {"key": "control", "rollout_percentage": 40},
            {"key": "test", "rollout_percentage": 60},
        ]
        feature_flag.filters = updated_filters
        feature_flag.save()

        # Call the web_experiments endpoint
        list_response = self.client.get(f"/api/web_experiments?token={self.team.api_token}")
        assert list_response.status_code == status.HTTP_200_OK, list_response
        response_data = list_response.json()

        # Verify the response
        assert len(response_data["experiments"]) == 1
        experiment_data = response_data["experiments"][0]
        assert experiment_data["name"] == "exposure_test_experiment"

        # Verify the variants contain the updated rollout percentages from feature flag
        variants = experiment_data["variants"]
        assert variants is not None
        assert "control" in variants
        assert "test" in variants
        assert variants["control"]["rollout_percentage"] == 40  # Updated value, not original 70
        assert variants["test"]["rollout_percentage"] == 60  # Updated value, not original 30

        # Verify transforms are still present from original experiment
        assert "transforms" in variants["control"]
        assert "transforms" in variants["test"]
        assert len(variants["control"]["transforms"]) == 1
        assert len(variants["test"]["transforms"]) == 1

    def test_web_experiments_endpoint_includes_new_feature_flag_variants(self):
        """Test that new variants added directly to the feature flag are included in the response"""
        # Create experiment with original variants
        response = self._create_web_experiment("new_variant_test")
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        experiment_id = response_data["id"]

        # Get the experiment and its feature flag
        web_experiment = WebExperiment.objects.get(id=experiment_id)
        feature_flag = web_experiment.feature_flag

        # Add a new variant directly to the feature flag (not in experiment variants)
        updated_filters = feature_flag.filters.copy()
        updated_filters["multivariate"]["variants"] = [
            {"key": "control", "rollout_percentage": 30},
            {"key": "test", "rollout_percentage": 30},
            {"key": "new_variant", "rollout_percentage": 40},  # New variant added to feature flag
        ]
        feature_flag.filters = updated_filters
        feature_flag.save()

        # Call the web_experiments endpoint
        list_response = self.client.get(f"/api/web_experiments?token={self.team.api_token}")
        assert list_response.status_code == status.HTTP_200_OK, list_response
        response_data = list_response.json()

        # Verify the response includes ALL feature flag variants
        experiment_data = response_data["experiments"][0]
        variants = experiment_data["variants"]
        assert variants is not None

        # Should include all three variants now
        assert "control" in variants
        assert "test" in variants
        assert "new_variant" in variants  # New variant should be included

        # Verify rollout percentages from feature flag
        assert variants["control"]["rollout_percentage"] == 30
        assert variants["test"]["rollout_percentage"] == 30
        assert variants["new_variant"]["rollout_percentage"] == 40

        # Original variants should still have their transforms
        assert "transforms" in variants["control"]
        assert "transforms" in variants["test"]

        # New variant should not have transforms (not in original experiment)
        assert "transforms" not in variants["new_variant"]
