from django.test import SimpleTestCase

import posthoganalytics

from posthog.ph_client import get_client


class TestAILaneOptIn(SimpleTestCase):
    def test_get_client_opts_into_ai_lane(self):
        for region in ("US", "EU"):
            client = get_client(region, send=False, enable_local_evaluation=False)
            self.assertTrue(client._use_ai_lane)

    def test_module_attribute_opts_default_client_into_ai_lane(self):
        self.assertTrue(posthoganalytics._use_ai_lane)
        client = posthoganalytics.setup()
        self.assertTrue(client._use_ai_lane)
