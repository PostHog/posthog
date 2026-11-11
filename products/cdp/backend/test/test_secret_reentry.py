from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.secret_reentry import filled_secret_keys, guarded_content, stored_secrets

HOG = "fetch(inputs.url, {'headers': inputs.headers})"
URL = {"key": "url", "type": "string", "label": "URL"}
HEADERS = {"key": "headers", "type": "dictionary", "label": "Headers"}
METHOD = {"key": "method", "type": "string", "label": "Method", "required": True, "default": "POST"}


def content(hog: str = HOG, inputs: Any = None, schema: Any = None) -> dict:
    return {"hog": hog, "inputs": inputs or {}, "schema": schema or [URL, HEADERS]}


def guarded(save: dict) -> tuple:
    return guarded_content(save["hog"], save["inputs"], save["schema"], [], set())


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
                "default_filled_in_for_a_missing_required_input",
                content(schema=[URL, METHOD]),
                content(inputs={"method": {"value": "POST"}}, schema=[URL, METHOD]),
            ),
            (
                "default_filled_in_with_the_schema_templating",
                content(schema=[URL, {**METHOD, "templating": "liquid"}]),
                content(
                    inputs={"method": {"value": "POST", "templating": "liquid"}},
                    schema=[URL, {**METHOD, "templating": "liquid"}],
                ),
            ),
            ("malformed_stored_inputs", content(inputs=["url"]), content()),
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
