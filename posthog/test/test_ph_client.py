from typing import Any

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

import posthoganalytics
from parameterized import parameterized

from posthog.clickhouse.query_tagging import tags_context
from posthog.ph_client import (
    ScopedCapture,
    default_before_send,
    get_client,
    ph_scoped_capture,
    self_hosted_capture_reaches_posthog,
)


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
                self.assertIsNotNone(client.before_send)
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
    def test_regional_capture_respects_private_deployment_setting(self, region: str, private_capture: bool) -> None:
        before_send = MagicMock(side_effect=lambda message: message)
        with override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=private_capture):
            client = get_client(
                region, disabled=False, send=False, enable_local_evaluation=False, before_send=before_send
            )
        assert client is not None
        try:
            with tags_context(is_scout_experiment=True):
                captured = client.capture("query executed", distinct_id="synthetic")
            self.assertEqual(captured is None, private_capture)
            self.assertEqual(before_send.call_count, 0 if private_capture else 1)
            with tags_context(is_scout_experiment=False):
                self.assertIsNotNone(client.capture("query executed", distinct_id="synthetic"))
            self.assertEqual(before_send.call_count, 1 if private_capture else 2)
            before_send.side_effect = lambda message: None
            with posthoganalytics.new_context(capture_exceptions=False):
                posthoganalytics.tag("$update_person_last_seen_at", False)
                self.assertIsNone(client.capture("query executed", distinct_id="synthetic"))
        finally:
            client.shutdown()

    @parameterized.expand(
        [
            ("cloud", False, False, {"$exception": True, "query executed": True}),
            ("cloud_private_scout", True, False, {"$exception": True, "query executed": True}),
            ("self_hosted", False, True, {"$exception": False, "query executed": True}),
            ("self_hosted_private_scout", True, True, {"$exception": False, "query executed": True}),
        ]
    )
    def test_default_before_send_drops_self_hosted_exceptions(
        self, _name: str, private_scout_capture: bool, self_hosted: bool, expected_kept: dict[str, bool]
    ) -> None:
        before_send = default_before_send(private_scout_capture=private_scout_capture, self_hosted=self_hosted)
        for event, kept in expected_kept.items():
            message = {"event": event, "distinct_id": "synthetic", "properties": {}}
            with tags_context(is_scout_experiment=False):
                result = message if before_send is None else before_send(message)
            self.assertEqual(result is not None, kept, event)
            if kept:
                self.assertEqual(result, message)
                with posthoganalytics.new_context(capture_exceptions=False):
                    posthoganalytics.tag("$update_person_last_seen_at", False)
                    result = before_send({"event": event, "properties": {"retained": True}})
                self.assertEqual(
                    result,
                    {"event": event, "properties": {"retained": True, "$update_person_last_seen_at": False}},
                )
                properties = {"$update_person_last_seen_at": False} if event == "$exception" else {}
                self.assertEqual(
                    before_send({"event": event, "properties": {}}), {"event": event, "properties": properties}
                )
        if private_scout_capture and before_send is not None:
            with tags_context(is_scout_experiment=True):
                self.assertIsNone(before_send({"event": "query executed", "distinct_id": "synthetic"}))

    @parameterized.expand(
        [
            ("self_hosted", True, False, True),
            ("self_hosted_self_capture", True, True, False),
            ("cloud_or_local", False, False, False),
        ]
    )
    def test_self_hosted_capture_reaches_posthog(
        self, _name: str, hobby: bool, self_capture: bool, expected: bool
    ) -> None:
        with (
            patch("posthog.ph_client.is_hobby", return_value=hobby),
            override_settings(TEST=False, SELF_CAPTURE=self_capture),
        ):
            self.assertEqual(self_hosted_capture_reaches_posthog(), expected)

    @parameterized.expand([("false", False), ("true", True), ("unset", None), ("zero", 0)])
    @override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False)
    @patch("posthoganalytics.client.flags")
    def test_minimal_flag_events_preserve_only_explicit_last_seen_suppression(
        self, _name: str, control: bool | int | None, mock_flags: MagicMock
    ) -> None:
        mock_flags.return_value = {
            "flags": {
                "report-routing": {"key": "report-routing", "value": True, "metadata": {"has_experiment": False}}
            },
            "minimalFlagCalledEvents": True,
        }
        before_send = MagicMock(side_effect=lambda message: message)
        client = get_client(send=False, disabled=False, enable_local_evaluation=False, before_send=before_send)
        assert client is not None
        try:
            with posthoganalytics.new_context(capture_exceptions=False):
                if control is not None:
                    posthoganalytics.tag("$update_person_last_seen_at", control)
                posthoganalytics.tag("unrelated_tag", "excluded")
                self.assertIs(client.get_feature_flag("report-routing", "recipient"), True)
            before_send.assert_called_once()
            message = before_send.call_args.args[0]
            self.assertEqual(message["event"], "$feature_flag_called")
            self.assertEqual(message["distinct_id"], "recipient")
            self.assertEqual(message["properties"]["$feature_flag"], "report-routing")
            self.assertNotIn("unrelated_tag", message["properties"])
            self.assertEqual("$update_person_last_seen_at" in message["properties"], control is False)
            if control is False:
                self.assertIs(message["properties"]["$update_person_last_seen_at"], False)

            self.assertIs(client.get_feature_flag("report-routing", "interactive-user"), True)
            self.assertEqual(before_send.call_count, 2)
            self.assertNotIn("$update_person_last_seen_at", before_send.call_args.args[0]["properties"])
        finally:
            client.shutdown()


