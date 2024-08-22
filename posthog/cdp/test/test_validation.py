import json

from inline_snapshot import snapshot

from posthog.cdp.validation import validate_inputs, validate_inputs_schema
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


def create_example_inputs_schema():
    return [
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
    ]


def create_example_inputs():
    return {
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
    }


class TestHogFunctionValidation(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_validate_inputs_schema(self):
        inputs_schema = create_example_inputs_schema()
        assert validate_inputs_schema(inputs_schema) == snapshot(
            [
                {"type": "string", "key": "url", "label": "Webhook URL", "required": True, "secret": False},
                {"type": "json", "key": "payload", "label": "JSON Payload", "required": True, "secret": False},
                {
                    "type": "choice",
                    "key": "method",
                    "label": "HTTP Method",
                    "choices": [
                        {"label": "POST", "value": "POST"},
                        {"label": "PUT", "value": "PUT"},
                        {"label": "PATCH", "value": "PATCH"},
                        {"label": "GET", "value": "GET"},
                    ],
                    "required": True,
                    "secret": False,
                },
                {"type": "dictionary", "key": "headers", "label": "Headers", "required": False, "secret": False},
            ]
        )

    def test_validate_inputs(self):
        inputs_schema = create_example_inputs_schema()
        inputs = create_example_inputs()
        assert json.loads(json.dumps(validate_inputs(inputs_schema, inputs))) == snapshot(
            {
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
                        "version": [
                            "_h",
                            32,
                            "$lib_version",
                            32,
                            "properties",
                            32,
                            "event",
                            1,
                            3,
                            32,
                            "v=",
                            2,
                            "concat",
                            2,
                        ]
                    },
                },
            }
        )

    def test_validate_inputs_creates_bytecode_for_html(self):
        # NOTE: CSS block curly brackets must be escaped beforehand
        html_with_css = '<html>\n<head>\n<style type="text/css">\n  .css \\{\n    width: 500px !important;\n  }</style>\n</head>\n\n<body>\n    <p>Hi {person.properties.email}</p>\n</body>\n</html>'

        assert json.loads(
            json.dumps(
                validate_inputs(
                    [
                        {"key": "html", "type": "string", "label": "HTML", "required": True},
                    ],
                    {
                        "html": {"value": html_with_css},
                    },
                )
            )
        ) == snapshot(
            {
                "html": {
                    "bytecode": [
                        "_h",
                        32,
                        "</p>\n</body>\n</html>",
                        32,
                        "email",
                        32,
                        "properties",
                        32,
                        "person",
                        1,
                        3,
                        32,
                        '<html>\n<head>\n<style type="text/css">\n  .css {\n    width: 500px !important;\n  }</style>\n</head>\n\n<body>\n    <p>Hi ',
                        2,
                        "concat",
                        3,
                    ],
                    "value": '<html>\n<head>\n<style type="text/css">\n  .css \\{\n    width: 500px !important;\n  }</style>\n</head>\n\n<body>\n    <p>Hi {person.properties.email}</p>\n</body>\n</html>',
                },
            }
        )
