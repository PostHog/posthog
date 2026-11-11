import os
import runpy
from pathlib import Path

from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

from parameterized import parameterized

from posthog.ip_restrictions import get_restriction_client_ip
from posthog.settings import base_variables
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


class TestTrustedProxyDefaults(TestCase):
    @parameterized.expand(
        [
            ("local_development", True, False, None, "127.0.0.1", "127.0.0.1,::1", "198.51.100.7"),
            ("local_ipv6", True, False, None, "::1", "127.0.0.1,::1", "198.51.100.7"),
            ("untrusted_peer", True, False, None, "10.0.0.5", "127.0.0.1,::1", None),
            ("production", False, False, None, "127.0.0.1", None, None),
            ("test", True, True, None, "127.0.0.1", None, None),
            ("explicit_override", True, False, "10.0.0.5", "127.0.0.1", "10.0.0.5", None),
            ("explicit_empty", True, False, "", "127.0.0.1", "", None),
        ]
    )
    def test_trusted_proxy_defaults(
        self,
        _name: str,
        debug: bool,
        test: bool,
        configured: str | None,
        peer: str,
        expected: str | None,
        expected_ip: str | None,
    ) -> None:
        with (
            patch.object(base_variables, "DEBUG", debug),
            patch.object(base_variables, "TEST", test),
            patch.dict(os.environ, {"SECRET_KEY": "test-proxy-defaults-secret"}),
        ):
            os.environ.pop("TRUSTED_PROXIES", None)
            if configured is not None:
                os.environ["TRUSTED_PROXIES"] = configured
            settings = runpy.run_path(str(Path(base_variables.__file__).with_name("access.py")))

        self.assertEqual(settings["TRUSTED_PROXIES"], expected)
        request = RequestFactory().get("/", REMOTE_ADDR=peer, HTTP_X_FORWARDED_FOR="198.51.100.7")
        with override_settings(
            USE_X_FORWARDED_HOST=True, TRUST_ALL_PROXIES=False, TRUSTED_PROXIES=settings["TRUSTED_PROXIES"]
        ):
            self.assertEqual(get_restriction_client_ip(request), expected_ip)
