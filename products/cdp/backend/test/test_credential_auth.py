from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.cdp.backend.credential_auth import bind_secret_auth, url_origin, validate_auth_declarations

SECRET = {"key": "api_key", "type": "string", "secret": True}
INTEGRATION = {"key": "workspace", "type": "integration", "integration": "slack"}
URL_INPUT = {"key": "host", "type": "string"}
USER_INPUT = {"key": "user", "type": "string"}
SECRET_USER_INPUT = {"key": "user", "type": "string", "secret": True}

ORIGINS = ["https://api.example.com"]


def schema_with(item: dict[str, Any], auth: dict[str, Any], *others: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**item, "auth": auth}, *others]


class TestValidateAuthDeclarations(SimpleTestCase):
    @parameterized.expand(
        [
            ("bearer_secret", schema_with(SECRET, {"scheme": "bearer", "origins": ORIGINS})),
            (
                "header_with_prefix",
                schema_with(SECRET, {"scheme": "header", "name": "X-Api-Key", "prefix": "Token ", "origins": ORIGINS}),
            ),
            (
                "basic_with_username_input",
                schema_with(SECRET, {"scheme": "basic", "username_input": "user", "origins": ORIGINS}, USER_INPUT),
            ),
            (
                "query_opted_in",
                schema_with(SECRET, {"scheme": "query", "name": "key", "opt_in": True, "origins": ORIGINS}),
            ),
            (
                "body_opted_in",
                schema_with(SECRET, {"scheme": "body", "path": "auth.token", "opt_in": True, "origins": ORIGINS}),
            ),
            ("origin_from_input", schema_with(SECRET, {"scheme": "bearer", "origin_input": "host"}, URL_INPUT)),
            ("integration_bearer", schema_with(INTEGRATION, {"scheme": "bearer"})),
            ("integration_basic", schema_with(INTEGRATION, {"scheme": "basic", "username_field": "account_sid"})),
        ]
    )
    def test_accepts(self, _name: str, schemas: list[dict[str, Any]]) -> None:
        validate_auth_declarations(schemas)

    @parameterized.expand(
        [
            ("unknown_scheme", schema_with(SECRET, {"scheme": "cookie", "origins": ORIGINS})),
            ("query_without_opt_in", schema_with(SECRET, {"scheme": "query", "name": "key", "origins": ORIGINS})),
            ("body_without_opt_in", schema_with(SECRET, {"scheme": "body", "path": "token", "origins": ORIGINS})),
            (
                "prototype_body_path",
                schema_with(SECRET, {"scheme": "body", "path": "a.__proto__", "opt_in": True, "origins": ORIGINS}),
            ),
            ("host_header", schema_with(SECRET, {"scheme": "header", "name": "Host", "origins": ORIGINS})),
            ("public_input", schema_with(URL_INPUT, {"scheme": "bearer", "origins": ORIGINS})),
            ("secret_without_origins", schema_with(SECRET, {"scheme": "bearer"})),
            ("origin_with_path", schema_with(SECRET, {"scheme": "bearer", "origins": ["https://api.example.com/v1"]})),
            ("plain_http_origin", schema_with(SECRET, {"scheme": "bearer", "origins": ["http://api.example.com"]})),
            (
                "origin_input_is_secret",
                schema_with(SECRET, {"scheme": "bearer", "origin_input": "user"}, SECRET_USER_INPUT),
            ),
            (
                "username_input_is_secret",
                schema_with(
                    SECRET, {"scheme": "basic", "username_input": "user", "origins": ORIGINS}, SECRET_USER_INPUT
                ),
            ),
            ("integration_with_origins", schema_with(INTEGRATION, {"scheme": "bearer", "origins": ORIGINS})),
            ("unknown_key", schema_with(SECRET, {"scheme": "bearer", "origins": ORIGINS, "name": "X-Key"})),
        ]
    )
    def test_refuses(self, _name: str, schemas: list[dict[str, Any]]) -> None:
        with self.assertRaises(ValidationError):
            validate_auth_declarations(schemas)


class TestBindSecretAuth(SimpleTestCase):
    @parameterized.expand(
        [
            ("https://Self-Hosted.example.com:8443/api/v1", "https://self-hosted.example.com:8443"),
            ("https://example.com:443/", "https://example.com"),
        ]
    )
    def test_binds_the_origin_of_the_url_input(self, url: str, origin: str) -> None:
        bound = bind_secret_auth({"scheme": "bearer", "origin_input": "host"}, {"host": {"value": url}})

        assert bound == {"scheme": "bearer", "origins": [origin]}

    @parameterized.expand([("templated", "https://{inputs.region}.example.com"), ("not_a_url", "example.com")])
    def test_refuses_a_url_input_without_a_fixed_origin(self, _name: str, url: str) -> None:
        with self.assertRaises(ValidationError):
            bind_secret_auth({"scheme": "bearer", "origin_input": "host"}, {"host": {"value": url}})

    @parameterized.expand(
        [
            ("userinfo", "https://api.example.com@evil.example/"),
            ("ipv6", "https://[::1]/"),
            ("hex_ipv4", "https://0x7f.1/"),
        ]
    )
    def test_url_origin_refuses_hosts_the_worker_reads_differently(self, _name: str, url: str) -> None:
        assert url_origin(url) is None
