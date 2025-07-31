from posthog.test.base import BaseTest
from posthog.caching.login_device_cache import check_and_cache_login_device


class TestLoginDeviceCache(BaseTest):
    def test_new_device_login(self):
        """Test new device login"""
        result = check_and_cache_login_device(1, "192.168.1.1", "Chrome 135.0.0 on Windows 10")
        self.assertEqual(result, True)
