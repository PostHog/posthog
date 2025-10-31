import json
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import ANY, MagicMock, patch

from django.db import connection

from inline_snapshot import snapshot
from rest_framework import status

from posthog.api.hog_function import MAX_HOG_CODE_SIZE_BYTES, MAX_TRANSFORMATIONS_PER_TEAM
from posthog.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.cdp.templates.slack.template_slack import template as template_slack
from posthog.models.action.action import Action
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.hog_function import DEFAULT_STATE, HogFunction, HogFunctionState

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION, Operation

webhook_template = MOCK_NODE_TEMPLATES[0]
geoip_template = MOCK_NODE_TEMPLATES[2]


EXAMPLE_FULL = {
    "name": "HogHook",
    "hog": "fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.payload,\n  'method': inputs.method\n});",
    "type": "destination",
    "code_language": "hog",
    "enabled": True,
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
    return cursor.fetchone()[0]


class TestHogFunctionAPIWithoutAvailableFeature(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()
        # Create slack template in DB
        sync_template_to_db(template_slack)
        sync_template_to_db(webhook_template)

    def _create_slack_function(self, data: Optional[dict] = None):
        payload = {
            "name": "Slack",
            "template_id": template_slack.id,
            "type": "destination",
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
        response = self._create_slack_function()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json()["hog"] == template_slack.code
        assert response.json()["inputs_schema"] == template_slack.inputs_schema

    def test_sers_can_update_non_free_templates(self):
        self.organization.save()

        response = self._create_slack_function(
            {
                "name": "Webhook",
                "template_id": "template-webhook",
                "inputs": {
                    "url": {"value": "https://example.com"},
                },
            }
        )

        assert response.json()["template"]["status"] == "beta"

        self.organization.available_product_features = []
        self.organization.save()

        payload = {
            "name": "Webhook",
            "template_id": "template-webhook",
            "inputs": {
                "url": {"value": "https://example.com/posthog-webhook-updated"},
            },
        }

        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}/",
            data=payload,
        )

        assert update_response.status_code == status.HTTP_200_OK, update_response.json()
        assert update_response.json()["inputs"]["url"]["value"] == "https://example.com/posthog-webhook-updated"

    def test_internal_destinations_can_be_managed_without_addon(self):
        self.organization.available_product_features = []
        self.organization.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "My custom function",
                "hog": "fetch('https://example.com');",
                "type": "internal_destination",
                "template_id": "template-slack",
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        function_id = response.json()["id"]

        # Update it
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function_id}/",
            data={"name": "New name"},
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK, update_response.json())
        self.assertEqual(update_response.json()["name"], "New name")

        # Delete it
        delete_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function_id}/",
            data={"deleted": True},
        )
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK, delete_response.json())


