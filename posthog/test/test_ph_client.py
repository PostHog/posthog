from unittest.mock import MagicMock

from django.test import SimpleTestCase

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
