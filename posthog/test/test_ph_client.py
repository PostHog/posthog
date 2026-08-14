from unittest.mock import MagicMock

from django.test import SimpleTestCase, override_settings

import posthoganalytics

from posthog.ph_client import ScopedCapture, get_client


class TestAILaneOptIn(SimpleTestCase):
    def test_get_client_opts_into_ai_lane(self):
        for region in ("US", "EU"):
            client = get_client(region, send=False, enable_local_evaluation=False)
            self.assertTrue(client._use_ai_lane)
            self.assertTrue(client._enable_multimodal_capture)

    def test_module_attribute_opts_default_client_into_ai_lane(self):
        self.assertTrue(posthoganalytics._use_ai_lane)
        self.assertTrue(posthoganalytics._enable_multimodal_capture)
        client = posthoganalytics.setup()
        self.assertTrue(client._use_ai_lane)
        self.assertTrue(client._enable_multimodal_capture)


class TestScopedCaptureFlush(SimpleTestCase):
    def test_flush_waits_indefinitely_rather_than_taking_the_default_budget(self):
        # The SDK's default is a 10 second budget, and on expiry it logs and returns with items still
        # queued — indistinguishable from a drained buffer. Callers flush before writing a durable
        # "events delivered" checkpoint, so an early return there loses exactly the events the flush
        # exists to protect. Nothing else surfaces the difference, so pin the argument.
        client = MagicMock()
        ScopedCapture(client).flush()
        client.flush.assert_called_once_with(timeout_seconds=None)


class TestGetClientTestGuard(SimpleTestCase):
    def test_client_is_disabled_under_test_settings(self) -> None:
        # apps.py disables the module-level client under TEST, but a client built here
        # is a fresh instance that never sees that flag. Without its own guard, any
        # test running in cloud mode captures to the real project.
        client = get_client()
        assert client is not None
        self.assertTrue(client.disabled)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_client_stays_disabled_when_a_test_runs_in_cloud_mode(self) -> None:
        # is_cloud() is the only other guard on this path, so a test that overrides
        # CLOUD_DEPLOYMENT to exercise cloud behaviour would otherwise emit for real.
        client = get_client()
        assert client is not None
        self.assertTrue(client.disabled)

    def test_explicit_disabled_wins(self) -> None:
        client = get_client(disabled=False)
        assert client is not None
        self.assertFalse(client.disabled)

    def test_unknown_region_returns_nothing(self) -> None:
        self.assertIsNone(get_client(region="MARS"))
