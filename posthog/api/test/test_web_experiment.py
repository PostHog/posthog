from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import ANY, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.web_experiment import WebExperimentsAPISerializer, WebExperimentViewSet
from posthog.models.activity_logging.activity_log import ActivityLog

from products.experiments.backend.models.web_experiment import WebExperiment


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

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_can_create_basic_web_experiment(self, mock_report_user_action):
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
        mock_report_user_action.assert_called_once_with(
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
            team=ANY,
            request=ANY,
        )

    @patch("posthog.api.web_experiment.report_user_action")
    def test_web_experiment_creation_reports_experiment_created(self, mock_report_user_action):
        response = self._create_web_experiment()
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data

        web_experiment = WebExperiment.objects.get(id=response_data["id"])

        mock_report_user_action.assert_called_once_with(
            ANY,
            "experiment created",
            {
                "experiment_id": web_experiment.id,
                "experiment_name": web_experiment.name,
                "feature_flag_key": web_experiment.feature_flag.key,
                "type": "web",
                "status": "draft",
                "metrics_count": 0,
                "secondary_metrics_count": 0,
                "saved_metrics_count": 0,
                "has_description": False,
                "has_conclusion_comment": False,
                "variant_count": 2,
                "created_at": web_experiment.created_at,
                "creation_mode": "new",
            },
            team=ANY,
            request=ANY,
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
        completed_web_exp.start_date = datetime.now(UTC) - timedelta(days=2)
        completed_web_exp.end_date = datetime.now(UTC)
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

    def test_web_experiment_activity_log_on_create_and_update(self):
        response = self._create_web_experiment()
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        experiment_id = response_data["id"]

        creation_logs = ActivityLog.objects.filter(scope="Experiment", item_id=str(experiment_id), activity="created")
        assert len(creation_logs) == 1

        # Update the experiment variants
        self.client.patch(
            f"/api/projects/{self.team.id}/web_experiments/{experiment_id}/",
            data={
                "variants": {
                    "control": {
                        "transforms": [
                            {"html": "", "text": "Updated control", "selector": "#page > #body > .header h1"}
                        ],
                        "rollout_percentage": 70,
                    },
                    "test": {
                        "transforms": [{"html": "", "text": "Updated test", "selector": "#page > #body > .header h1"}],
                        "rollout_percentage": 30,
                    },
                },
            },
            format="json",
        )

        update_logs = list(
            ActivityLog.objects.filter(scope="Experiment", item_id=str(experiment_id), activity="updated").order_by(
                "-created_at"
            )
        )
        assert len(update_logs) >= 1

        # Find the log entry that has variant changes (the web experiment update, not the feature flag sync)
        experiment_update_log = next(
            (
                log
                for log in update_logs
                if log.detail is not None and any(c["field"] == "variants" for c in log.detail["changes"])
            ),
            update_logs[0],
        )

        # The parameters field should be excluded from changes for web experiments
        assert experiment_update_log.detail is not None
        changes = experiment_update_log.detail["changes"]
        parameter_changes = [c for c in changes if c["field"] == "parameters"]
        assert parameter_changes == []

        # But variants changes should be present
        variant_changes = [c for c in changes if c["field"] == "variants"]
        assert len(variant_changes) == 1

    def test_accepts_safe_html_with_formatting(self):
        """Test that safe HTML with complex formatting is accepted and preserved"""
        complex_html = """<div class="flex h-4 items-center justify-center lg:h-12">
  <div class="hidden lg:block" data-testid="nav-container">
    <div class="flex h-full w-full">
      <a href="https://example.com" class="nav-link">Link</a>
      <span>Text content</span>
    </div>
  </div>
</div>"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/web_experiments/",
            data={
                "name": "Safe HTML Test",
                "variants": {
                    "control": {
                        "transforms": [{"html": "", "text": "Safe", "selector": "#test"}],
                        "rollout_percentage": 50,
                    },
                    "test": {
                        "transforms": [
                            {
                                "html": complex_html,
                                "text": "Safe <b>formatted</b> text",
                                "selector": "#test",
                            }
                        ],
                        "rollout_percentage": 50,
                    },
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()

        # Verify the HTML is preserved exactly as submitted
        experiment_id = response_data["id"]
        web_experiment = WebExperiment.objects.get(id=experiment_id)
        assert web_experiment.variants is not None
        test_variant = web_experiment.variants["test"]
        transforms = test_variant["transforms"][0]

        # HTML should be preserved with original formatting
        assert transforms["html"] == complex_html
        assert transforms["text"] == "Safe <b>formatted</b> text"


def _variants_with_test_transform(transform: dict) -> dict:
    return {
        "control": {"rollout_percentage": 50},
        "test": {"rollout_percentage": 50, "transforms": [transform]},
    }


class TestWebExperimentValidationNoDB(SimpleTestCase):
    # validate() / validate_no_xss are pure (no context, no DB), so the matrix runs without
    # a database. test_validation_serializer_is_wired_to_viewset guards that the endpoint
    # actually validates through this serializer.
    def _assert_invalid(self, variants: dict, expected_substring: str) -> None:
        serializer = WebExperimentsAPISerializer(data={"name": "x", "variants": variants})
        assert not serializer.is_valid()
        assert expected_substring in str(serializer.errors).lower()

    @parameterized.expand(
        [
            ["script tag in text", {"selector": "#t", "text": '<script>alert("x")</script>'}, "script"],
            ["event handler in html", {"selector": "#t", "html": '<img src=x onerror="alert(1)">'}, "event handler"],
            [
                "javascript protocol in html",
                {"selector": "#t", "html": '<a href="javascript:alert(1)">x</a>'},
                "javascript:",
            ],
            ["iframe in html", {"selector": "#t", "html": '<iframe src="https://evil.com"></iframe>'}, "iframe"],
            ["object tag in html", {"selector": "#t", "html": "<object data=x></object>"}, "object"],
            ["data:text/html in html", {"selector": "#t", "html": "data:text/html,<b>x</b>"}, "data:text/html"],
        ]
    )
    def test_rejects_xss_in_transform(self, _name: str, transform: dict, expected_substring: str) -> None:
        self._assert_invalid(_variants_with_test_transform(transform), expected_substring)

    def test_rejects_missing_control_variant(self) -> None:
        self._assert_invalid({"test": {"rollout_percentage": 50}}, "control variant")

    def test_rejects_variant_without_rollout_percentage(self) -> None:
        self._assert_invalid({"control": {}}, "rollout percentage")

    def test_rejects_non_control_transform_without_selector(self) -> None:
        variants = {
            "control": {"rollout_percentage": 50},
            "test": {"rollout_percentage": 50, "transforms": [{"text": "hi"}]},
        }
        self._assert_invalid(variants, "selector")

    def test_validation_serializer_is_wired_to_viewset(self) -> None:
        # Wiring guard (no DB): the ModelViewSet validates input through this serializer on
        # create/update, so the no-DB matrix above covers the real endpoint validation path.
        # If serializer_class is swapped or dropped, validation silently stops running.
        assert WebExperimentViewSet.serializer_class is WebExperimentsAPISerializer
