import json
from typing import Any, Optional
from unittest.mock import ANY, patch

from django.db import connection
from freezegun import freeze_time
from inline_snapshot import snapshot
from rest_framework import status

from hogvm.python.operation import HOGQL_BYTECODE_VERSION
from posthog.constants import AvailableFeature
from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import DEFAULT_STATE, HogFunction
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from posthog.cdp.templates.webhook.template_webhook import template as template_webhook
from posthog.cdp.templates.slack.template_slack import template as template_slack


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


def get_db_field_value(field, model_id):
    cursor = connection.cursor()
    cursor.execute(f"select {field} from posthog_hogfunction where id='{model_id}';")
    return cursor.fetchone()[0]  # type: ignore


class TestHogFunctionAPIWithoutAvailableFeature(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def create_slack_function(self, data: Optional[dict] = None):
        payload = {
            "name": "Slack",
            "template_id": template_slack.id,
            "inputs": {
                "slack_workspace": {"value": 1},
                "channel": {"value": "#general"},
            },
        }

        payload.update(data or {})

        return self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data=payload,
        )

    def test_create_hog_function_works_for_free_template(self):
        response = self.create_slack_function()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json()["hog"] == template_slack.hog
        assert response.json()["inputs_schema"] == template_slack.inputs_schema

    def test_free_users_cannot_override_hog_or_schema(self):
        response = self.create_slack_function(
            {
                "hog": "fetch(inputs.url);",
                "inputs_schema": [
                    {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
                ],
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "The Data Pipelines addon is required to create custom functions."

    def test_free_users_cannot_use_without_template(self):
        response = self.create_slack_function({"template_id": None})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "The Data Pipelines addon is required to create custom functions."

    def test_free_users_cannot_use_non_free_templates(self):
        response = self.create_slack_function(
            {
                "template_id": template_webhook.id,
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json()["detail"] == "The Data Pipelines addon is required for this template."


class TestHogFunctionAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.DATA_PIPELINES, "name": AvailableFeature.DATA_PIPELINES}
        ]
        self.organization.save()

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
            "bytecode": ["_H", HOGQL_BYTECODE_VERSION, 32, "url", 32, "inputs", 1, 2, 2, "fetch", 1, 35],
            "inputs_schema": [],
            "inputs": {},
            "filters": {"bytecode": ["_H", HOGQL_BYTECODE_VERSION, 29]},
            "icon_url": None,
            "template": None,
            "masking": None,
            "status": {"rating": 0, "state": 0, "tokens": 0},
        }

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
            "masking": None,
            "sub_templates": response.json()["template"]["sub_templates"],
        }

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
        # Fernet encryption is deterministic, but has a temporal component and utilizes os.urandom() for the IV
        with freeze_time("2024-01-01T00:01:00Z"):
            with patch("os.urandom", return_value=b"\x00" * 16):
                res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.status_code == status.HTTP_201_CREATED, res.json()
        assert res.json()["inputs"] == expectation
        res = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{res.json()['id']}")
        assert res.json()["inputs"] == expectation

        # Finally check the DB has the real value
        obj = HogFunction.objects.get(id=res.json()["id"])
        assert obj.inputs == {}
        assert obj.encrypted_inputs == {
            "url": {
                "bytecode": [
                    "_H",
                    1,
                    32,
                    "I AM SECRET",
                ],
                "value": "I AM SECRET",
            },
        }

        raw_encrypted_inputs = get_db_field_value("encrypted_inputs", obj.id)

        assert (
            raw_encrypted_inputs
            == "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAEx9NjkHozEIpr88sZFSwgVZWWVGhTZXkr6Y7uw_UwUEapVuRFgmPIfijCG6lAzNk_Z33D8eoBLEMubWVOsi-ZqUiOZVzZP-S16Bhvdr_stga8vfTR1oA0_WRVM8gh0Dh4LSDn5J6hpEGSDCyfBDK68="
        )

    def test_secret_inputs_not_updated_if_not_changed(self, *args):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "secret1", "type": "string", "label": "Secret 1", "secret": True, "required": True},
                {"key": "secret2", "type": "string", "label": "Secret 2", "secret": True, "required": False},
            ],
            "inputs": {
                "secret1": {
                    "value": "I AM SECRET",
                },
            },
        }
        res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.json()["inputs"] == {"secret1": {"secret": True}}, res.json()
        res = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{res.json()['id']}",
            data={
                "inputs": {
                    "secret1": {
                        "secret": True,
                    },
                    "secret2": {
                        "value": "I AM ALSO SECRET",
                    },
                },
            },
        )
        assert res.json()["inputs"] == {"secret1": {"secret": True}, "secret2": {"secret": True}}, res.json()

        # Finally check the DB has the real value
        obj = HogFunction.objects.get(id=res.json()["id"])
        assert obj.encrypted_inputs["secret1"]["value"] == "I AM SECRET"
        assert obj.encrypted_inputs["secret2"]["value"] == "I AM ALSO SECRET"

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
            f'["_H", {HOGQL_BYTECODE_VERSION}, 33, 0, 33, 3, 36, 0, 15, 40, 45, 33, 1, 36, 0, 6, 37, 0, 32, "url", 32, "inputs", 1, 2, 32, "headers", 32, "x-count", 36, 0, 42, 1, 32, "body", 32, "payload", 32, "inputs", 1, 2, 32, "method", 32, "method", 32, "inputs", 1, 2, 42, 3, 2, "fetch", 2, 35, 39, -52, 35]'
        ), response.json()

    def test_generates_inputs_bytecode(self, *args):
        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data=EXAMPLE_FULL)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["inputs"] == {
            "url": {
                "value": "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                "bytecode": [
                    "_H",
                    HOGQL_BYTECODE_VERSION,
                    32,
                    "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                ],
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
                    "event": ["_H", HOGQL_BYTECODE_VERSION, 32, "event", 1, 1],
                    "groups": ["_H", HOGQL_BYTECODE_VERSION, 32, "groups", 1, 1],
                    "nested": {"foo": ["_H", HOGQL_BYTECODE_VERSION, 32, "url", 32, "event", 1, 2]},
                    "person": ["_H", HOGQL_BYTECODE_VERSION, 32, "person", 1, 1],
                    "event_url": [
                        "_H",
                        HOGQL_BYTECODE_VERSION,
                        32,
                        "url",
                        32,
                        "event",
                        1,
                        2,
                        32,
                        "-test",
                        2,
                        "concat",
                        2,
                    ],
                },
            },
            "method": {"value": "POST"},
            "headers": {
                "value": {"version": "v={event.properties.$lib_version}"},
                "bytecode": {
                    "version": [
                        "_H",
                        HOGQL_BYTECODE_VERSION,
                        32,
                        "v=",
                        32,
                        "$lib_version",
                        32,
                        "properties",
                        32,
                        "event",
                        1,
                        3,
                        2,
                        "concat",
                        2,
                    ]
                },
            },
        }

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
                "_H",
                HOGQL_BYTECODE_VERSION,
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
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
                32,
                "%docs%",
                32,
                "$current_url",
                32,
                "properties",
                1,
                2,
                17,
                3,
                2,
                3,
                2,
                4,
                2,
            ],
        }

    def test_saves_masking_config(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "masking": {"ttl": 60, "threshold": 20, "hash": "{person.properties.email}"},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["masking"] == snapshot(
            {
                "ttl": 60,
                "threshold": 20,
                "hash": "{person.properties.email}",
                "bytecode": ["_H", HOGQL_BYTECODE_VERSION, 32, "email", 32, "properties", 32, "person", 1, 3],
            }
        )

    @patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True)
    def test_loads_status_when_enabled_and_available(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            mock_get.return_value.status_code = status.HTTP_200_OK
            mock_get.return_value.json.return_value = {"state": 1, "tokens": 0, "rating": 0}

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
            assert response.json()["status"] == {"state": 1, "tokens": 0, "rating": 0}

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
            assert response.json()["status"] == DEFAULT_STATE

    def test_patches_status_on_enabled_update(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            with patch("posthog.plugins.plugin_server_api.requests.patch") as mock_patch:
                mock_get.return_value.status_code = status.HTTP_200_OK
                mock_get.return_value.json.return_value = {"state": 4, "tokens": 0, "rating": 0}

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

    def test_list_with_filters_filter(self, *args):
        action1 = Action.objects.create(
            team=self.team,
            name="test action",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        action2 = Action.objects.create(
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
                    "actions": [
                        {"id": f"{action1.id}", "name": "Test Action", "type": "actions", "order": 1},
                        {"id": f"{action2.id}", "name": "Test Action 2", "type": "actions", "order": 1},
                    ],
                    "filter_test_accounts": True,
                },
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        filters: Any = {"filter_test_accounts": True}
        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?filters={json.dumps(filters)}")
        assert len(response.json()["results"]) == 1

        filters = {"filter_test_accounts": False}
        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?filters={json.dumps(filters)}")
        assert len(response.json()["results"]) == 0

        filters = {"actions": [{"id": f"other"}]}
        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?filters={json.dumps(filters)}")
        assert len(response.json()["results"]) == 0

        filters = {"actions": [{"id": f"{action1.id}"}]}
        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?filters={json.dumps(filters)}")
        assert len(response.json()["results"]) == 1

        filters = {"actions": [{"id": f"{action2.id}"}]}
        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?filters={json.dumps(filters)}")
        assert len(response.json()["results"]) == 1