class TestSecondaryTelemetryLastSeen(SimpleTestCase):
    @parameterized.expand([("module",), ("regional",), ("regional_custom_callback",)])
    @override_settings(SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False)
    def test_technical_events_do_not_count_as_user_activity(self, client_kind: str) -> None:
        with patch.multiple(
            posthoganalytics,
            default_client=None,
            disabled=False,
            send=False,
            enable_local_evaluation=False,
            enable_exception_autocapture=False,
        ):
            if client_kind == "module":
                client = posthoganalytics.setup()
            else:
                custom_callback = (
                    (lambda message: {**message, "properties": {"callback_property": True}})
                    if client_kind == "regional_custom_callback"
                    else None
                )
                client = get_client(
                    send=False, disabled=False, enable_local_evaluation=False, before_send=custom_callback
                )
            assert client is not None
            original_before_send = client.before_send
            assert original_before_send is not None
            captured_messages: list[dict[str, Any]] = []

            def observe_capture(message: dict[str, Any]) -> dict[str, Any] | None:
                result = original_before_send(message)
                if result is not None:
                    captured_messages.append(result)
                return result

            client.before_send = observe_capture
            try:
                for event, suppressed in (
                    ("$ai_generation", True),
                    ("$ai_span", True),
                    ("$ai_trace", True),
                    ("$exception", True),
                    ("conversation message sent", False),
                    ("ai prompt submitted", False),
                    ("$pageview", False),
                ):
                    with self.subTest(event=event):
                        self.assertIsNotNone(client.capture(event, distinct_id="interactive-user"))
                        message = captured_messages[-1]
                        self.assertEqual(message["event"], event)
                        self.assertEqual(message["distinct_id"], "interactive-user")
                        self.assertEqual("$update_person_last_seen_at" in message["properties"], suppressed)
                        if suppressed:
                            self.assertIs(message["properties"]["$update_person_last_seen_at"], False)
                        if client_kind == "regional_custom_callback":
                            self.assertIs(message["properties"]["callback_property"], True)
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

    @override_settings(CLOUD_DEPLOYMENT="EU")
    def test_cross_region_capture_preserves_the_event_region(self) -> None:
        before_send = MagicMock(side_effect=lambda event: event)
        client = get_client("US", send=False, disabled=False, enable_local_evaluation=False, before_send=before_send)
        with patch("posthog.ph_client.get_client", return_value=client) as make_client:
            with ph_scoped_capture(region="US", event_region="EU") as capture:
                capture(distinct_id="person", event="account_audit_finished")
        make_client.assert_called_once_with("US")
        self.assertEqual(before_send.call_args.args[0]["properties"]["region"], "EU")


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
