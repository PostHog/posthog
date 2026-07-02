from unittest import TestCase

from posthog.settings import integrations


class TestCustomerIOSettings(TestCase):
    def test_customer_io_settings_defined_outside_ee(self):
        # The email availability checks (is_http_email_service_available) read these on every
        # preflight, including on non-EE builds where ee/settings.py is never imported. Keeping
        # them in the always-imported integrations module guards against a regression where a
        # non-EE home render hit AttributeError: 'Settings' has no attribute 'CUSTOMER_IO_API_KEY'.
        self.assertTrue(hasattr(integrations, "CUSTOMER_IO_API_KEY"))
        self.assertTrue(hasattr(integrations, "CUSTOMER_IO_API_URL"))
