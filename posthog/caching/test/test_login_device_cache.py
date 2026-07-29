from django.test import SimpleTestCase

from posthog.caching.login_device_cache import check_and_cache_login_device
from posthog.redis import get_client


class TestLoginDeviceCache(SimpleTestCase):
    def setUp(self):
        super().setUp()
        redis_client = get_client()
        keys = redis_client.keys("login_device:*")
        if keys:
            redis_client.delete(*keys)

    def test_new_device_login(self):
        result = check_and_cache_login_device(11, "Canada", "chrome|windows|pc")
        self.assertEqual(result, True)

    def test_same_user_same_device(self):
        first_result = check_and_cache_login_device(23, "Canada", "chrome|windows|pc")
        self.assertEqual(first_result, True)

        second_result = check_and_cache_login_device(23, "Canada", "chrome|windows|pc")
        self.assertEqual(second_result, False)

    def test_same_user_different_device(self):
        result = check_and_cache_login_device(45, "Canada", "chrome|windows|pc")
        self.assertEqual(result, True)

        result = check_and_cache_login_device(45, "France", "chrome|mac os x|pc")
        self.assertEqual(result, True)

    def test_different_users_same_device(self):
        result1 = check_and_cache_login_device(100, "Canada", "firefox|mac os x|pc")
        self.assertEqual(result1, True)

        # Same device but a different user, so still "new"
        result2 = check_and_cache_login_device(200, "Canada", "firefox|mac os x|pc")
        self.assertEqual(result2, True)

        result3 = check_and_cache_login_device(100, "Canada", "firefox|mac os x|pc")
        self.assertEqual(result3, False)

    def test_device_cached_under_legacy_fingerprint_is_not_new(self):
        # Entries written before the fingerprint dropped version numbers must still count as known,
        # otherwise every user gets alerted once when the new fingerprint misses their cached entry.
        legacy = "Chrome 135.0.0 on Windows 10"
        self.assertEqual(check_and_cache_login_device(300, "Canada", legacy), True)

        self.assertEqual(
            check_and_cache_login_device(300, "Canada", "chrome|windows|pc", legacy_short_user_agent=legacy), False
        )
        # And the device is now cached under the new fingerprint, so the legacy key can age out
        self.assertEqual(check_and_cache_login_device(300, "Canada", "chrome|windows|pc"), False)
