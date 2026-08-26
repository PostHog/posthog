import json

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from django.test import SimpleTestCase

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
from posthog.models.integration import Integration

from products.messaging.backend.api.design_validation import validate_design

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


def validate_inputs(schema, inputs, function_type="destination", is_dwh_source=False, context_extra=None):
    serializer = MappingsSerializer(
        data={
            "inputs_schema": schema,
            "inputs": inputs,
        },
        context={"function_type": function_type, "is_dwh_source": is_dwh_source, **(context_extra or {})},
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

    def test_omitted_required_input_falls_back_to_the_schema_default(self):
        schema = [
            {"key": "url", "type": "string", "label": "Webhook URL", "required": True},
            {"key": "method", "type": "string", "label": "HTTP Method", "required": True, "default": "POST"},
        ]

        inputs = validate_inputs(schema, {"url": {"value": "https://example.com"}})

        assert inputs["method"]["value"] == "POST"

    def test_explicitly_emptied_required_input_is_still_rejected(self):
        schema = [{"key": "method", "type": "string", "label": "HTTP Method", "required": True, "default": "POST"}]

        with pytest.raises(ValidationError) as e:
            validate_inputs(schema, {"method": {"value": ""}})

        assert "This field is required." in str(e.value)

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
            ("string_input", "string", "Hey {{ person.properties.name }}"),
            (
                "email_object_input",
                "native_email",
                {
                    "to": "{{ person.properties.email }}",
                    "from": "hi@posthog.com",
                    "subject": "Hello",
                    "html": "<p>hi</p>",
                },
            ),
        ]
    )
    def test_liquid_syntax_in_hog_templated_input_names_the_expected_syntax(self, _name, item_type, value):
        # Liquid-style {{ ... }} in a hog-templated field is the dominant authoring mistake
        # behind template errors, and the transpiler's own message ("Placeholders are not
        # allowed in this context") never names it - agents bisect blind on it. The error
        # must state the expected single-curly syntax and call out Liquid.
        inputs_schema = [{"key": "field", "type": item_type, "required": True}]
        inputs = {"field": {"value": value}}

        with pytest.raises(ValidationError) as ctx:
            validate_inputs(inputs_schema, inputs)
        message = str(ctx.value.detail)
        assert "{person.properties.email}" in message
        assert "Liquid" in message

    def test_liquid_templated_input_still_accepts_liquid_syntax(self):
        inputs_schema = [{"key": "field", "type": "string", "required": True, "templating": "liquid"}]
        inputs = {"field": {"value": "Hey {{ person.properties.name }}"}}

        validated = validate_inputs(inputs_schema, inputs)
        assert validated["field"]["value"] == "Hey {{ person.properties.name }}"

    @parameterized.expand([("email",), ("native_email",)])
    def test_html_only_email_value_gets_design_wrapping_the_html(self, item_type):
        inputs_schema = [{"key": "email", "type": item_type, "required": True, "templating": "liquid"}]
        html = "<html><body><p>Hello</p></body></html>"
        value = {"from": "hi@posthog.com", "to": "a@b.com", "subject": "hi", "html": html, "text": "Hello"}

        validated = validate_inputs(inputs_schema, {"email": {"value": value}})

        result = validated["email"]["value"]
        assert result["html"] == html
        contents = result["design"]["body"]["rows"][0]["columns"][0]["contents"]
        assert len(contents) == 1
        assert contents[0]["type"] == "html"
        assert contents[0]["values"]["html"] == html
        assert validate_design(result["design"]) == []

    @parameterized.expand(
        [
            (
                "existing_design_untouched",
                {
                    "from": "hi@posthog.com",
                    "to": "a@b.com",
                    "subject": "hi",
                    "html": "<p>hi</p>",
                    "design": {"body": {"rows": []}},
                },
                {"body": {"rows": []}},
            ),
            (
                "text_only_email_gets_no_design",
                {"from": "hi@posthog.com", "to": "a@b.com", "subject": "hi", "text": "hi"},
                None,
            ),
        ]
    )
    def test_email_value_wrap_no_ops(self, _name, value, expected_design):
        inputs_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]

        validated = validate_inputs(inputs_schema, {"email": {"value": value}})

        assert validated["email"]["value"].get("design") == expected_design

    def test_html_only_email_wrap_is_deterministic(self):
        # Callers resend the same html-only value on every save; a fresh design each time would
        # register as a content change in revision and draft-diff equality checks.
        inputs_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        value = {"from": "hi@posthog.com", "to": "a@b.com", "subject": "hi", "html": "<p>Hello</p>"}

        first = validate_inputs(inputs_schema, {"email": {"value": dict(value)}})["email"]["value"]["design"]
        second = validate_inputs(inputs_schema, {"email": {"value": dict(value)}})["email"]["value"]["design"]

        assert first == second

    @parameterized.expand(
        [
            (
                "single_missing_key_keeps_the_familiar_message",
                {"to": "a@b.com", "subject": "hi", "html": "<p>hi</p>"},
                "Missing value for 'from'.",
            ),
            (
                "multiple_missing_keys_reported_at_once",
                {"to": "a@b.com"},
                "Missing values for 'from', 'subject', either 'text' or 'html'.",
            ),
            (
                "body_alternatives_named_together",
                {"from": "hi@posthog.com", "to": "a@b.com", "subject": "hi"},
                "Missing value for either 'text' or 'html'.",
            ),
        ]
    )
    def test_email_input_reports_all_missing_keys_in_one_error(self, _name, value, expected):
        # Email objects are typically authored programmatically; raising on the first absent
        # key forces a validate round trip per key, so every missing key is named at once.
        inputs_schema = [{"key": "email", "type": "native_email", "required": True}]
        inputs = {"email": {"value": value}}

        with pytest.raises(ValidationError) as ctx:
            validate_inputs(inputs_schema, inputs)
        assert expected in str(ctx.value.detail)

    @parameterized.expand(
        [
            ("email_not_a_string", {"email": 123}, "Expected string value for 'from.email'."),
            (
                "both_not_strings",
                {"email": 123, "name": ["x"]},
                "Expected string values for 'from.email', 'from.name'.",
            ),
        ]
    )
    def test_email_from_overrides_must_be_strings(self, _name, overrides, expected):
        # A non-string override saves fine without this check and then fails every send in the
        # runtime's schema parse, so the shape error must surface at authoring time instead.
        inputs_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        value = {
            "from": {"integrationId": 1, **overrides},
            "to": "a@b.com",
            "subject": "hi",
            "text": "hi",
        }

        with pytest.raises(ValidationError) as ctx:
            validate_inputs(inputs_schema, {"email": {"value": value}})
        assert expected in str(ctx.value.detail)

    def test_email_from_overrides_accept_templated_strings(self):
        inputs_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        value = {
            "from": {"integrationId": 1, "email": "{{ event.properties.sender_email }}", "name": "Community"},
            "to": "a@b.com",
            "subject": "hi",
            "text": "hi",
        }

        validated = validate_inputs(inputs_schema, {"email": {"value": value}})
        assert validated["email"]["value"]["from"] == {
            "integrationId": 1,
            "email": "{{ event.properties.sender_email }}",
            "name": "Community",
        }

    def test_email_sender_rotation_rejects_more_than_ten_senders(self):
        inputs_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        value = {
            "from": {"integrationId": 1, "integrationIds": list(range(1, 12))},
            "to": "a@b.com",
            "subject": "hi",
            "text": "hi",
        }

        with pytest.raises(ValidationError) as ctx:
            validate_inputs(inputs_schema, {"email": {"value": value}})
        assert "At most 10 email senders are allowed." in str(ctx.value.detail)

    def _create_email_integration(self, domain="posthog.com"):
        return Integration.objects.create(
            team=self.team,
            kind="email",
            config={"email": f"sender@{domain}", "name": "Sender", "domain": domain, "verified": True},
        )

    def _validate_email_from(self, from_value, existing_from=None, get_team=True, cache=None):
        inputs_schema = [{"key": "email", "type": "native_email", "required": True, "templating": "liquid"}]
        value = {"from": from_value, "to": "a@b.com", "subject": "hi", "text": "hi"}
        context_extra = {"existing_email_from": existing_from}
        if get_team:
            context_extra["get_team"] = lambda: self.team
        if cache is not None:
            context_extra["email_integration_domain_cache"] = cache
        return validate_inputs(inputs_schema, {"email": {"value": value}}, context_extra=context_extra)

    @parameterized.expand(
        [
            ("off_domain", "sales@evil.com", 'is not on the verified domain "posthog.com"'),
            ("planted_placeholder", "default@example.com", 'is not on the verified domain "posthog.com"'),
            ("not_an_email", "not-an-email", "is not a valid email address"),
            ("address_list", "a@posthog.com, b@posthog.com", "is not a valid email address"),
        ]
    )
    def test_email_literal_sender_override_rejected_at_save(self, _name, address, expected):
        # A literal override that the runtime would refuse (or silently fall back from) must be
        # rejected when the workflow is saved, while the author can still act on it.
        integration = self._create_email_integration()

        with pytest.raises(ValidationError) as ctx:
            self._validate_email_from({"integrationId": integration.id, "email": address})
        assert expected in str(ctx.value.detail)

    @parameterized.expand(
        [
            ("on_domain", "community@posthog.com"),
            ("case_insensitive", "Community@PostHog.com"),
            ("liquid_template", "{{ event.properties.sender }}"),
            ("hog_template", "{event.properties.sender}"),
            ("empty_means_integration_default", ""),
        ]
    )
    def test_email_sender_override_accepted_at_save(self, _name, address):
        integration = self._create_email_integration()

        validated = self._validate_email_from({"integrationId": integration.id, "email": address})
        assert validated["email"]["value"]["from"]["email"] == address

    def test_email_sender_override_unchanged_stored_value_is_not_revalidated(self):
        # Workflows written before June 2026 carry a placeholder address the author never typed.
        # Re-saving one of them must not fail on that stored value; only a newly written address
        # is held to the domain rule. The stored placeholders are removed by a separate backfill.
        integration = self._create_email_integration()

        self._validate_email_from(
            {"integrationId": integration.id, "email": "default@example.com"},
            existing_from={"integrationId": integration.id, "email": "default@example.com"},
        )

    def test_email_sender_override_changed_value_is_validated(self):
        integration = self._create_email_integration()

        with pytest.raises(ValidationError) as ctx:
            self._validate_email_from(
                {"integrationId": integration.id, "email": "new@evil.com"},
                existing_from={"integrationId": integration.id, "email": "old@evil.com"},
            )
        assert 'is not on the verified domain "posthog.com"' in str(ctx.value.detail)

    def test_email_sender_override_kept_address_with_changed_sender_is_validated(self):
        # Selecting a different sender re-runs the domain check even when the address is kept.
        # Grandfathering on the address alone let a sender change save an off-domain pair that
        # silently falls back at send time - the failure this validation exists to surface.
        posthog_integration = self._create_email_integration("posthog.com")
        other_integration = self._create_email_integration("example.dev")

        with pytest.raises(ValidationError) as ctx:
            self._validate_email_from(
                {"integrationId": other_integration.id, "email": "community@posthog.com"},
                existing_from={"integrationId": posthog_integration.id, "email": "community@posthog.com"},
            )
        assert 'is not on the verified domain "example.dev"' in str(ctx.value.detail)

    def test_email_sender_override_added_rotation_sender_is_validated(self):
        # Adding a rotation sender keeps the stored address, so an address-only grandfather
        # would skip the multi-sender domain loop entirely.
        posthog_integration = self._create_email_integration("posthog.com")
        other_integration = self._create_email_integration("example.dev")

        with pytest.raises(ValidationError) as ctx:
            self._validate_email_from(
                {
                    "integrationId": posthog_integration.id,
                    "integrationIds": [posthog_integration.id, other_integration.id],
                    "email": "community@posthog.com",
                },
                existing_from={"integrationId": posthog_integration.id, "email": "community@posthog.com"},
            )
        assert 'is not on the verified domain "example.dev"' in str(ctx.value.detail)

    def test_email_sender_override_grandfathers_either_live_or_draft_value(self):
        # A raw-API live save is compared against both stored variants: an address unchanged
        # from the live value must not be blocked because a divergent draft exists.
        integration = self._create_email_integration()

        self._validate_email_from(
            {"integrationId": integration.id, "email": "legacy@evil.com"},
            existing_from=[
                {"integrationId": integration.id, "email": "legacy@evil.com"},
                {"integrationId": integration.id, "email": "draft@evil.com"},
            ],
        )

    def test_email_sender_domain_lookup_is_cached_per_save(self):
        # A drip sequence validates one action at a time, so each email step re-queries the
        # same sender row unless the domain lookup shares a request-scoped cache (mirrors
        # _message_template_cache).
        integration = self._create_email_integration()
        cache: dict = {}

        self._validate_email_from({"integrationId": integration.id, "email": "a@posthog.com"}, cache=cache)
        with self.assertNumQueries(0):
            self._validate_email_from({"integrationId": integration.id, "email": "b@posthog.com"}, cache=cache)

    def test_email_sender_override_must_be_on_every_rotation_domain(self):
        # Sender rotation picks one integration per send, so a literal address that is off-domain
        # for any of them would make a fraction of sends fall back to a different sender.
        posthog_integration = self._create_email_integration("posthog.com")
        other_integration = self._create_email_integration("example.dev")

        with pytest.raises(ValidationError) as ctx:
            self._validate_email_from(
                {
                    "integrationId": posthog_integration.id,
                    "integrationIds": [posthog_integration.id, other_integration.id],
                    "email": "community@posthog.com",
                }
            )
        assert 'is not on the verified domain "example.dev"' in str(ctx.value.detail)

    @parameterized.expand(
        [
            ("no_team_in_context", False, 1),
            ("unknown_integration", True, 999999),
        ]
    )
    def test_email_sender_override_skips_when_domain_is_unresolvable(self, _name, get_team, integration_id):
        # Internal re-saves run without a request (no get_team), and an integration id that does
        # not resolve has no domain to compare against. Both must not block the save; the runtime
        # still enforces the domain at send time.
        self._validate_email_from({"integrationId": integration_id, "email": "sales@evil.com"}, get_team=get_team)

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
            # The UI sends the read-back mask as the value when a secret is left untouched. This
            # must keep the stored secret, not encrypt the mask over it.
            (
                {
                    "secret_field": {"value": "********", "secret": True},
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

    @parameterized.expand(
        [
            # Read-back mask flagged as secret, nothing stored to restore.
            ({"value": "********", "secret": True},),
            # Mask that lost its secret flag - the persistence guard must still refuse it.
            ({"value": "********"},),
        ]
    )
    def test_masked_secret_without_stored_value_is_rejected(self, input_value):
        # The mask must never be encrypted as the real credential when there is nothing to restore.
        inputs_schema = [
            {"key": "secret_field", "type": "string", "required": True, "secret": True},
        ]

        serializer = MappingsSerializer(
            data={
                "inputs_schema": inputs_schema,
                "inputs": {"secret_field": input_value},
            },
            context={"function_type": "destination", "encrypted_inputs": {}},
        )
        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

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

    # Behavioral filters compile to a ClickHouse subquery over events history, which neither
    # bytecode (per-event) nor transpiled JS (in-browser) filters can evaluate
    @parameterized.expand(
        [
            ("destination_global_properties", "destination", "properties"),
            ("site_destination_global_properties", "site_destination", "properties"),
            ("destination_event_properties", "destination", "event_properties"),
        ]
    )
    def test_validate_filters_rejects_behavioral_properties(self, _name, function_type, placement):
        behavioral_property = {
            "type": "behavioral",
            "value": "performed_event",
            "key": "$pageview",
            "event_type": "events",
            "time_value": 30,
            "time_interval": "day",
        }
        event = {"id": "$pageview", "type": "events", "name": "$pageview", "order": 0}
        if placement == "properties":
            filters = {"events": [event], "properties": [behavioral_property]}
        else:
            filters = {"events": [{**event, "properties": [behavioral_property]}]}

        serializer = HogFunctionFiltersSerializer(
            data=filters, context={**self.filters_context, "function_type": function_type}
        )
        assert not serializer.is_valid()
        assert "behavioral" in str(serializer.errors).lower()

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


class TestTaskInputTypeValidation(SimpleTestCase):
    # The task_* input types are authored programmatically (workflow API, MCP agents), so the
    # serializer is the only guard against a payload shape the tasks endpoint would reject at
    # run time - long after the workflow saved fine.
    @parameterized.expand(
        [
            ("repository_string", "task_repository", "example-org/example-repo", True),
            ("repository_not_string", "task_repository", 123, False),
            ("model_full", "task_model", {"model": "claude-sonnet-5", "reasoning_effort": "high"}, True),
            ("model_without_effort", "task_model", {"model": "claude-sonnet-5"}, True),
            ("model_not_dict", "task_model", "claude-sonnet-5", False),
            ("model_value_not_string", "task_model", {"model": 5}, False),
            ("model_key_absent", "task_model", {"reasoning_effort": "high"}, False),
            ("model_value_empty_string", "task_model", {"model": ""}, False),
            ("installations_string_list", "task_mcp_installations", ["id-1", "id-2"], True),
            ("installations_not_list", "task_mcp_installations", "id-1", False),
            ("installations_not_strings", "task_mcp_installations", [1, 2], False),
        ]
    )
    def test_task_input_value_shapes(self, _name, schema_type, value, expect_valid):
        schema = [{"key": "field", "type": schema_type, "label": "Field", "required": False}]
        inputs = {"field": {"value": value}}

        if expect_valid:
            validate_inputs(schema, inputs)
        else:
            with pytest.raises(ValidationError):
                validate_inputs(schema, inputs)
