from django.test import SimpleTestCase, override_settings

from posthog.ph_client import get_client


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
