import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.hogql import ast

from posthog.cdp.validation import (
    HogFunctionFiltersSerializer,
    InputsSchemaItemSerializer,
    MappingsSerializer,
    RecordAliasRewriter,
    compile_hog,
    generate_template_bytecode,
)

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


def validate_inputs(schema, inputs, function_type="destination", is_dwh_source=False):
    serializer = MappingsSerializer(
        data={
            "inputs_schema": schema,
            "inputs": inputs,
        },
        context={"function_type": function_type, "is_dwh_source": is_dwh_source},
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
    filters_context: dict = {}

    def setUp(self):
        super().setUp()
        self.filters_context = {"function_type": "destination", "get_team": lambda: self.team}

    def test_validate_inputs_schema(self):
        inputs_schema = create_example_inputs_schema()
        assert validate_inputs_schema(inputs_schema) == [
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

    def test_validate_inputs(self):
        inputs_schema = create_example_inputs_schema()
        inputs = create_example_inputs()
        assert json.loads(json.dumps(validate_inputs(inputs_schema, inputs))) == {
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
        ) == {
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

    @parameterized.expand(
        [
            ("person", "{person?.id}"),
            ("groups", "{groups.organization.id}"),
            ("source", "{source.name}"),
            ("multiple", "{person?.id} {groups.organization.id}"),
        ]
    )
    def test_validate_transformation_inputs_rejects_unavailable_global(self, _name: str, value: str):
        # Transformations only have access to project, event, and inputs at runtime
        # (HogTransformerService.createInvocationGlobals). Referencing other globals
        # must be caught at validation time so we don't crash the realtime ingestion
        # worker with a "Global variable not found" error from the Hog VM.
        inputs_schema = [{"key": "payload", "type": "string", "required": True}]
        inputs = {"payload": {"value": value}}

        with self.assertRaises(ValidationError) as ctx:
            validate_inputs(inputs_schema, inputs, function_type="transformation")

        assert "transformation" in str(ctx.exception).lower()

    def test_validate_transformation_inputs_allows_event_project_inputs(self):
        inputs_schema = [
            {"key": "first", "type": "string", "required": True},
            {"key": "second", "type": "string", "required": True},
        ]
        inputs = {
            "first": {"value": "hello {event.distinct_id} from {project.name}"},
            "second": {"value": "{inputs.first}!"},
        }

        validated = validate_inputs(inputs_schema, inputs, function_type="transformation")
        assert validated["first"]["bytecode"] is not None
        assert validated["second"]["bytecode"] is not None

    def test_validate_transformation_inputs_allows_stl_and_runtime_functions(self):
        # STL functions (e.g. now) and transformation runtime helpers (e.g. geoipLookup)
        # are valid root identifiers because the Hog VM falls back to STL/runtime lookups
        # when a global isn't found.
        inputs_schema = [
            {"key": "ts", "type": "string", "required": True},
            {"key": "geo", "type": "string", "required": True},
        ]
        inputs = {
            "ts": {"value": "{now()}"},
            "geo": {"value": "{geoipLookup(event.properties.$ip)}"},
        }

        validated = validate_inputs(inputs_schema, inputs, function_type="transformation")
        assert validated["ts"]["bytecode"] is not None
        assert validated["geo"]["bytecode"] is not None

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

    def test_validate_filters_builds_bytecode(self):
        filters = {
            "properties": [{"key": "email", "value": ["test@posthog.com"], "operator": "exact", "type": "person"}],
            "events": [{"id": "$pageview", "type": "events", "name": "$pageview", "order": 0}],
        }

        serializer = HogFunctionFiltersSerializer(data=filters, context=self.filters_context)
        serializer.is_valid(raise_exception=True)
        value = json.loads(json.dumps(serializer.validated_data))
        assert value == {
            "source": "events",
            "events": [{"id": "$pageview", "type": "events", "name": "$pageview", "order": 0}],
            "properties": [{"key": "email", "value": ["test@posthog.com"], "operator": "exact", "type": "person"}],
            "bytecode": [
                "_H",
                1,
                32,
                "test@posthog.com",
                32,
                "email",
                32,
                "properties",
                32,
                "person",
                1,
                3,
                11,
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
        }

    def test_validate_filters_person_updates_only_allows_properties(self):
        filters = {
            "source": "person-updates",
            "properties": [{"key": "email", "value": ["test@posthog.com"], "operator": "exact", "type": "person"}],
            "events": [{"id": "$pageview", "type": "events", "name": "$pageview", "order": 0}],
        }

        serializer = HogFunctionFiltersSerializer(data=filters, context=self.filters_context)
        serializer.is_valid(raise_exception=True)
        value = json.loads(json.dumps(serializer.validated_data))
        assert value == {
            "source": "person-updates",
            "properties": [{"key": "email", "value": ["test@posthog.com"], "operator": "exact", "type": "person"}],
            "bytecode": ["_H", 1, 32, "test@posthog.com", 32, "email", 32, "properties", 32, "person", 1, 3, 11],
        }

    @parameterized.expand(
        [
            ("valid_dotted", "{person.properties.email}", False),
            ("valid_bracket", "{person.properties['self-serve']}", False),
            ("hyphenated_single", "{person.properties.self-serve}", True),
            ("hyphenated_multi", "{event.properties.multi-word-name}", True),
            ("subtraction_with_spaces", "{event.properties.count - total}", False),
            ("subtraction_field_minus_field", "{event.properties.amount - event.properties.discount}", False),
        ]
    )
    def test_hyphenated_property_detection(self, _name, template, should_error):
        inputs_schema = [{"key": "msg", "type": "string", "required": True}]
        inputs = {"msg": {"value": template}}

        if should_error:
            with self.assertRaises(ValidationError) as ctx:
                validate_inputs(inputs_schema, inputs)
            error_msg = str(ctx.exception)
            assert "Hyphens are not supported" in error_msg
            assert "bracket notation" in error_msg
        else:
            validate_inputs(inputs_schema, inputs)

    @parameterized.expand(
        [
            ("simple", "{record.name}", "{event.properties.name}"),
            ("nested", "{record.address.city}", "{event.properties.address.city}"),
            ("bare", "{record}", "{event.properties}"),
            ("alongside_event", "{concat(record.id, event.event)}", "{concat(event.properties.id, event.event)}"),
            ("bracket", "{record['self-serve']}", "{event.properties['self-serve']}"),
        ]
    )
    def test_record_alias_rewritten_for_dwh_source(self, _name, template, equivalent):
        # With a warehouse source, `{record.x}` compiles identically to `{event.properties.x}`.
        rewritten = generate_template_bytecode(template, set(), function_type="destination", is_dwh_source=True)
        expected = generate_template_bytecode(equivalent, set(), function_type="destination", is_dwh_source=False)
        assert rewritten == expected

    def test_record_alias_not_rewritten_without_dwh_source(self):
        # Without a warehouse source, `record` is left untouched (compiles like any other global).
        untouched = generate_template_bytecode("{record.name}", set(), function_type="destination", is_dwh_source=False)
        rewritten = generate_template_bytecode("{record.name}", set(), function_type="destination", is_dwh_source=True)
        assert untouched != rewritten

    def test_record_alias_rewriter_only_touches_record_fields(self):
        # AST-level: a `record` field is rewritten; a non-record field and a same-named string
        # constant are structurally immune (the rewriter only visits ast.Field chains).
        record_field = ast.Field(chain=["record", "id"])
        other_field = ast.Field(chain=["event", "properties", "id"])
        literal = ast.Constant(value="record.name")
        node = ast.Call(name="concat", args=[record_field, other_field, literal])

        RecordAliasRewriter().visit(node)

        assert record_field.chain == ["event", "properties", "id"]
        assert other_field.chain == ["event", "properties", "id"]
        assert literal.value == "record.name"

    def test_record_alias_rewritten_through_inputs_serializer(self):
        inputs_schema = [{"key": "msg", "type": "string", "required": True}]
        inputs = {"msg": {"value": "{record.id}"}}
        validated = validate_inputs(inputs_schema, inputs, is_dwh_source=True)
        expected = generate_template_bytecode("{event.properties.id}", set())
        assert validated["msg"]["bytecode"] == expected

    def test_validate_boolean_input_with_bool_value(self):
        inputs_schema = [{"key": "opt_out", "type": "boolean", "required": False}]
        inputs = {"opt_out": {"value": True}}
        validated = validate_inputs(inputs_schema, inputs)
        assert validated["opt_out"]["value"] is True

    def test_validate_boolean_input_with_false_value(self):
        inputs_schema = [{"key": "opt_out", "type": "boolean", "required": False}]
        inputs = {"opt_out": {"value": False}}
        validated = validate_inputs(inputs_schema, inputs)
        # False is falsy so it skips transpilation, value should still be preserved
        assert validated["opt_out"]["value"] is False

    def test_validate_boolean_input_with_template_string(self):
        inputs_schema = [{"key": "opt_out", "type": "boolean", "required": False}]
        inputs = {"opt_out": {"value": "{event.properties.opt_out}"}}
        validated = validate_inputs(inputs_schema, inputs)
        assert validated["opt_out"]["value"] == "{event.properties.opt_out}"
        assert "bytecode" in validated["opt_out"]

    def test_validate_boolean_input_rejects_invalid_type(self):
        inputs_schema = [{"key": "opt_out", "type": "boolean", "required": True}]
        inputs = {"opt_out": {"value": 42}}
        with self.assertRaises(ValidationError) as ctx:
            validate_inputs(inputs_schema, inputs)
        assert "boolean or a template string" in str(ctx.exception)

    def test_validate_boolean_input_rejects_liquid_templating(self):
        inputs_schema = [{"key": "opt_out", "type": "boolean", "required": False}]
        inputs = {"opt_out": {"value": "{{ event.properties.opt_out }}", "templating": "liquid"}}
        with self.assertRaises(ValidationError) as ctx:
            validate_inputs(inputs_schema, inputs)
        assert "Liquid templating is not supported for boolean fields" in str(ctx.exception)

    def test_validate_boolean_input_allows_hog_templating(self):
        inputs_schema = [{"key": "opt_out", "type": "boolean", "required": False}]
        inputs = {"opt_out": {"value": "{event.properties.opt_out}", "templating": "hog"}}
        validated = validate_inputs(inputs_schema, inputs)
        assert validated["opt_out"]["value"] == "{event.properties.opt_out}"
        assert "bytecode" in validated["opt_out"]

    @parameterized.expand(
        [
            ("valid_code", "let x := person.properties.email", False),
            ("hyphenated_code", "let x := person.properties.self-serve", True),
            ("subtraction_code", "let x := event.properties.count - total", False),
        ]
    )
    def test_hyphenated_property_detection_in_hog(self, _name, hog_code, should_error):
        if should_error:
            with self.assertRaises(ValidationError) as ctx:
                compile_hog(hog_code, "destination")
            error_msg = str(ctx.exception)
            assert "Hyphens are not supported" in error_msg
            assert "bracket notation" in error_msg
        else:
            compile_hog(hog_code, "destination")

    def test_non_failure_status_codes_schema_type_is_valid(self):
        inputs_schema = [
            {
                "key": "non_failure_status_codes",
                "type": "non_failure_status_codes",
                "label": "Ignored response codes",
                "required": False,
            }
        ]
        validated = validate_inputs_schema(inputs_schema)
        assert validated[0]["type"] == "non_failure_status_codes"
        assert validated[0]["key"] == "non_failure_status_codes"

    @parameterized.expand(
        [
            ("exact_numbers", [400, 429]),
            ("wildcards", ["4xx", "5xx"]),
            ("mixed", ["4xx", 500]),
            ("single_number", [400]),
            ("single_wildcard", ["4xx"]),
            ("empty_list", []),
        ]
    )
    def test_validate_non_failure_status_codes_accepts_valid_values(self, _name, value):
        inputs_schema = [{"key": "non_failure_status_codes", "type": "non_failure_status_codes", "required": False}]
        inputs = {"non_failure_status_codes": {"value": value}}
        validated = validate_inputs(inputs_schema, inputs)
        # Empty list short-circuits (falsy value path), but anything truthy round-trips intact
        if value:
            assert validated["non_failure_status_codes"]["value"] == value

    @parameterized.expand(
        [
            ("non_list_string", "4xx"),
            ("non_list_number", 400),
            ("non_list_dict", {"foo": "bar"}),
            ("invalid_wildcard_9xx", ["9xx"]),
            ("informational_wildcard_1xx", ["1xx"]),
            ("success_wildcard_2xx", ["2xx"]),
            ("redirect_wildcard_3xx", ["3xx"]),
            ("invalid_string", ["foo"]),
            ("out_of_range_low_negative", [-1]),
            ("out_of_range_low_below_400", [200]),
            ("out_of_range_low_399", [399]),
            ("out_of_range_high", [1000]),
            ("mixed_invalid", [400, "9xx"]),
            ("mixed_with_2xx", [500, "2xx"]),
            ("float_value", [400.5]),
            ("bool_value", [True]),
        ]
    )
    def test_validate_non_failure_status_codes_rejects_invalid_values(self, _name, value):
        inputs_schema = [{"key": "non_failure_status_codes", "type": "non_failure_status_codes", "required": False}]
        inputs = {"non_failure_status_codes": {"value": value}}
        with self.assertRaises(ValidationError):
            validate_inputs(inputs_schema, inputs)

    def test_posthog_ticket_tags_schema_type_is_valid(self):
        inputs_schema = [
            {
                "key": "tags",
                "type": "posthog_ticket_tags",
                "label": "Tags",
                "required": False,
            }
        ]
        validated = validate_inputs_schema(inputs_schema)
        assert validated[0]["type"] == "posthog_ticket_tags"
        assert validated[0]["key"] == "tags"

    def test_customer_analytics_account_properties_compiles_dict_values_to_bytecode(self):
        # Without the opt-in into transpilation, the dict values ship without bytecode and the
        # Node runtime sets the literal placeholder string instead of the interpolated value.
        inputs_schema = [{"key": "properties", "type": "customer_analytics_account_properties", "required": True}]
        inputs = {"properties": {"value": {"Plan tier": "{event.properties.plan}", "MRR": "5000"}}}

        validated = validate_inputs(inputs_schema, inputs)

        assert validated["properties"].get("bytecode") is not None

    def test_customer_analytics_account_relationships_validates_assignment_dict(self):
        # Guards the type's registration in InputsSchemaItemSerializer's ChoiceField —
        # without it, publishing a workflow with the relationships node 400s.
        inputs_schema = [{"key": "relationships", "type": "customer_analytics_account_relationships", "required": True}]
        inputs = {"relationships": {"value": {"0197f9f0-1111-0000-0000-000000000000": {"type": "user", "id": 42}}}}

        validated = validate_inputs(inputs_schema, inputs)

        assert validated["relationships"].get("bytecode") is not None

    @parameterized.expand(
        [
            # Reproduces the original user report: a mixed literal prefix plus a workflow variable.
            ("template_workflow_variable", ["zendesk/{variables.zendesk_ticketid}"]),
            # Pure event-property substitution.
            ("template_event_property", ["{event.properties.region}"]),
            # Literal-only list still gets per-element bytecode — back-compat path.
            ("literal_only", ["top_20"]),
            # Mix of literal and templated tags in a single list.
            ("mixed_literal_and_templated", ["plan_enterprise", "{event.properties.region}"]),
        ]
    )
    def test_posthog_ticket_tags_compiles_per_element_bytecode(self, _name, value):
        # Regression guard for the InputsItemSerializer opt-in. Before posthog_ticket_tags
        # was added to the list of types that go through generate_template_bytecode, list
        # values shipped without a `bytecode` field, so the Node runtime had nothing to
        # interpolate against and tags ended up containing the literal placeholder text
        # (e.g. a tag literally named `zendesk/{variables.zendesk_ticketid}`).
        inputs_schema = [{"key": "tags", "type": "posthog_ticket_tags", "required": False}]
        inputs = {"tags": {"value": value}}
        validated = validate_inputs(inputs_schema, inputs)

        bytecode = validated["tags"].get("bytecode")
        assert bytecode is not None, "tags input must have bytecode after the opt-in"
        assert isinstance(bytecode, list), "list values compile to a list of per-element bytecode"
        assert len(bytecode) == len(value), "one bytecode entry per tag element"
        for entry in bytecode:
            assert isinstance(entry, list) and entry[:2] == ["_H", HOGQL_BYTECODE_VERSION], (
                "each element is itself a Hog bytecode array"
            )
        # The original value round-trips so the UI can still render the templated source string.
        assert validated["tags"]["value"] == value