class TestHogFunctionAPI(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        self.organization.save()

        # Create slack template in DB
        sync_template_to_db(template_slack)
        sync_template_to_db(webhook_template)
        sync_template_to_db(geoip_template)

        # Create the action referenced in EXAMPLE_FULL (use auto-generated ID to avoid sequence collision)
        self.test_action, _ = Action.objects.get_or_create(
            name="Test Action", team=self.team, defaults={"created_by": self.user}
        )
        # Update EXAMPLE_FULL to use the actual action ID
        EXAMPLE_FULL["filters"]["actions"][0]["id"] = str(self.test_action.id)

    def _get_function_activity(
        self,
        function_id: Optional[int] = None,
    ) -> list:
        params: dict = {"scope": "HogFunction", "page": 1, "limit": 20}
        if function_id:
            params["item_id"] = function_id
        activity = self.client.get(f"/api/projects/{self.team.pk}/activity_log", data=params)
        self.assertEqual(activity.status_code, status.HTTP_200_OK)
        return activity.json().get("results")

    def _filter_expected_keys(self, actual_data, expected_structure):
        if isinstance(expected_structure, list) and expected_structure and isinstance(expected_structure[0], dict):
            return [self._filter_expected_keys(item, expected_structure[0]) for item in actual_data]
        elif isinstance(expected_structure, dict):
            return {
                key: self._filter_expected_keys(actual_data.get(key), expected_value)
                for key, expected_value in expected_structure.items()
            }
        else:
            return actual_data

    def test_create_hog_function(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "type": "destination",
                "name": "Fetch URL",
                "description": "Test description",
                "hog": "fetch(inputs.url);",
                "inputs": {},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"]["id"] == self.user.id
        assert response.json() == {
            "id": ANY,
            "type": "destination",
            "name": "Fetch URL",
            "description": "Test description",
            "created_at": ANY,
            "created_by": ANY,
            "updated_at": ANY,
            "enabled": False,
            "hog": "fetch(inputs.url);",
            "bytecode": ["_H", HOGQL_BYTECODE_VERSION, 32, "url", 32, "inputs", 1, 2, 2, "fetch", 1, 35],
            "transpiled": None,
            "inputs_schema": [],
            "inputs": {},
            "filters": {
                "source": "events",
                "bytecode": ["_H", HOGQL_BYTECODE_VERSION, 29],
            },
            "icon_url": None,
            "template": None,
            "masking": None,
            "mappings": None,
            "status": {"state": 0, "tokens": 0},
            "execution_order": None,
        }

        id = response.json()["id"]
        expected_activities = [
            {
                "activity": "created",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": None,
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
        ]
        actual_activities = self._get_function_activity(id)
        filtered_actual_activities = [
            self._filter_expected_keys(actual_activity, expected_activity)
            for actual_activity, expected_activity in zip(actual_activities, expected_activities)
        ]
        assert filtered_actual_activities == expected_activities

    def test_creates_with_template_id(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Fetch URL",
                "description": "Test description",
                "hog": "fetch(inputs.url);",
                "inputs": {"url": {"value": "https://example.com"}},
                "template_id": "template-webhook",
                "type": "destination",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        assert response.json()["hog"] == "fetch(inputs.url);"
        assert response.json()["template"] == {
            "type": "destination",
            "free": False,
            "name": webhook_template["name"],
            "description": webhook_template["description"],
            "id": "template-webhook",
            "status": "beta",
            "icon_url": webhook_template["icon_url"],
            "category": webhook_template["category"],
            "code_language": "hog",
            "inputs_schema": webhook_template["inputs_schema"],
            "code": webhook_template["code"].strip(),
            "filters": None,
            "masking": None,
            "mapping_templates": None,
        }

    def test_creates_with_template_values_if_not_provided(self, *args):
        payload: dict = {
            "template_id": "template-webhook",
            "type": "destination",
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data=payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json() == {
            "attr": "inputs__url",
            "code": "invalid_input",
            "detail": "This field is required.",
            "type": "validation_error",
        }

        payload["inputs"] = {"url": {"value": "https://example.com"}}

        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data=payload)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["hog"] == webhook_template["code"].strip()
        assert response.json()["inputs_schema"] == webhook_template["inputs_schema"]
        assert response.json()["name"] == webhook_template["name"]
        assert response.json()["description"] == webhook_template["description"]
        assert response.json()["icon_url"] == webhook_template["icon_url"]

    def test_deletes_via_update(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "name": "Fetch URL",
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        id = response.json()["id"]

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

        expected_activities = [
            {
                "activity": "updated",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": [
                        {
                            "action": "changed",
                            "after": True,
                            "before": False,
                            "field": "deleted",
                            "type": "HogFunction",
                        }
                    ],
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
            {
                "activity": "created",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": None,
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
        ]
        actual_activities = self._get_function_activity(id)
        filtered_actual_activities = [
            self._filter_expected_keys(actual_activity, expected_activity)
            for actual_activity, expected_activity in zip(actual_activities, expected_activities)
        ]
        assert filtered_actual_activities == expected_activities

    def test_can_undelete_hog_function(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={**EXAMPLE_FULL},
        )
        id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{id}/",
            data={"deleted": True},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert (
            self.client.get(f"/api/projects/{self.team.id}/hog_functions/{id}").status_code == status.HTTP_404_NOT_FOUND
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{id}/",
            data={"deleted": False},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.client.get(f"/api/projects/{self.team.id}/hog_functions/{id}").status_code == status.HTTP_200_OK

    def test_inputs_required(self, *args):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
            ],
            "type": "destination",
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

    def test_validation_error_on_invalid_type(self, *args):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
            ],
            "type": "invalid_type",
        }
        # Check required
        res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.status_code == status.HTTP_400_BAD_REQUEST, res.json()
        assert res.json() == {
            "type": "validation_error",
            "code": "invalid_choice",
            "detail": '"invalid_type" is not a valid choice.',
            "attr": "type",
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
            "type": "destination",
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

    def test_validates_input_schema(self, *args):
        payload = {
            "name": "Fetch URL",
            "hog": "fetch(inputs.url);",
            "inputs_schema": [
                {"key": "not-a-key", "type": "not-valid", "label": "Webhook URL"},
            ],
            "type": "destination",
        }
        # Check required
        res = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data={**payload})
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        assert res.json() == {
            "type": "validation_error",
            "code": "invalid_choice",
            "detail": '"not-valid" is not a valid choice.',
            "attr": "inputs_schema__0__type",
        }

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
            "type": "destination",
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
                "order": 0,
            },
        }

        raw_encrypted_inputs = get_db_field_value("encrypted_inputs", obj.id)

        assert (
            raw_encrypted_inputs
            == "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAKvzDjuLG689YjjVhmmbXAtZSRoucXuT8VtokVrCotIx3ttPcVufoVt76dyr2phbuotMldKMVv_Y6uzMDZFjX1Uvej4GHsYRbsTN_txcQHNnU7zvLee83DhHIrThEjceoq8i7hbfKrvqjEi7GCGc_k_Gi3V5KFxDOfLKnke4KM4s"
        )

    def test_secret_inputs_not_updated_if_not_changed(self, *args):
        payload = {
            "type": "destination",
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

    def test_secret_inputs_updated_if_changed(self, *args):
        payload = {
            "type": "destination",
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
        id = res.json()["id"]
        assert res.json().get("inputs") == {"secret1": {"secret": True}}, res.json()
        res = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{res.json()['id']}",
            data={
                "inputs": {
                    "secret1": {
                        "value": "I AM CHANGED",
                    },
                    "secret2": {
                        "value": "I AM ALSO SECRET",
                    },
                },
            },
        )
        assert res.json().get("inputs") == {"secret1": {"secret": True}, "secret2": {"secret": True}}, res.json()

        # Finally check the DB has the real value
        obj = HogFunction.objects.get(id=res.json()["id"])
        assert obj.encrypted_inputs["secret1"]["value"] == "I AM CHANGED"
        assert obj.encrypted_inputs["secret2"]["value"] == "I AM ALSO SECRET"

        # changes to encrypted inputs aren't persisted
        expected_activities = [
            {
                "activity": "updated",
                "created_at": ANY,
                "detail": {
                    "changes": [
                        {
                            "action": "changed",
                            "after": "masked",
                            "before": "masked",
                            "field": "encrypted_inputs",
                            "type": "HogFunction",
                        }
                    ],
                    "name": "Fetch URL",
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
            {
                "activity": "created",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": None,
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
        ]
        actual_activities = self._get_function_activity(id)
        filtered_actual_activities = [
            self._filter_expected_keys(actual_activity, expected_activity)
            for actual_activity, expected_activity in zip(actual_activities, expected_activities)
        ]
        assert filtered_actual_activities == expected_activities

    def test_generates_hog_bytecode(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
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
                "order": 0,
            },
            "payload": {
                "value": {
                    "event": "{event}",
                    "groups": "{groups}",
                    "nested": {"foo": "{event.url}"},
                    "person": "{person}",
                    "event_url": "{f'{event.url}-test'}",
                },
                "order": 1,
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
            "method": {"value": "POST", "order": 2},
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
                "order": 3,
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
            "source": "events",
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
                2,
                "toString",
                1,
                20,
                32,
                "$pageview",
                32,
                "event",
                1,
                1,
                11,
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
                4,
                2,
                3,
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
            mock_get.return_value.json.return_value = {
                "state": 1,
                "tokens": 0,
            }

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data=EXAMPLE_FULL,
            )
            assert response.status_code == status.HTTP_201_CREATED, response.json()

            response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}")
            assert response.json()["status"] == {
                "state": 1,
                "tokens": 0,
            }

    def test_does_not_crash_when_status_not_available(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            # Mock the api actually throwing fully
            mock_get.side_effect = lambda x: Exception("oh no")

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data=EXAMPLE_FULL,
            )
            assert response.status_code == status.HTTP_201_CREATED, response.json()
            response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}")
            assert response.json()["status"] == DEFAULT_STATE

    def test_patches_status_on_enabled_update(self, *args):
        with patch("posthog.plugins.plugin_server_api.requests.get") as mock_get:
            with patch("posthog.plugins.plugin_server_api.requests.patch") as mock_patch:
                mock_get.return_value.status_code = status.HTTP_200_OK
                mock_get.return_value.json.return_value = {
                    "state": HogFunctionState.DISABLED.value,
                    "tokens": 0,
                }

                response = self.client.post(
                    f"/api/projects/{self.team.id}/hog_functions/",
                    data={
                        **EXAMPLE_FULL,
                        "name": "Fetch URL",
                    },
                )
                id = response.json()["id"]

                assert response.json()["status"]["state"] == HogFunctionState.DISABLED.value

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

        expected_activities = [
            {
                "activity": "updated",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": [
                        {
                            "action": "changed",
                            "after": True,
                            "before": False,
                            "field": "enabled",
                            "type": "HogFunction",
                        }
                    ],
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
            {
                "activity": "updated",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": [
                        {
                            "action": "changed",
                            "after": False,
                            "before": True,
                            "field": "enabled",
                            "type": "HogFunction",
                        }
                    ],
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
            {
                "activity": "created",
                "created_at": ANY,
                "detail": {
                    "name": "Fetch URL",
                    "changes": None,
                    "short_id": None,
                    "trigger": None,
                    "type": "destination",
                },
                "item_id": id,
                "scope": "HogFunction",
                "user": {
                    "email": "user1@posthog.com",
                    "first_name": "",
                },
            },
        ]
        actual_activities = self._get_function_activity(id)
        filtered_actual_activities = [
            self._filter_expected_keys(actual_activity, expected_activity)
            for actual_activity, expected_activity in zip(actual_activities, expected_activities)
        ]
        assert filtered_actual_activities == expected_activities

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

    def test_list_with_filter_groups_filter(self, *args):
        action1 = Action.objects.create(
            team=self.team,
            name="test action",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
            },
        )
        hog_function_id_1 = response.json()["id"]
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "filters": {
                    "actions": [{"id": f"{action1.id}", "name": "Test Action", "type": "actions", "order": 1}],
                },
            },
        )
        hog_function_id_2 = response.json()["id"]
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        filter_groups: Any = [{"events": [{"id": "$pageview", "type": "events"}]}]
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_functions/?filter_groups={json.dumps(filter_groups)}"
        )
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == hog_function_id_1

        filter_groups = [{"actions": [{"id": f"{action1.id}", "type": "actions"}]}]
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_functions/?filter_groups={json.dumps(filter_groups)}"
        )
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == hog_function_id_2

        filter_groups = [
            {"actions": [{"id": f"{action1.id}", "type": "actions"}]},
            {"events": [{"id": "$pageview", "type": "events"}]},
        ]
        response = self.client.get(
            f"/api/projects/{self.team.id}/hog_functions/?filter_groups={json.dumps(filter_groups)}"
        )
        assert len(response.json()["results"]) == 2

    def test_list_with_type_filter(self, *args):
        response_destination = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        )

        destination_id = response_destination.json()["id"]

        response_transform = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "HogTransform",
                "hog": "return event",
                "type": "transformation",
                "template_id": "template-geoip",
                "enabled": True,
            },
        )

        assert response_transform.status_code == status.HTTP_201_CREATED, response_transform.json()

        transformation_id = response_transform.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        assert len(response.json()["results"]) == 2

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?type=destination")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == destination_id

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?type=transformation")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == transformation_id

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?type=destination,site_app")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == destination_id

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?type=destination,transformation")
        assert len(response.json()["results"]) == 2

    def test_list_with_enabled_filter(self, *args):
        response_destination = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                },
            },
        )

        destination_id = response_destination.json()["id"]

        response_transform = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "HogTransform",
                "hog": "return event",
                "type": "transformation",
                "template_id": "template-geoip",
                "enabled": False,
            },
        )

        transformation_id = response_transform.json()["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        assert len(response.json()["results"]) == 2

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?enabled=true")

        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == destination_id

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?enabled=false")
        assert len(response.json()["results"]) == 1
        assert response.json()["results"][0]["id"] == transformation_id

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/?enabled=true,false")
        assert len(response.json()["results"]) == 2

    def test_create_hog_function_with_site_app_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Site App Function",
                "hog": "export function onLoad() { console.log('Hello, site_app'); }",
                "type": "site_app",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["bytecode"] is None
        assert "Hello, site_app" in response.json()["transpiled"]

    def test_create_hog_function_with_site_destination_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Site Destination Function",
                "hog": "export function onLoad() { console.log('Hello, site_destination'); }",
                "type": "site_destination",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["bytecode"] is None
        assert "Hello, site_destination" in response.json()["transpiled"]

    def test_cannot_modify_type_of_existing_hog_function(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data=EXAMPLE_FULL,
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{response.json()['id']}/",
            data={"type": "site_app"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json() == {
            "attr": "type",
            "detail": "Cannot modify the type of an existing function",
            "code": "invalid_input",
            "type": "validation_error",
        }

    def test_transpiled_field_not_populated_for_other_types(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data=EXAMPLE_FULL,
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["bytecode"] is not None
        assert response.json()["transpiled"] is None

    def test_create_hog_function_with_invalid_typescript(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Invalid Site App Function",
                "hog": "export function onLoad() { console.log('Missing closing brace');",
                "type": "site_app",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "detail" in response.json()
        assert "Error in TypeScript code" in response.json()["detail"]

    def test_create_typescript_destination_with_inputs(self):
        payload = {
            "name": "TypeScript Destination Function",
            "hog": "export function onLoad() { console.log(inputs.message); }",
            "type": "site_destination",
            "inputs_schema": [
                {"key": "message", "type": "string", "label": "Message", "required": True},
            ],
            "inputs": {
                "message": {
                    "value": "Hello, TypeScript {arrayMap(a -> a, [1, 2, 3])}!",
                },
            },
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data=payload,
        )
        result = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert result["bytecode"] is None
        assert "Hello, TypeScript" in result["transpiled"]
        inputs = result["inputs"]
        inputs["message"]["transpiled"]["stl"].sort()
        assert result["inputs"] == {
            "message": {
                "order": 0,
                "transpiled": {
                    "code": 'concat("Hello, TypeScript ", arrayMap(__lambda((a) => a), [1, 2, 3]), "!")',
                    "lang": "ts",
                    "stl": sorted(["__lambda", "concat", "arrayMap"]),
                },
                "value": "Hello, TypeScript {arrayMap(a -> a, [1, 2, 3])}!",
            }
        }

    def test_validates_mappings(self):
        payload = {
            "name": "TypeScript Destination Function",
            "hog": "export function onLoad() { console.log(inputs.message); }",
            "type": "site_destination",
            "mappings": [
                {
                    "inputs": {"message": {"value": "Hello, TypeScript {arrayMap(a -> a, [1, 2, 3])}!"}},
                    "inputs_schema": [
                        {"key": "message", "type": "string", "label": "Message", "required": True},
                        {"key": "required_field", "type": "string", "label": "Required", "required": True},
                    ],
                },
            ],
        }

        def create(payload):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data=payload,
            )
            return response

        response = create(payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert response.json() == snapshot(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This field is required.",
                "attr": "mappings__0__inputs__required_field",
            }
        )

    def test_compiles_valid_mappings(self):
        payload = {
            "name": "TypeScript Destination Function",
            "hog": "print(inputs.message)",
            "type": "destination",
            "mappings": [
                {
                    "inputs": {"message": {"value": "Hello, {arrayMap(a -> a, [1, 2, 3])}!"}},
                    "inputs_schema": [
                        {"key": "message", "type": "string", "label": "Message", "required": True},
                    ],
                    "filters": {
                        "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                        "filter_test_accounts": True,
                    },
                },
            ],
        }

        def create(payload):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data=payload,
            )
            return response

        response = create(payload)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["mappings"] == snapshot(
            [
                {
                    "inputs_schema": [
                        {
                            "type": "string",
                            "key": "message",
                            "label": "Message",
                            "required": True,
                            "secret": False,
                            "hidden": False,
                        }
                    ],
                    "inputs": {
                        "message": {
                            "value": "Hello, {arrayMap(a -> a, [1, 2, 3])}!",
                            "bytecode": [
                                "_H",
                                1,
                                32,
                                "Hello, ",
                                52,
                                "lambda",
                                1,
                                0,
                                3,
                                36,
                                0,
                                38,
                                53,
                                0,
                                33,
                                1,
                                33,
                                2,
                                33,
                                3,
                                43,
                                3,
                                2,
                                "arrayMap",
                                2,
                                32,
                                "!",
                                2,
                                "concat",
                                3,
                            ],
                            "order": 0,
                        }
                    },
                    "filters": {
                        "source": "events",
                        "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                        "bytecode": [
                            "_H",
                            1,
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
                            2,
                            "toString",
                            1,
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
                        ],
                        "filter_test_accounts": True,
                    },
                }
            ]
        )

    def test_transformation_type_gets_execution_order_automatically(self):
        # Create first transformation function
        response1 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "type": "transformation",
                "name": "First Transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response1.status_code == status.HTTP_201_CREATED
        assert response1.json()["execution_order"] == 1

        # Create second transformation function
        response2 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "type": "transformation",
                "name": "Second Transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response2.status_code == status.HTTP_201_CREATED
        assert response2.json()["execution_order"] == 2

        # Create a non-transformation function - should not get execution_order
        response3 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                **EXAMPLE_FULL,  # This is fine for destination type
                "type": "destination",
                "name": "Destination Function",
            },
        )
        assert response3.status_code == status.HTTP_201_CREATED
        assert response3.json()["execution_order"] is None

    def test_list_hog_functions_ordered_by_execution_order_and_updated_at(self):
        # Create functions with different execution orders and update times
        # First create all functions with the same timestamp
        with freeze_time("2024-01-01T00:00:00Z"):
            self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    **EXAMPLE_FULL,
                    "name": "Function 1",
                    "execution_order": 1,
                },
            ).json()

            self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    **EXAMPLE_FULL,
                    "name": "Function 2",
                    "execution_order": 1,  # Same execution_order as fn1
                },
            ).json()

            self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    **EXAMPLE_FULL,
                    "name": "Function 3",
                    "execution_order": 2,
                },
            ).json()

            self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    **EXAMPLE_FULL,
                    "name": "Function 4",
                    "execution_order": None,  # No execution order
                },
            ).json()

        response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]

        # Verify order: execution_order ASC, created_at ASC, nulls last
        assert [f["name"] for f in results] == [
            "Function 1",  # execution_order=1, created first
            "Function 2",  # execution_order=1, created second
            "Function 3",  # execution_order=2
            "Function 4",  # execution_order=null
        ]

    def test_can_call_a_test_invocation(self):
        with patch("posthog.api.hog_function.create_hog_invocation_test") as mock_create_hog_invocation_test:
            res = MagicMock(status_code=200, json=lambda: {"status": "success"})
            mock_create_hog_invocation_test.return_value = res

            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/new/invocations/",
                data={
                    "configuration": {
                        **EXAMPLE_FULL,
                    },
                },
            )

            assert response.status_code == status.HTTP_200_OK, response.json()
            assert response.json() == {"status": "success"}

            assert mock_create_hog_invocation_test.call_count == 1
            assert mock_create_hog_invocation_test.call_args_list[0].kwargs["team_id"] == self.team.id
            assert mock_create_hog_invocation_test.call_args_list[0].kwargs["hog_function_id"] == "new"
            assert (
                mock_create_hog_invocation_test.call_args_list[0].kwargs["payload"]["configuration"]["type"]
                == "destination"
            )
            assert mock_create_hog_invocation_test.call_args_list[0].kwargs["payload"]["configuration"]["inputs"][
                "url"
            ] == {
                "bytecode": [
                    "_H",
                    1,
                    Operation.STRING,
                    "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                ],
                "order": 0,
                "value": "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
            }

    def test_can_update_with_null_filters(self):
        # First create a function with filters
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Test Function",
                "type": "destination",
                "hog": "print('hello world')",
                "filters": {
                    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
                    "filter_test_accounts": True,
                },
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        function_id = response.json()["id"]

        # Verify filters were saved
        function = HogFunction.objects.get(id=function_id)
        assert function.filters.get("events") is not None
        assert function.filters.get("filter_test_accounts") is True
        assert function.filters.get("bytecode") is not None

        # Now update the function with null filters
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function_id}/",
            data={"filters": None},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        # Verify filters were updated to an empty object with valid bytecode
        function.refresh_from_db()
        assert function.filters.get("events", None) is None
        assert function.filters.get("filter_test_accounts", None) is None
        assert function.filters.get("bytecode") is not None

        # Also test with empty object
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function_id}/",
            data={"filters": {}},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

        # Verify filters remain an empty object with valid bytecode
        function.refresh_from_db()
        assert function.filters.get("events", None) is None
        assert function.filters.get("filter_test_accounts", None) is None
        assert function.filters.get("bytecode") is not None

    def test_limits_transformation_functions_per_team(self):
        """Test that we can create unlimited disabled transformations but only 20 enabled ones"""
        # 1. Create several disabled transformations (more than the limit)
        for i in range(5):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    "name": f"Disabled Transformation {i}",
                    "type": "transformation",
                    "hog": "return event",
                    "enabled": False,
                },
            )
            assert response.status_code == status.HTTP_201_CREATED

        # 2. Create enabled transformations up to the limit
        for i in range(MAX_TRANSFORMATIONS_PER_TEAM):
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_functions/",
                data={
                    "name": f"Enabled Transformation {i}",
                    "type": "transformation",
                    "hog": "return event",
                    "enabled": True,
                },
            )
            assert response.status_code == status.HTTP_201_CREATED

        # 3. Verify we hit the limit when trying to create one more enabled transformation
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "One Too Many",
                "type": "transformation",
                "hog": "return event",
                "enabled": True,
            },
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 20 enabled transformation functions" in response.json()["detail"]

        # 4. Verify we can still create disabled transformations when at the limit
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Another Disabled",
                "type": "transformation",
                "hog": "return event",
                "enabled": False,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED

        # 5. Test that we can enable after deleting an enabled one
        # First delete an enabled transformation
        enabled_transformation = HogFunction.objects.filter(
            team=self.team, type="transformation", deleted=False, enabled=True
        ).first()

        assert enabled_transformation is not None, "No enabled transformation found to delete"
        self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{enabled_transformation.id}/",
            data={"deleted": True},
        )

        # Then enable a disabled transformation
        disabled_transformation = HogFunction.objects.filter(
            team=self.team, type="transformation", deleted=False, enabled=False
        ).first()

        assert disabled_transformation is not None, "No disabled transformation found to enable"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{disabled_transformation.id}/",
            data={"enabled": True},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_validates_raw_hog_code_size(self):
        """Test that we validate the raw HOG code size before compiling it."""
        # Generate a large HOG code string that exceeds the maximum allowed size
        large_hog_code = "return " + "x" * (MAX_HOG_CODE_SIZE_BYTES + 1000)

        # Try to create a function with HOG code exceeding the size limit
        # No need to mock compile_hog as we're checking the string size directly
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Large HOG Code Function",
                "type": "transformation",
                "hog": large_hog_code,
            },
        )

        # Verify the creation was rejected with the correct error
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "HOG code exceeds maximum size" in response.json()["detail"]
        assert f"{MAX_HOG_CODE_SIZE_BYTES // 1024}KB" in response.json()["detail"]

    def test_validates_raw_hog_code_size_during_update(self):
        """Test that we validate the raw HOG code size when updating an existing function."""
        # First create a hog function with small, valid code
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Valid HOG Code Function",
                "type": "transformation",
                "hog": "return event",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        function_id = response.json()["id"]

        # Generate a large HOG code string for the update that exceeds the limit
        large_hog_code = "return " + "x" * (MAX_HOG_CODE_SIZE_BYTES + 1000)

        # Update the function with large HOG code
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function_id}/",
            data={
                "hog": large_hog_code,
            },
        )

        # Verify the update was rejected with the correct error
        assert update_response.status_code == status.HTTP_400_BAD_REQUEST, update_response.json()
        assert "HOG code exceeds maximum size" in update_response.json()["detail"]
        assert f"{MAX_HOG_CODE_SIZE_BYTES // 1024}KB" in update_response.json()["detail"]

    def test_transformation_undeletion_puts_at_end(self, *args):
        """Test that undeleted transformation functions are placed at the end of the execution order sequence."""

        # Create initial transformations
        response1 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform A",
                "type": "transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response1.status_code == status.HTTP_201_CREATED

        response2 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform B",
                "type": "transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response2.status_code == status.HTTP_201_CREATED
        fn_b_id = response2.json()["id"]

        # Delete function B
        delete_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{fn_b_id}/",
            data={"deleted": True},
        )
        assert delete_response.status_code == status.HTTP_200_OK

        # Create a third function
        response3 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform C",
                "type": "transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response3.status_code == status.HTTP_201_CREATED
        # At this point we should have A with order 1 and C with order 2
        list_response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        results = list_response.json()["results"]
        transformations = [f for f in results if f["type"] == "transformation"]
        assert len(transformations) == 2

        # Verify current order
        fn_orders = {f["name"]: f["execution_order"] for f in transformations}
        assert fn_orders["Transform A"] == 1
        assert fn_orders["Transform C"] == 2

        # Now undelete function B
        undelete_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{fn_b_id}/",
            data={"deleted": False},
        )
        assert undelete_response.status_code == status.HTTP_200_OK

        # Check order - B should now be at the end (order 3)
        list_response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        results = list_response.json()["results"]
        transformations = [f for f in results if f["type"] == "transformation"]
        assert len(transformations) == 3

        fn_orders = {f["name"]: f["execution_order"] for f in transformations}
        assert fn_orders["Transform A"] == 1
        assert fn_orders["Transform C"] == 2
        assert fn_orders["Transform B"] == 3

    def test_transformation_reenabling_puts_at_end(self, *args):
        """Test that re-enabled transformation functions are placed at the end of the execution order sequence."""

        # Create initial transformations - all enabled
        response1 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform A",
                "type": "transformation",
                "template_id": template_slack.id,
                "enabled": True,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response1.status_code == status.HTTP_201_CREATED

        response2 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform B",
                "type": "transformation",
                "template_id": template_slack.id,
                "enabled": True,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response2.status_code == status.HTTP_201_CREATED
        fn_b_id = response2.json()["id"]

        # Disable function B
        disable_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{fn_b_id}/",
            data={"enabled": False},
        )
        assert disable_response.status_code == status.HTTP_200_OK

        # Create a third function
        response3 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform C",
                "type": "transformation",
                "template_id": template_slack.id,
                "enabled": True,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response3.status_code == status.HTTP_201_CREATED

        # Check current order before re-enabling
        list_response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        results = list_response.json()["results"]
        transformations = sorted(
            [f for f in results if f["type"] == "transformation"], key=lambda x: x["execution_order"] or 999
        )

        # Verify current order (B is disabled but still in the list)
        fn_orders = {f["name"]: {"order": f["execution_order"], "enabled": f["enabled"]} for f in transformations}
        assert fn_orders["Transform A"]["order"] == 1
        assert fn_orders["Transform B"]["order"] == 2 and not fn_orders["Transform B"]["enabled"]
        assert fn_orders["Transform C"]["order"] == 3

        # Now re-enable function B without specifying an execution_order
        reenable_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{fn_b_id}/",
            data={"enabled": True},
        )
        assert reenable_response.status_code == status.HTTP_200_OK

        # Check order - B should now be at the end
        list_response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        results = list_response.json()["results"]
        transformations = sorted(
            [f for f in results if f["type"] == "transformation"], key=lambda x: x["execution_order"] or 999
        )

        fn_orders = {f["name"]: f["execution_order"] for f in transformations}
        assert str(fn_orders["Transform A"]) == "1", "A should still have order 1"
        assert str(fn_orders["Transform C"]) == "3", "C should remain at order 3"
        assert str(fn_orders["Transform B"]) == "4", "B should now be at the end (order 4)"

    def test_transformation_normal_execution_order_update(self, *args):
        """Test updating execution_order for a transformation function directly."""

        # Create three transformations with consecutive orders
        response1 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform A",
                "type": "transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response1.status_code == status.HTTP_201_CREATED

        response2 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform B",
                "type": "transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response2.status_code == status.HTTP_201_CREATED
        fn_b_id = response2.json()["id"]

        response3 = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Transform C",
                "type": "transformation",
                "template_id": template_slack.id,
                "inputs": {
                    "slack_workspace": {"value": 1},
                    "channel": {"value": "#general"},
                },
            },
        )
        assert response3.status_code == status.HTTP_201_CREATED

        # Verify initial order: A=1, B=2, C=3
        list_response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        results = list_response.json()["results"]
        transformations = [f for f in results if f["type"] == "transformation"]
        assert len(transformations) == 3

        fn_orders = {f["name"]: f["execution_order"] for f in transformations}
        assert str(fn_orders["Transform A"]) == "1"
        assert str(fn_orders["Transform B"]) == "2"
        assert str(fn_orders["Transform C"]) == "3"

        # Test 1: Update B's execution_order to match A (both will have order 1)
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{fn_b_id}/",
            data={"execution_order": 1},
        )
        assert update_response.status_code == status.HTTP_200_OK

        # Check the updated orders
        list_response = self.client.get(f"/api/projects/{self.team.id}/hog_functions/")
        results = list_response.json()["results"]
        transformations = [f for f in results if f["type"] == "transformation"]

        # Order by function name for verification
        fn_orders = {f["name"]: f["execution_order"] for f in transformations}
        assert str(fn_orders["Transform A"]) == "1", "A should still have order 1"
        assert str(fn_orders["Transform B"]) == "1", "B should now have order 1"
        assert str(fn_orders["Transform C"]) == "3", "C should remain at order 3"

        # In results, B should be first because it was most recently updated
        names_in_order = [f["name"] for f in transformations]
        assert names_in_order[0] == "Transform B", "B should be first (order 1, most recently updated)"
        assert names_in_order[1] == "Transform A", "A should be second (order 1, updated earlier)"
        assert names_in_order[2] == "Transform C", "C should be last (order 3)"

    def test_create_in_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "type": "destination",
                "name": "Fetch URL With Folder",
                "hog": "fetch(inputs.url);",
                "inputs": {
                    "url": {"value": "https://example.com"},
                },
                "_create_in_folder": "Special/Hog Destinations",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        hog_function_id = response.json()["id"]

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(
            team=self.team,
            type="hog_function/destination",
            ref=str(hog_function_id),
        ).first()
        assert fs_entry is not None, "No FileSystem entry was created for this HogFunction."
        assert "Special/Hog Destinations" in fs_entry.path

    def test_hog_function_template_fk_set_on_create(self):
        """
        When creating a HogFunction with a template_id, the hog_function_template FK should be set to the latest template.
        When creating without a template_id, the FK should be null.
        """

        # Create a template in the DB
        _template = HogFunctionTemplate.objects.create(
            template_id="template-fk-test",
            sha="abcdef",
            name="FK Test Template",
            description="FK Test Template",
            code="return event",
            code_language="hog",
            inputs_schema=[],
            type="destination",
            status="alpha",
            category=[],
        )

        # Create a HogFunction with template_id
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "FK Test Function",
                "hog": "return event",
                "type": "destination",
                "template_id": "template-fk-test",
                "inputs": {},
            },
        )
        assert response.status_code == 201, response.json()
        hog_function_id = response.json()["id"]
        hog_function = HogFunction.objects.get(id=hog_function_id)
        assert hog_function.hog_function_template is not None, "FK should be set when template_id is provided"
        assert hog_function.hog_function_template.id == _template.id, "FK should point to the correct template"

        # Create a HogFunction without template_id
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "No Template FK",
                "hog": "return event",
                "type": "destination",
                "inputs": {},
            },
        )
        assert response.status_code == 201, response.json()
        hog_function_id = response.json()["id"]
        hog_function = HogFunction.objects.get(id=hog_function_id)
        assert hog_function.hog_function_template is None, "FK should be null when template_id is not provided"

    def test_hog_function_template_fk_validation_error_on_missing_template(self):
        """
        Creating a HogFunction with a template_id that does not exist in the DB should raise a validation error and not create the object.
        """
        from posthog.models.hog_functions.hog_function import HogFunction

        initial_count = HogFunction.objects.count()
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_functions/",
            data={
                "name": "Should Fail",
                "hog": "return event",
                "type": "destination",
                "template_id": "nonexistent-template-id",
                "inputs": {},
            },
        )
        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "template_id"
        assert "No template found for id 'nonexistent-template-id'" in response.json()["detail"]
        assert HogFunction.objects.count() == initial_count, "No HogFunction should be created on error"
