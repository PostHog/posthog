from typing import Any, cast

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.cdp.backend.credential_auth import validate_auth_declarations

INTEGRATION = {"key": "workspace", "type": "integration", "integration": "slack"}


def schema_with(item: dict[str, Any], auth: Any) -> list[dict[str, Any]]:
    return [{**item, "auth": auth}]


class TestValidateAuthDeclarations(SimpleTestCase):
    @parameterized.expand([(scheme,) for scheme in ("bearer", "header", "basic", "query", "body")])
    def test_accepts_a_scheme_on_a_connection(self, scheme: str) -> None:
        validate_auth_declarations(schema_with(INTEGRATION, {"scheme": scheme}))

    @parameterized.expand(
        [
            ("secret_input", {"key": "api_key", "type": "string", "secret": True}, {"scheme": "bearer"}),
            ("plain_input", {"key": "host", "type": "string"}, {"scheme": "bearer"}),
            ("integration_multi", {"key": "many", "type": "integration_multi"}, {"scheme": "bearer"}),
            ("unknown_scheme", INTEGRATION, {"scheme": "cookie"}),
            ("not_an_object", INTEGRATION, "bearer"),
            ("origins", INTEGRATION, {"scheme": "bearer", "origins": ["https://attacker.example"]}),
            ("body_path", INTEGRATION, {"scheme": "body", "path": "__proto__.x", "opt_in": True}),
            ("header_name", INTEGRATION, {"scheme": "header", "name": "X-Forwarded-To"}),
        ]
    )
    def test_refuses(self, _name: str, item: dict[str, Any], auth: Any) -> None:
        with self.assertRaises(ValidationError) as error:
            validate_auth_declarations(schema_with(item, auth))
        assert str(item["key"]) in cast(dict[str, Any], error.exception.detail)["auth"]
