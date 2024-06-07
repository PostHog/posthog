import json
from unittest.mock import ANY

from rest_framework import status

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


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

    def test_generates_hog_bytecode(self):
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

    def test_generates_inputs_bytecode(self):
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

    def test_generates_filters_bytecode(self):
        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()
        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data=EXAMPLE_FULL)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["filters"] == {
            "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
            "actions": [{"id": "9", "name": "Test Action", "type": "actions", "order": 1}],
            "filter_test_accounts": True,
            "bytecode": [
                "_h",
                33,
                2,
                33,
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
                1,
                4,
                2,
            ],
        }
