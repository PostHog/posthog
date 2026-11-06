from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.integration_origins import integration_origins
from products.cdp.backend.secret_origins import secret_origins
from products.cdp.backend.templates import HOG_FUNCTION_TEMPLATES

SAMPLE_CONFIGS: dict[str, dict[str, Any]] = {"salesforce": {"instance_url": "https://acme.my.salesforce.com"}}

TEMPLATE_INTEGRATION_INPUTS = [
    (f"{template.id}_{schema['key']}", template.code, schema["key"], schema["integration"])
    for template in HOG_FUNCTION_TEMPLATES
    if template.code_language == "hog"
    for schema in template.inputs_schema
    if schema.get("type") == "integration" and schema.get("integration")
]


class TestIntegrationOrigins(SimpleTestCase):
    @parameterized.expand(
        [
            ("static", "slack", {}, frozenset({"https://slack.com"})),
            (
                "instance_from_config",
                "salesforce",
                {"instance_url": "https://acme.my.salesforce.com/"},
                frozenset({"https://acme.my.salesforce.com"}),
            ),
            ("instance_outside_its_service", "salesforce", {"instance_url": "https://evil.example.com"}, frozenset()),
            ("instance_with_a_port", "salesforce", {"instance_url": "https://a.salesforce.com:8443"}, frozenset()),
            (
                "self_hosted_instance",
                "gitlab",
                {"hostname": "https://git.example.com"},
                frozenset({"https://git.example.com"}),
            ),
            ("instance_without_tls", "gitlab", {"hostname": "http://git.example.com"}, frozenset()),
            ("unlisted_kind", "jira", {}, None),
        ]
    )
    def test_integration_origins(self, _name: str, kind: str, config: dict, expected: Optional[frozenset[str]]) -> None:
        assert integration_origins(kind, config) == expected

    @parameterized.expand(TEMPLATE_INTEGRATION_INPUTS)
    def test_template_sends_its_connection_only_to_its_service(self, _name: str, hog: str, key: str, kind: str) -> None:
        config = SAMPLE_CONFIGS.get(kind, {})
        allowed = integration_origins(kind, config)

        derived = secret_origins(hog, {key: {"value": 1}}, [], {key}, {key: config})[key]

        assert allowed is not None
        assert isinstance(derived, frozenset) and derived and derived <= allowed, derived
