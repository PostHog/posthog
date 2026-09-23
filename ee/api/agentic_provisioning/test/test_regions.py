from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from ee.api.agentic_provisioning.regions import current_region_host, region_to_host

SITE_URL = "https://app.example.test"


class TestRegions(SimpleTestCase):
    @parameterized.expand(
        [
            ("US", "https://us.posthog.com"),
            ("us", "https://us.posthog.com"),
            ("EU", "https://eu.posthog.com"),
            ("eu", "https://eu.posthog.com"),
            ("DEV", "https://app.dev.posthog.dev"),
            ("dev", "https://app.dev.posthog.dev"),
        ]
    )
    def test_region_to_host(self, region: str, expected: str) -> None:
        self.assertEqual(region_to_host(region), expected)

    @override_settings(SITE_URL=SITE_URL)
    def test_region_to_host_falls_back_to_site_url_for_an_unknown_region(self) -> None:
        self.assertEqual(region_to_host("MARS"), SITE_URL)

    @parameterized.expand(
        [
            ("US", "https://us.posthog.com"),
            ("EU", "https://eu.posthog.com"),
            ("DEV", "https://app.dev.posthog.dev"),
            (None, SITE_URL),
        ]
    )
    def test_current_region_host(self, deployment: str | None, expected: str) -> None:
        with override_settings(CLOUD_DEPLOYMENT=deployment, SITE_URL=SITE_URL):
            self.assertEqual(current_region_host(), expected)
