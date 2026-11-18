from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cdp.backend.abuse.classifier import HogFunctionContent
from products.cdp.backend.abuse.rules import Rule, matched_rules


def content(
    hog: str = "fetch(inputs.url, {'body': event})",
    inputs: dict[str, Any] | None = None,
    mappings: list[Any] | None = None,
    filters: dict[str, Any] | None = None,
) -> HogFunctionContent:
    return HogFunctionContent(
        type="destination",
        template_id=None,
        code_modified_from_template=None,
        hog=hog,
        inputs_schema=[],
        inputs=inputs if inputs is not None else {"url": {"value": "https://hooks.example.com/orders"}},
        filters=filters or {},
        mappings=mappings or [],
        masking=None,
    )


class TestAbuseRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("public_webhook", content(), ()),
            (
                "metadata_ip_in_code",
                content(hog="fetch('http://169.254.169.254/latest/meta-data')"),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "localhost_with_port_in_input",
                content(inputs={"url": {"value": "http://localhost:8000/api"}}),
                (Rule.INTERNAL_HOST,),
            ),
            ("private_ip", content(inputs={"url": {"value": "http://10.1.2.3/hook"}}), (Rule.INTERNAL_HOST,)),
            ("ipv6_loopback", content(hog="fetch('http://[::1]:8080/')"), (Rule.INTERNAL_HOST,)),
            ("cluster_service", content(hog="fetch('http://api.default.svc.cluster.local/')"), (Rule.INTERNAL_HOST,)),
            ("internal_suffix", content(hog="fetch('https://metadata.google.internal/')"), (Rule.INTERNAL_HOST,)),
            (
                "encoded_in_a_redirect_parameter",
                content(
                    inputs={
                        "url": {"value": "https://redirect.example.com/go?to=http%3A%2F%2F169.254.169.254%2Flatest"}
                    }
                ),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "encoded_twice",
                content(
                    inputs={"url": {"value": "https://redirect.example.com/go?to=http%253A%252F%252F127.0.0.1%252F"}}
                ),
                (Rule.INTERNAL_HOST,),
            ),
            ("userinfo_trick", content(hog="fetch('http://169.254.169.254@example.com/')"), (Rule.INTERNAL_HOST,)),
            (
                "nested_input_value",
                content(inputs={"body": {"value": {"callback": ["http://192.168.0.10/x"]}}}),
                (Rule.INTERNAL_HOST,),
            ),
            (
                "request_catcher",
                content(inputs={"url": {"value": "https://webhook.site/0000-abcd"}}),
                (Rule.REQUEST_CATCHER,),
            ),
            ("tunnel_subdomain", content(hog="fetch('https://abc123.ngrok-free.app/x')"), (Rule.REQUEST_CATCHER,)),
            ("oob_domain", content(hog="fetch('http://probe.oast.fun/')"), (Rule.REQUEST_CATCHER,)),
            ("catcher_lookalike", content(inputs={"url": {"value": "https://notwebhook.site/x"}}), ()),
            ("catcher_name_as_subdomain", content(inputs={"url": {"value": "https://webhook.site.example.com/x"}}), ()),
            (
                "catcher_in_a_mapping_input",
                content(mappings=[{"name": "Orders", "inputs": {"url": {"value": "https://httpbin.org/post"}}}]),
                (Rule.REQUEST_CATCHER,),
            ),
            (
                "local_url_in_an_event_filter",
                content(
                    filters={
                        "properties": [{"key": "$current_url", "value": "http://localhost:8000/", "type": "event"}]
                    }
                ),
                (),
            ),
            ("templated_host", content(inputs={"url": {"value": "https://{inputs.host}/hook"}}), ()),
            ("oversized_input", content(inputs={"padding": {"value": "B" * 65_537}}), (Rule.OVERSIZED_INPUT,)),
            ("input_at_the_size_limit", content(inputs={"padding": {"value": "B" * 65_536}}), ()),
            (
                "oversized_mapping_input",
                content(mappings=[{"inputs": {"padding": {"value": {"nested": "B" * 70_000}}}}]),
                (Rule.OVERSIZED_INPUT,),
            ),
            (
                "several_rules",
                content(
                    hog="fetch('https://webhook.site/x'); fetch('http://127.0.0.1/')",
                    inputs={"padding": {"value": "B" * 100_000}},
                ),
                (Rule.INTERNAL_HOST, Rule.REQUEST_CATCHER, Rule.OVERSIZED_INPUT),
            ),
        ]
    )
    def test_matched_rules(self, _name: str, function: HogFunctionContent, expected: tuple[Rule, ...]) -> None:
        assert matched_rules(function) == expected
