from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

import posthoganalytics
from parameterized import parameterized

from posthog.clickhouse.query_tagging import tags_context
from posthog.ph_client import ScopedCapture, filter_scout_experiment_capture, get_client, ph_scoped_capture


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


class TestPrivateScoutCapture(SimpleTestCase):
    def test_module_filter_matches_deployment_setting(self) -> None:
        with patch.multiple(
            posthoganalytics,
            default_client=None,
            disabled=False,
            send=False,
            enable_local_evaluation=False,
            enable_exception_autocapture=False,
        ):
            client = posthoganalytics.setup()
            assert client is not None
            try:
                self.assertIs(
                    client.before_send,
                    filter_scout_experiment_capture if settings.SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE else None,
                )
                with tags_context(is_scout_experiment=True):
                    captured = client.capture(
                        "query executed", distinct_id="synthetic", properties={"is_scout_experiment": False}
                    )
                    self.assertEqual(captured is None, settings.SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE)
                with tags_context(is_scout_experiment=False):
                    self.assertIsNotNone(
                        client.capture(
                            "query executed", distinct_id="synthetic", properties={"is_scout_experiment": True}
                        )
                    )
            finally:
                client.shutdown()

    @parameterized.expand([("US", False), ("EU", False), ("US", True), ("EU", True)])
    @override_settings(SCOUT_LIVE_TRIALS_ENABLED=False)
    def test_regional_capture_respects_private_deployment_setting(self, region: str, private_capture: bool) -> None:
        before_send = MagicMock(side_effect=lambda message: message)
        with override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=private_capture):
            client = get_client(
                region, disabled=False, send=False, enable_local_evaluation=False, before_send=before_send
            )
        assert client is not None
        try:
            if not private_capture:
                self.assertIs(client.before_send, before_send)
            with tags_context(is_scout_experiment=True):
                captured = client.capture("query executed", distinct_id="synthetic")
            self.assertEqual(captured is None, private_capture)
            self.assertEqual(before_send.call_count, 0 if private_capture else 1)
            with tags_context(is_scout_experiment=False):
                self.assertIsNotNone(client.capture("query executed", distinct_id="synthetic"))
            self.assertEqual(before_send.call_count, 1 if private_capture else 2)
        finally:
            client.shutdown()

    @override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False)
    def test_unconfigured_regional_client_has_no_capture_filter(self) -> None:
        client = get_client(send=False, enable_local_evaluation=False)
        assert client is not None
        try:
            self.assertIsNone(client.before_send)
        finally:
            client.shutdown()


class TestScopedCaptureFlush(SimpleTestCase):
    def test_flush_waits_indefinitely_rather_than_taking_the_default_budget(self):
        # The SDK's default is a 10 second budget, and on expiry it logs and returns with items still
        # queued — indistinguishable from a drained buffer. Callers flush before writing a durable
        # "events delivered" checkpoint, so an early return there loses exactly the events the flush
        # exists to protect. Nothing else surfaces the difference, so pin the argument.
        client = MagicMock()
        ScopedCapture(client).flush()
        client.flush.assert_called_once_with(timeout_seconds=None)

    @override_settings(CLOUD_DEPLOYMENT="EU")
    @patch("posthog.ph_client.get_client")
    def test_scoped_capture_uses_requested_region(self, get_client_mock: MagicMock) -> None:
        client = MagicMock()
        get_client_mock.return_value = client

        with ph_scoped_capture(region="EU") as capture:
            capture(distinct_id="person", event="event")

        get_client_mock.assert_called_once_with("EU")
        client.capture.assert_called_once_with(distinct_id="person", event="event")
        client.shutdown.assert_called_once()


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
