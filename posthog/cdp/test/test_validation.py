import json

from inline_snapshot import snapshot

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION
from posthog.cdp.validation import InputsSchemaItemSerializer, MappingsSerializer
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


def validate_inputs(schema, inputs):
    serializer = MappingsSerializer(
        data={
            "inputs_schema": schema,
            "inputs": inputs,
        },
        context={"function_type": "destination"},
    )
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["inputs"]


def validate_inputs_schema(data):
    serializer = InputsSchemaItemSerializer(data=data, many=True)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


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
        {"key": "number", "type": "number", "label": "Number", "required": False},
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
        "number": {"value": 42},
    }


class TestHogFunctionValidation(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_validate_inputs_schema(self):
        inputs_schema = create_example_inputs_schema()
        assert validate_inputs_schema(inputs_schema) == snapshot(
            [
                {
                    "type": "string",
                    "key": "url",
                    "label": "Webhook URL",
                    "required": True,
                    "secret": False,
                    "hidden": False,
                },
                {
                    "type": "json",
                    "key": "payload",
                    "label": "JSON Payload",
                    "required": True,
                    "secret": False,
                    "hidden": False,
                },
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
                    "hidden": False,
                },
                {
                    "type": "dictionary",
                    "key": "headers",
                    "label": "Headers",
                    "required": False,
                    "secret": False,
                    "hidden": False,
                },
                {
                    "type": "number",
                    "key": "number",
                    "label": "Number",
                    "required": False,
                    "secret": False,
                    "hidden": False,
                },
            ]
        )

    def test_validate_inputs(self):
        inputs_schema = create_example_inputs_schema()
        inputs = create_example_inputs()
        assert json.loads(json.dumps(validate_inputs(inputs_schema, inputs))) == snapshot(
            {
                "url": {
                    "value": "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                    "bytecode": [
                        "_H",
                        HOGQL_BYTECODE_VERSION,
                        32,
                        "http://localhost:2080/0e02d917-563f-4050-9725-aad881b69937",
                    ],
                    "order": 0,  # Now that we have ordering, url should have some order assigned
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
                    "order": 1,
                },
                "method": {
                    "value": "POST",
                    "order": 2,
                },
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
                "number": {
                    "value": 42,
                    "order": 4,
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
                        "_H",
                        HOGQL_BYTECODE_VERSION,
                        32,
                        '<html>\n<head>\n<style type="text/css">\n  .css {\n    width: 500px !important;\n  }</style>\n</head>\n\n<body>\n    <p>Hi ',
                        32,
                        "email",
                        32,
                        "properties",
                        32,
                        "person",
                        1,
                        3,
                        32,
                        "</p>\n</body>\n</html>",
                        2,
                        "concat",
                        3,
                    ],
                    "value": '<html>\n<head>\n<style type="text/css">\n  .css \\{\n    width: 500px !important;\n  }</style>\n</head>\n\n<body>\n    <p>Hi {person.properties.email}</p>\n</body>\n</html>',
                    "order": 0,
                },
            }
        )

    # New tests for ordering
    def test_validate_inputs_with_dependencies_simple_chain(self):
        # Schema: A->B->C
        # A has no deps, B uses A, C uses B
        inputs_schema = [
            {"key": "A", "type": "string", "required": True},
            {"key": "C", "type": "string", "required": True},
            {"key": "B", "type": "string", "required": True},
        ]
        # Values: B depends on A, C depends on B
        # We'll use templates referencing inputs.A, inputs.B
        inputs = {
            "A": {"value": "A value"},
            "C": {"value": "{inputs.B} + C value"},
            "B": {"value": "{inputs.A} + B value"},
        }

        validated = validate_inputs(inputs_schema, inputs)
        # Order should be A=0, B=1, C=2
        assert validated["A"]["order"] == 0
        assert validated["B"]["order"] == 1
        assert validated["C"]["order"] == 2

    def test_validate_inputs_with_multiple_dependencies(self):
        # Schema: W, X, Y, Z
        # Z depends on W and Y
        # Y depends on X
        # X depends on W
        # So order: W=0, X=1, Y=2, Z=3
        inputs_schema = [
            {"key": "X", "type": "string", "required": True},
            {"key": "W", "type": "string", "required": True},
            {"key": "Z", "type": "string", "required": True},
            {"key": "Y", "type": "string", "required": True},
        ]
        inputs = {
            "X": {"value": "{inputs.W}_x"},
            "W": {"value": "w"},
            "Z": {"value": "{inputs.W}{inputs.Y}_z"},  # depends on W and Y
            "Y": {"value": "{inputs.X}_y"},
        }

        validated = validate_inputs(inputs_schema, inputs)
        assert validated["W"]["order"] == 0
        assert validated["X"]["order"] == 1
        assert validated["Y"]["order"] == 2
        assert validated["Z"]["order"] == 3

    def test_validate_inputs_with_no_dependencies(self):
        # All inputs have no references. Any order is fine but all should start from 0 and increment.
        inputs_schema = [
            {"key": "one", "type": "string", "required": True},
            {"key": "two", "type": "string", "required": True},
            {"key": "three", "type": "string", "required": True},
        ]
        inputs = {
            "one": {"value": "1"},
            "two": {"value": "2"},
            "three": {"value": "3"},
        }

        validated = validate_inputs(inputs_schema, inputs)
        # Should just assign order in any stable manner (likely alphabetical since no deps):
        # Typically: one=0, two=1, three=2
        # The actual order might depend on dictionary ordering, but given code, it should be alphabetical keys since we topologically sort by dependencies.
        assert validated["one"]["order"] == 0
        assert validated["two"]["order"] == 1
        assert validated["three"]["order"] == 2

    def test_validate_inputs_with_circular_dependencies(self):
        # A depends on B, B depends on A -> should fail
        inputs_schema = [
            {"key": "A", "type": "string", "required": True},
            {"key": "B", "type": "string", "required": True},
        ]

        inputs = {
            "A": {"value": "{inputs.B} + A"},
            "B": {"value": "{inputs.A} + B"},
        }

        try:
            validate_inputs(inputs_schema, inputs)
            raise AssertionError("Expected circular dependency error")
        except Exception as e:
            assert "Circular dependency" in str(e)

    def test_validate_inputs_with_extraneous_dependencies(self):
        # A depends on a non-existing input X
        # This should ignore X since it's not defined.
        # So no error, but A has no real dependencies that matter.
        inputs_schema = [
            {"key": "A", "type": "string", "required": True},
        ]
        inputs = {
            "A": {"value": "{inputs.X} + A"},
        }

        validated = validate_inputs(inputs_schema, inputs)
        # Only A is present, so A=0
        assert validated["A"]["order"] == 0

    def test_validate_inputs_no_bytcode_if_not_hog(self):
        # A depends on a non-existing input X
        # This should ignore X since it's not defined.
        # So no error, but A has no real dependencies that matter.
        inputs_schema = [
            {"key": "A", "type": "string", "required": True, "templating": False},
        ]
        inputs = {
            "A": {"value": "{inputs.X} + A"},
        }

        validated = validate_inputs(inputs_schema, inputs)
        assert validated["A"].get("bytecode") is None
        assert validated["A"].get("transpiled") is None
        assert validated["A"].get("value") == "{inputs.X} + A"

    def test_validate_inputs_with_secret_values(self):
        inputs_schema = [
            {"key": "secret_field", "type": "string", "required": True, "secret": True},
        ]

        existing_secret_inputs = {
            "secret_field": {"value": "EXISTING_SECRET_VALUE", "order": 1},
        }

        for inputs, expected_result in [
            (
                {
                    "secret_field": {},
                },
                {
                    "secret_field": {"value": "EXISTING_SECRET_VALUE"},
                },
            ),
            (
                {
                    "secret_field": {"value": "NEW_SECRET_VALUE"},
                },
                {
                    "secret_field": {"value": "NEW_SECRET_VALUE"},
                },
            ),
            (
                {
                    "secret_field": {"secret": True},
                },
                {
                    "secret_field": {"value": "EXISTING_SECRET_VALUE"},
                },
            ),
        ]:
            serializer = MappingsSerializer(
                data={
                    "inputs_schema": inputs_schema,
                    "inputs": inputs,
                },
                context={"function_type": "destination", "encrypted_inputs": existing_secret_inputs},
            )
            serializer.is_valid(raise_exception=True)
            validated = serializer.validated_data["inputs"]

            values_only = {k: {"value": v["value"]} for k, v in validated.items()}
            assert values_only == expected_result
