from posthog.test.base import APIBaseTest
from posthog.warehouse.models import QueryTabState


class TestQueryTabState(APIBaseTest):
    def test_create_query_tab_state(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/query_tab_state",
            data={
                "state": {
                    "editorModelsStateKey": ["my_model"],
                    "activeModelStateKey": "my_model",
                    "activeModelVariablesStateKey": "my_model_variables",
                }
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["state"],
            {
                "editorModelsStateKey": ["my_model"],
                "activeModelStateKey": "my_model",
                "activeModelVariablesStateKey": "my_model_variables",
            },
        )

    def test_get_query_tab_state(self):
        query_tab_state = QueryTabState.objects.create(
            team=self.team,
            state={
                "editorModelsStateKey": ["my_model"],
                "activeModelStateKey": "my_model",
                "activeModelVariablesStateKey": "my_model_variables",
            },
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/query_tab_state/{query_tab_state.pk}",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["state"],
            {
                "editorModelsStateKey": ["my_model"],
                "activeModelStateKey": "my_model",
                "activeModelVariablesStateKey": "my_model_variables",
            },
        )

    def test_update_query_tab_state(self):
        query_tab_state = QueryTabState.objects.create(
            team=self.team,
            state={
                "editorModelsStateKey": ["my_model"],
                "activeModelStateKey": "my_model",
                "activeModelVariablesStateKey": "my_model_variables",
            },
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/query_tab_state/{query_tab_state.pk}",
            data={
                "state": {
                    "editorModelsStateKey": ["my_model_2"],
                    "activeModelStateKey": "my_model_2",
                    "activeModelVariablesStateKey": "my_model_variables_2",
                }
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["state"],
            {
                "editorModelsStateKey": ["my_model_2"],
                "activeModelStateKey": "my_model_2",
                "activeModelVariablesStateKey": "my_model_variables_2",
            },
        )

    def test_delete_query_tab_state(self):
        query_tab_state = QueryTabState.objects.create(
            team=self.team,
            state={
                "editorModelsStateKey": ["my_model"],
                "activeModelStateKey": "my_model",
                "activeModelVariablesStateKey": "my_model_variables",
            },
        )

        response = self.client.delete(
            f"/api/projects/{self.team.id}/query_tab_state/{query_tab_state.pk}",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(QueryTabState.objects.count(), 0)
