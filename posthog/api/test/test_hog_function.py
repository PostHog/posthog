from unittest.mock import ANY

from rest_framework import status

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


class TestHogFunctionAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_create_hog_function(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Fetch URL",
                "description": "Test description",
                "hog": "fetch(inputs.url);",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json() == {
            "id": ANY,
            "name": "Fetch URL",
            "description": "Test description",
            "created_at": ANY,
            "created_by": ANY,
            "updated_at": ANY,
            "enabled": False,
            "hog": "fetch(inputs.url);",
            "bytecode": ["_h", 32, "url", 32, "inputs", 1, 2, 2, "fetch", 1, 35],
            "inputs_schema": [],
            "inputs": {},
            "filters": {},
        }

    def test_inputs_required(self):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
            ],
        }
        # Check required
        res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()
        assert res.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "This field is required.",
            "attr": "inputs__url",
        }

    def test_inputs_mismatch_type(self):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "string", "type": "string"},
                {"key": "dictionary", "type": "dictionary"},
                {"key": "boolean", "type": "boolean"},
            ],
        }

        bad_inputs = {
            "string": 123,
            "dictionary": 123,
            "boolean": 123,
        }

        for key, value in bad_inputs.items():
            res = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/", data={**payload, "inputs": {key: {"value": value}}}
            )
            assert res.json() == {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": f"Value must be a {key}.",
                "attr": f"inputs__{key}",
            }, f"Did not get error for {key}, got {res.json()}"
            assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()

    # def test_create_action_generates_bytecode(self):
    #     response = self.client.post(
    #         f"/api/projects/{self.team.id}/actions/",
    #         data={
    #             "name": "user signed up",
    #             "steps": [
    #                 {
    #                     "text": "sign up",
    #                     "selector": "div > button",
    #                     "url": "/signup",
    #                 }
    #             ],
    #             "description": "Test description",
    #         },
    #         HTTP_ORIGIN="http://testserver",
    #     )
    #     assert response.status_code == status.HTTP_201_CREATED, response.json()
    #     action = Action.objects.get(pk=response.json()["id"])
    #     assert action.bytecode == ["_h", 32, "%/signup%", 32, "$current_url", 32, "properties", 1, 2, 17]
