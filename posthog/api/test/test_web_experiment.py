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
