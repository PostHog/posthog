import unittest
from unittest import mock

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.cloud_utils import is_cloud, is_hobby, is_hobby_url
from posthog.run_mode import RunMode, derive_run_mode, run_mode


class TestDeriveRunMode(unittest.TestCase):
    @parameterized.expand(
        [
            ("US", False, RunMode.CLOUD_US),
            ("EU", False, RunMode.CLOUD_EU),
            ("DEV", False, RunMode.CLOUD_DEV),
            ("E2E", True, RunMode.E2E),
            ("LOCAL", False, RunMode.LOCAL),
            ("us", False, RunMode.CLOUD_US),
            (None, True, RunMode.LOCAL),
            (None, False, RunMode.HOBBY),
            ("", False, RunMode.HOBBY),
            ("PROD", False, RunMode.HOBBY),
        ]
    )
    def test_derives_mode(self, cloud_deployment: str | None, debug: bool, expected: RunMode) -> None:
        self.assertIs(derive_run_mode(cloud_deployment, debug), expected)

    @parameterized.expand(
        [
            (RunMode.CLOUD_US, True, True, True, False, "US"),
            (RunMode.CLOUD_EU, True, True, True, False, "EU"),
            (RunMode.CLOUD_DEV, False, True, True, False, "DEV"),
            (RunMode.E2E, False, False, True, False, None),
            (RunMode.LOCAL, False, False, False, False, None),
            (RunMode.HOBBY, False, False, False, True, None),
        ]
    )
    def test_predicates(
        self,
        mode: RunMode,
        is_prod_cloud: bool,
        is_deployed_cloud: bool,
        is_cloud: bool,
        is_hobby: bool,
        region: str | None,
    ) -> None:
        self.assertEqual(mode.is_prod_cloud, is_prod_cloud)
        self.assertEqual(mode.is_deployed_cloud, is_deployed_cloud)
        self.assertEqual(mode.is_cloud, is_cloud)
        self.assertEqual(mode.is_hobby, is_hobby)
        self.assertEqual(mode.region, region)

    def test_reads_settings_on_every_call(self) -> None:
        with mock.patch("posthog.settings.CLOUD_DEPLOYMENT", "EU"):
            self.assertIs(run_mode(), RunMode.CLOUD_EU)
        with mock.patch("posthog.settings.CLOUD_DEPLOYMENT", "US"):
            self.assertIs(run_mode(), RunMode.CLOUD_US)


class TestCloudUtilsRunMode(SimpleTestCase):
    @parameterized.expand(
        [
            ("US", False, True, False),
            ("EU", False, True, False),
            ("DEV", False, True, False),
            ("E2E", False, True, False),
            (None, True, False, False),
            (None, False, False, True),
        ]
    )
    def test_honors_override_settings(
        self, cloud_deployment: str | None, debug: bool, cloud: bool, hobby: bool
    ) -> None:
        with override_settings(CLOUD_DEPLOYMENT=cloud_deployment, DEBUG=debug):
            self.assertEqual(is_cloud(), cloud)
            self.assertEqual(is_hobby(), hobby)

    @parameterized.expand(
        [
            ("cloud", "https://eu.posthog.com/project/1", False),
            ("cloud_subdomain", "https://app.posthog.com/project/1", False),
            ("deployed_dev", "https://app.dev.posthog.dev/project/1", False),
            ("localhost", "http://localhost:8010/project/1", False),
            ("ipv4_loopback", "http://127.0.0.1:8010/project/1", False),
            ("ipv6_loopback", "http://[::1]:8010/project/1", False),
            ("hobby", "https://posthog.example.com/project/1", True),
            ("similar_domain", "https://notposthog.com/project/1", True),
            # Browsers can report a trailing-dot host (`localhost.`, `us.posthog.com.`); it must
            # not defeat the localhost, loopback, and Cloud-domain checks.
            ("cloud_trailing_dot", "https://eu.posthog.com./project/1", False),
            ("deployed_dev_trailing_dot", "https://app.dev.posthog.dev./project/1", False),
            ("localhost_trailing_dot", "http://localhost.:8010/project/1", False),
            ("ipv4_loopback_trailing_dot", "http://127.0.0.1./project/1", False),
            ("missing", None, False),
            ("malformed", "https://[", False),
            # Chrome reports `about` as the document URL for a violation inside an `about:blank`
            # frame. The report is valid but names no origin, so it must not be treated as hobby.
            ("about_blank_frame", "about", False),
        ]
    )
    def test_identifies_hobby_url(self, _name: str, url: str | None, expected: bool) -> None:
        self.assertEqual(is_hobby_url(url), expected)
