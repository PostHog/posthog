from unittest import TestCase

from django.core.exceptions import ImproperlyConfigured

from parameterized import parameterized

from posthog.settings.utils import assert_debug_not_in_production


class TestAssertDebugNotInProduction(TestCase):
    @parameterized.expand([("US",), ("us",), ("EU",), ("eu",), ("DEV",), ("dev",)])
    def test_raises_when_debug_enabled_on_deployed_cloud(self, cloud_deployment):
        with self.assertRaises(ImproperlyConfigured):
            assert_debug_not_in_production(debug=True, cloud_deployment=cloud_deployment, test=False)

    @parameterized.expand(
        [
            ("debug_off_on_us", False, "US", False),
            ("debug_off_on_eu", False, "EU", False),
            ("debug_off_on_dev", False, "DEV", False),
            ("debug_on_local_unset", True, None, False),
            ("debug_on_local_explicit", True, "LOCAL", False),
            # E2E runs only in automated tests and never sets DEBUG, so it is intentionally not blocked.
            ("debug_on_e2e", True, "E2E", False),
            ("debug_on_dev_but_running_tests", True, "DEV", True),
        ]
    )
    def test_does_not_raise(self, _name, debug, cloud_deployment, test):
        assert_debug_not_in_production(debug=debug, cloud_deployment=cloud_deployment, test=test)
