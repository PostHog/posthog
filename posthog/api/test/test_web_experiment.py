from rest_framework import status

from posthog.models import WebExperiment
from posthog.test.base import APIBaseTest


class TestWebExperiment(APIBaseTest):
    def _create_web_experiment(self):
        return self.client.post(
            f"/api/projects/{self.team.id}/web_experiments/",
            data={
                "name": "Zero to Web Experiment",
                "variants": {
                    "control": {
                        "transforms": [
                            {"html": "", "text": "There goes Superman!", "selector": "#page > #body > .header h1"}
                        ],
                        "variant_name": "variant #0",
                        "rollout_percentage": 70,
                    },
                    "test": {
                        "transforms": [
                            {"html": "", "text": "Up, UP and Away!", "selector": "#page > #body > .header h1"}
                        ],
                        "variant_name": "variant #1",
                        "rollout_percentage": 30,
                    },
                },
            },
            format="json",
        )

    def test_can_create_basic_web_experiment(self):
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

        assert web_experiment.variants is not None
        assert web_experiment.type == "web"
        assert web_experiment.variants.get("control") is not None
        assert web_experiment.variants.get("test") is not None

    def test_can_delete_web_experiment(self):
        response = self._create_web_experiment()
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        experiment_id = response_data["id"]
        assert WebExperiment.objects.filter(id=experiment_id).exists()
        del_response = self.client.delete(f"/api/projects/{self.team.id}/web_experiments/{experiment_id}")
        assert del_response.status_code == status.HTTP_204_NO_CONTENT
        assert WebExperiment.objects.filter(id=experiment_id).exists() is False
