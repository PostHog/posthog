from typing import Any, cast

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.cdp.backend.credential_auth import validate_auth_declarations

INTEGRATION = {"key": "workspace", "type": "integration", "integration": "slack"}


class TestValidateAuthDeclarations(SimpleTestCase):
    def test_accepts_auth_on_a_connection(self) -> None:
        validate_auth_declarations([{**INTEGRATION, "auth": True}])

    @parameterized.expand(
        [
            ("secret_input", {"key": "api_key", "type": "string", "secret": True}, True),
            ("plain_input", {"key": "host", "type": "string"}, True),
            ("integration_multi", {"key": "many", "type": "integration_multi"}, True),
            ("old_scheme_object", INTEGRATION, {"scheme": "bearer"}),
            ("string", INTEGRATION, "true"),
        ]
    )
    def test_refuses(self, _name: str, item: dict[str, Any], auth: Any) -> None:
        with self.assertRaises(ValidationError) as error:
            validate_auth_declarations([{**item, "auth": auth}])
        assert str(item["key"]) in cast(dict[str, Any], error.exception.detail)["auth"]
