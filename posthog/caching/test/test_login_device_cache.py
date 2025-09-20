from posthog.test.base import BaseTest

from posthog.caching.login_device_cache import check_and_cache_login_device
from posthog.redis import get_client


class TestLoginDeviceCache(BaseTest):
    def setUp(self):
        """Clean up login device cache keys before each test"""
        super().setUp()
        redis_client = get_client()
        keys = redis_client.keys("login_device:*")
        if keys:
            redis_client.delete(*keys)

    def test_new_device_login(self):
        """Test new device login"""
        result = check_and_cache_login_device(11, "192.168.1.1", "Chrome 135.0.0 on Windows 10")
        self.assertEqual(result, True)

    def test_same_user_same_device(self):
        """Test login with the same device from the same user"""
        user_id = 23
        ip = "10.0.0.1"
        user_agent = "Chrome 135.0.0 on Windows 10"

        # First login - new device
        first_result = check_and_cache_login_device(user_id, ip, user_agent)
        self.assertEqual(first_result, True)

        # Second login - existing device
        second_result = check_and_cache_login_device(user_id, ip, user_agent)
        self.assertEqual(second_result, False)

    def test_same_user_different_device(self):
        """Test login with the same user from different devices"""
        result = check_and_cache_login_device(45, "192.168.1.1", "Chrome 135.0.0 on Windows 10")
        self.assertEqual(result, True)

        result = check_and_cache_login_device(45, "192.168.1.2", "Chrome 135.0.0 on Mac OS X 10.15")
        self.assertEqual(result, True)

    def test_different_users_same_device(self):
        """Test same device with Firefox on macOS for different users"""
        ip = "172.16.0.1"
        user_agent = "Firefox 131.0 on Mac OS X 10.15"

        # User 1 - new device
        result1 = check_and_cache_login_device(100, ip, user_agent)
        self.assertEqual(result1, True)

        # User 2 - same device but different user, so still "new"
        result2 = check_and_cache_login_device(200, ip, user_agent)
        self.assertEqual(result2, True)

        # User 1 again - now existing
        result3 = check_and_cache_login_device(100, ip, user_agent)
        self.assertEqual(result3, False)

    def test_missing_user_agent(self):
        """Test behavior when user agent is empty"""
        result1 = check_and_cache_login_device(111, "192.168.1.200", "")
        self.assertEqual(result1, True)

        result2 = check_and_cache_login_device(111, "192.168.1.200", "")
        self.assertEqual(result2, False)
