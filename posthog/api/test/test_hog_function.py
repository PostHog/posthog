import json
from unittest.mock import ANY, patch

from rest_framework import status

from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.cdp.templates.webhook.template_webhook import template as template_webhook


EXAMPLE_FULL = {
    "name": "HogHook",
    "hog": "fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.payload,\n  'method': inputs.method\n});",
    "inputs_schema": [
        {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
        {"key": "payload", "type": "json", "label": "JSON Payload", "required": True},
        {
            "key": "method",
            "type": "choice",
            "label": "HTTP Method",
            "choices": [
                {"label": "POST", "value": "POST"},
                {"label": "PUT", "value": "PUT"},
                {"label": "PATCH", "value": "PATCH"},
                {"label": "GET", "value": "GET"},
            ],
            "required": True,
        },
        {"key": "headers", "type": "dictionary", "label": "Headers", "required": False},
    ],
    "inputs": {
        "url": {
            "value": "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
        },
        "method": {"value": "POST"},
        "headers": {
            "value": {"version": "v={event.properties.$lib_version}"},
        },
        "payload": {
            "value": {
                "event": "{event}",
                "groups": "{groups}",
                "nested": {"foo": "{event.url}"},
                "person": "{person}",
                "event_url": "{f'{event.url}-test'}",
            },
        },
    },
    "filters": {
        "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
        "actions": [{"id": "9", "name": "Test Action", "type": "actions", "order": 1}],
        "filter_test_accounts": True,
    },
}


class TestHogFunctionAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @patch("posthog.permissions.posthoganalytics.feature_enabled")
    def test_create_hog_function_forbidden_if_not_in_flag(self, mock_feature_enabled):
        mock_feature_enabled.return_value = False

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Fetch URL",
                "description": "Test description",
                "hog": "fetch(inputs.url);",
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

        assert mock_feature_enabled.call_count == 1
        assert mock_feature_enabled.call_args[0][0] == ("hog-functions")

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_create_hog_function(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={"name": "Fetch URL", "description": "Test description", "hog": "fetch(inputs.url);", "inputs": {}},
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
            "filters": {"bytecode": ["_h", 29]},
            "icon_url": None,
            "template": None,
            "status": {"ratings": [], "state": 0, "states": []},
        }

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_creates_with_template_id(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Fetch URL",
                "description": "Test description",
                "hog": "fetch(inputs.url);",
                "template_id": template_webhook.id,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["template"] == {
            "name": template_webhook.name,
            "description": template_webhook.description,
            "id": template_webhook.id,
            "status": template_webhook.status,
            "icon_url": template_webhook.icon_url,
            "inputs_schema": template_webhook.inputs_schema,
            "hog": template_webhook.hog,
            "filters": None,
        }

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_deletes_via_update(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={"name": "Fetch URL", "description": "Test description", "hog": "fetch(inputs.url);"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        list_res = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        assert list_res.status_code == status.HTTP_200_OK, list_res.json()
        # Assert that it isn't in the list
        assert (
            next((item for item in list_res.json()["results"] if item["id"] == response.json()["id"]), None) is not None
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}/",
            data={"deleted": True},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        list_res = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        assert list_res.status_code == status.HTTP_200_OK, list_res.json()
        assert next((item for item in list_res.json()["results"] if item["id"] == response.json()["id"]), None) is None

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_inputs_required(self, *args):
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

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_inputs_mismatch_type(self, *args):
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

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_secret_inputs_not_returned(self, *args):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "url", "type": "string", "label": "Webhook URL", "secret": True, "required": True},
            ],
            "inputs": {
                "url": {
                    "value": "I AM SECRET",
                },
            },
        }
        expectation = {
            "url": {
                "secret": True,
            }
        }
        # Check not returned
        res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.status_code == status.HTTP_201_CREATED, res.json()
        assert res.json()["inputs"] == expectation
        res = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{res.json()['id']}")
        assert res.json()["inputs"] == expectation

        # Finally check the DB has the real value
        obj = HogFunction.objects.get(id=res.json()["id"])
        assert obj.inputs["url"]["value"] == "I AM SECRET"

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_secret_inputs_not_updated_if_not_changed(self, *args):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "url", "type": "string", "label": "Webhook URL", "secret": True, "required": True},
            ],
            "inputs": {
                "url": {
                    "value": "I AM SECRET",
                },
            },
        }
        expectation = {"url": {"secret": True}}
        res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.json()["inputs"] == expectation, res.json()
        res = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{res.json()['id']}",
            data={
                "inputs": {
                    "url": {
                        "secret": True,
                    },
                },
            },
        )
        assert res.json()["inputs"] == expectation

        # Finally check the DB has the real value
        obj = HogFunction.objects.get(id=res.json()["id"])
        assert obj.inputs["url"]["value"] == "I AM SECRET"

        # And check we can still update it
        res = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{res.json()['id']}",
            data={"inputs": {"url": {"value": "I AM A NEW SECRET"}}},
        )
        assert res.json()["inputs"] == expectation

        # Finally check the DB has the real value
        obj = HogFunction.objects.get(id=res.json()["id"])
        assert obj.inputs["url"]["value"] == "I AM A NEW SECRET"

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_generates_hog_bytecode(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Fetch URL",
                "hog": "let i := 0;\nwhile(i < 3) {\n  i := i + 1;\n  fetch(inputs.url, {\n    'headers': {\n      'x-count': f'{i}'\n    },\n    'body': inputs.payload,\n    'method': inputs.method\n  });\n}",
            },
        )
        # JSON loads for one line comparison
        assert response.json()["bytecode"] == json.loads(
            '["_h", 33, 0, 33, 3, 36, 0, 15, 40, 45, 33, 1, 36, 0, 6, 37, 0, 32, "headers", 32, "x-count", 36, 0, 42, 1, 32, "body", 32, "payload", 32, "inputs", 1, 2, 32, "method", 32, "method", 32, "inputs", 1, 2, 42, 3, 32, "url", 32, "inputs", 1, 2, 2, "fetch", 2, 35, 39, -52, 35]'
        ), response.json()

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_generates_inputs_bytecode(self, *args):
        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data=EXAMPLE_FULL)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["inputs"] == {
            "url": {
                "value": "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                "bytecode": ["_h", 32, "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937"],
            },
            "payload": {
                "value": {
                    "event": "{event}",
                    "groups": "{groups}",
                    "nested": {"foo": "{event.url}"},
                    "person": "{person}",
                    "event_url": "{f'{event.url}-test'}",
                },
                "bytecode": {
                    "event": ["_h", 32, "event", 1, 1],
                    "groups": ["_h", 32, "groups", 1, 1],
                    "nested": {"foo": ["_h", 32, "url", 32, "event", 1, 2]},
                    "person": ["_h", 32, "person", 1, 1],
                    "event_url": ["_h", 32, "-test", 32, "url", 32, "event", 1, 2, 2, "concat", 2],
                },
            },
            "method": {"value": "POST"},
            "headers": {
                "value": {"version": "v={event.properties.$lib_version}"},
                "bytecode": {
                    "version": ["_h", 32, "$lib_version", 32, "properties", 32, "event", 1, 3, 32, "v=", 2, "concat", 2]
                },
            },
        }

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_generates_filters_bytecode(self, *args):
        action = Action.objects.create(
            team=self.team,
            name="test action",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                    "actions": [{"id": f"{action.id}", "name": "Test Action", "type": "actions", "order": 1}],
                    "filter_test_accounts": True,
                },
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["filters"] == {
            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            "actions": [{"id": f"{action.id}", "name": "Test Action", "type": "actions", "order": 1}],
            "filter_test_accounts": True,
            "bytecode": [
                "_h",
                32,
                "%docs%",
                32,
                "$current_url",
                32,
                "properties",
                1,
                2,
                17,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                3,
                2,
                32,
                "%@posthog.com%",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                20,
                3,
                2,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                32,
                "%@posthog.com%",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                20,
                3,
                2,
                4,
                2,
            ],
        }

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_loads_status_when_enabled_and_available(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            mock_get.return_value.status_code = status.HTTP_200_OK
            mock_get.return_value.json.return_value = {"state": 1, "states": [], "ratings": []}

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    "name": "Fetch URL",
                    "description": "Test description",
                    "hog": "fetch(inputs.url);",
                    "template_id": template_webhook.id,
                    "enabled": True,
                },
            )
            assert response.status_code == status.HTTP_201_CREATED, response.json()

            response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}")
            assert response.json()["status"] == {"state": 1, "states": [], "ratings": []}

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_does_not_crash_when_status_not_available(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            # Mock the api actually throwing fully
            mock_get.side_effect = lambda x: Exception("oh no")

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    "name": "Fetch URL",
                    "description": "Test description",
                    "hog": "fetch(inputs.url);",
                    "template_id": template_webhook.id,
                    "enabled": True,
                },
            )
            assert response.status_code == status.HTTP_201_CREATED, response.json()
            response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}")
            assert response.json()["status"] == {"ratings": [], "state": 0, "states": []}

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_patches_status_on_enabled_update(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            with patch("posthog.plugins.plugin_server_api.requests.patch") as mock_patch:
                mock_get.return_value.status_code = status.HTTP_200_OK
                mock_get.return_value.json.return_value = {"state": 4, "states": [], "ratings": []}

                response = self.client.post(
                    f"/api/projects/{self.team.id}/hog_functions/",
                    data={"name": "Fetch URL", "hog": "fetch(inputs.url);", "enabled": True},
                )

                assert response.json()["status"]["state"] == 4

                self.client.patch(
                    f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}/",
                    data={"enabled": False},
                )

                assert mock_patch.call_count == 0

                self.client.patch(
                    f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}/",
                    data={"enabled": True},
                )

                assert mock_patch.call_count == 1
                mock_patch.assert_called_once_with(
                    f"http://localhost:6738/api/projects/{self.team.id}/hog_functions/{response.json()['id']}/status",
                    json={"state": 2},
                )
