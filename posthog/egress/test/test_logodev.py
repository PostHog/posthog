from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.logodev.limiter import consume_logodev_sync, logodev_account_key
from posthog.egress.logodev.observability import _normalize_logodev_endpoint


class TestLogoDevEgress(SimpleTestCase):
    @parameterized.expand(
        [
            ("img_brand_path", "https://img.logo.dev/linear.app?token=x", "/img/{domain}"),
            ("img_nested_brand_path", "https://img.logo.dev/some.brand.co", "/img/{domain}"),
            ("search_api", "https://search.logo.dev/api/icons?query=linear", "/api/icons"),
            ("no_url", None, "unknown"),
        ]
    )
    def test_endpoint_normalizer_bounds_cardinality(self, _name: str, url: str | None, expected: str) -> None:
        # Every brand domain minting its own endpoint label would blow up Prometheus cardinality —
        # the normalizer collapsing img paths to one label is what this domain's telemetry relies on.
        assert _normalize_logodev_endpoint(url) == expected

    def test_policy_is_registered_for_the_account_key(self) -> None:
        # consume raises for a domain with no registered policy — this catches the registration
        # side effect being lost (e.g. an import shuffle dropping the register_policy call).
        assert logodev_account_key() == "logodev:account:default"
        assert consume_logodev_sync(source="test") is True
