from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.secret_reentry import filled_secret_keys, guarded_content, stored_secrets

HOG = "fetch(inputs.url, {'headers': inputs.headers})"
URL = {"key": "url", "type": "string", "label": "URL"}
HEADERS = {"key": "headers", "type": "dictionary", "label": "Headers"}
METHOD = {"key": "method", "type": "string", "label": "Method", "required": True, "default": "POST"}
TARGET = {"key": "target", "type": "string", "label": "Target", "secret": True}
CHOICE = {
    "key": "url",
    "type": "choice",
    "label": "URL",
    "choices": [
        {"label": "A", "value": "https://a.example.com"},
        {"label": "Token", "value": "{inputs.target}"},
    ],
}


def content(hog: str = HOG, inputs: Any = None, schema: Any = None, mappings: Any = None) -> dict:
    return {"hog": hog, "inputs": inputs or {}, "schema": schema or [URL, HEADERS], "mappings": mappings or []}


def guarded(save: dict) -> str:
    secret_keys = {schema["key"] for schema in save["schema"] if schema.get("secret")}
    return guarded_content(save["hog"], save["inputs"], save["schema"], save["mappings"], secret_keys)


class TestGuardedContent(SimpleTestCase):
    @parameterized.expand(
        [
            ("trailing_whitespace_in_code", content(f"{HOG}\n"), content()),
            (
                "dictionary_in_another_key_order",
                content(inputs={"headers": {"value": {"a": "1", "b": "2"}}}),
                content(inputs={"headers": {"value": {"b": "2", "a": "1"}}}),
            ),
            (
                "secret_value",
                content(inputs={"target": {"value": "old"}}, schema=[URL, TARGET]),
                content(inputs={"target": {"value": "typed again"}}, schema=[URL, TARGET]),
            ),
            (
                "server_derived_fields",
                content(inputs={"url": {"value": "{event.url}", "bytecode": ["_H", 1], "order": 0}}),
                content(inputs={"url": {"value": "{event.url}", "bytecode": ["_H", 2], "order": 1}}),
            ),
            (
                "mapping_filter_bytecode",
                content(mappings=[{"filters": {"events": [{"id": "$pageview"}], "bytecode": ["_H", 1]}}]),
                content(mappings=[{"filters": {"events": [{"id": "$pageview"}], "bytecode": ["_H", 2]}}]),
            ),
        ]
    )
    def test_a_save_that_changes_nothing_the_code_sees_is_not_a_change(
        self, _name: str, before: dict, after: dict
    ) -> None:
        assert guarded(before) == guarded(after)

    @parameterized.expand(
        [
            ("code", content(), content(f"{HOG};")),
            (
                "list_order",
                content(inputs={"url": {"value": ["https://a.example.com", "https://b.example.com"]}}),
                content(inputs={"url": {"value": ["https://b.example.com", "https://a.example.com"]}}),
            ),
            (
                "value_other_than_the_default",
                content(schema=[URL, METHOD]),
                content(inputs={"method": {"value": "GET"}}, schema=[URL, METHOD]),
            ),
            ("schema_order", content(schema=[URL, HEADERS]), content(schema=[HEADERS, URL])),
            (
                "mapping_schema_order",
                content(mappings=[{"inputs_schema": [URL, HEADERS]}]),
                content(mappings=[{"inputs_schema": [HEADERS, URL]}]),
            ),
            (
                "value_dropped_from_a_choice_list",
                content(inputs={"url": {"value": "{inputs.target}"}}, schema=[CHOICE, TARGET]),
                content(
                    inputs={"url": {"value": "{inputs.target}"}},
                    schema=[{**CHOICE, "choices": [{"label": "A", "value": "https://a.example.com"}]}, TARGET],
                ),
            ),
            (
                "dictionary_entry_named_like_a_derived_field",
                content(inputs={"headers": {"value": {"order": "1"}}}),
                content(inputs={"headers": {"value": {"order": "{inputs.target}"}}}),
            ),
            (
                "mapping_filters",
                content(mappings=[{"filters": {"events": [{"id": "$pageview"}]}}]),
                content(mappings=[{"filters": {"events": [{"id": "$autocapture"}]}}]),
            ),
            (
                "templating_left_to_the_schema",
                content(inputs={"url": {"value": "{{ event.url }}"}}, schema=[{**URL, "templating": "liquid"}]),
                content(
                    inputs={"url": {"value": "{{ event.url }}", "templating": "liquid"}},
                    schema=[{**URL, "templating": "liquid"}],
                ),
            ),
            (
                "secret_templating",
                content(inputs={"target": {"value": "x", "templating": "hog"}}, schema=[URL, TARGET]),
                content(inputs={"target": {"value": "x", "templating": "liquid"}}, schema=[URL, TARGET]),
            ),
            (
                "default_that_fills_an_empty_secret",
                content(schema=[URL, TARGET]),
                content(schema=[URL, {**TARGET, "required": True, "default": "https://evil.example.com"}]),
            ),
        ]
    )
    def test_a_save_that_changes_what_the_code_sees_is_a_change(self, _name: str, before: dict, after: dict) -> None:
        assert guarded(before) != guarded(after)


class TestFilledSecretKeys(SimpleTestCase):
    def test_only_a_secret_with_a_value_needs_entering_again(self) -> None:
        secrets = {
            "token": {"value": "secret-token"},
            "headers": {"value": {"Authorization": "secret-header"}},
            "blank": {"value": ""},
            "unset": {"value": None},
            "emptied": {"value": {}},
        }

        assert filled_secret_keys(secrets) == {"token", "headers"}

    def test_malformed_stored_inputs_hold_no_secret(self) -> None:
        assert stored_secrets(["token"], [{"key": "token", "secret": True}], None) == {}  # type: ignore[arg-type]
