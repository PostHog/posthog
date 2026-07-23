import threading

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import posthoganalytics
from parameterized import parameterized
from posthoganalytics import Posthog

import posthog.ph_client
from posthog.ph_client import enable_dedicated_ai_endpoint_for_default_client, get_client, ph_scoped_capture
from posthog.settings.ingestion import (
    DedicatedAIEndpointRollout as Rollout,
    _parse_dedicated_ai_rollout,
)


class TestPhScopedCapture(SimpleTestCase):
    def test_hung_shutdown_does_not_block_context_exit(self) -> None:
        release = threading.Event()
        shutdown_completed = threading.Event()

        def hung_shutdown() -> None:
            release.wait(timeout=10)
            shutdown_completed.set()

        client = MagicMock(**{"shutdown.side_effect": hung_shutdown})
        try:
            with (
                patch.object(posthog.ph_client, "PH_SCOPED_CAPTURE_FLUSH_TIMEOUT_SECONDS", 0.05),
                patch.object(posthog.ph_client, "get_client", return_value=client),
            ):
                with ph_scoped_capture():
                    pass
            # Exit must abandon the hung shutdown, not hold the caller's thread
            # (request threads and worker slots ride on this).
            assert not shutdown_completed.is_set()
        finally:
            release.set()


class TestDedicatedAIEndpointRollout(SimpleTestCase):
    @parameterized.expand(
        [
            (Rollout.OFF, Rollout.RUNNER, False),
            (Rollout.OFF, Rollout.ALL, False),
            (Rollout.RUNNER, Rollout.RUNNER, True),
            (Rollout.RUNNER, Rollout.ALL, False),
            (Rollout.ALL, Rollout.RUNNER, True),
            (Rollout.ALL, Rollout.ALL, True),
        ]
    )
    def test_dedicated_ai_endpoint_gated_by_rollout_stage(self, rollout, caller_stage, expected):
        with override_settings(POSTHOG_DEDICATED_AI_ENDPOINT_ROLLOUT=rollout):
            client = get_client(
                "US", dedicated_ai_endpoint_stage=caller_stage, send=False, enable_local_evaluation=False
            )
            self.assertEqual(client._dedicated_ai_endpoint, expected)

    def test_general_callers_only_opt_in_at_full_rollout(self):
        with override_settings(POSTHOG_DEDICATED_AI_ENDPOINT_ROLLOUT=Rollout.RUNNER):
            self.assertFalse(get_client("US", send=False, enable_local_evaluation=False)._dedicated_ai_endpoint)
        with override_settings(POSTHOG_DEDICATED_AI_ENDPOINT_ROLLOUT=Rollout.ALL):
            self.assertTrue(get_client("US", send=False, enable_local_evaluation=False)._dedicated_ai_endpoint)

    @parameterized.expand(
        [
            ("off", Rollout.OFF),
            ("runner", Rollout.RUNNER),
            ("all", Rollout.ALL),
            ("  RUNNER  ", Rollout.RUNNER),
            ("bogus", Rollout.OFF),
        ]
    )
    def test_parse_rollout_falls_back_to_off_on_invalid(self, value, expected):
        self.assertEqual(_parse_dedicated_ai_rollout(value), expected)

    @parameterized.expand(
        [
            (Rollout.OFF, False),
            (Rollout.RUNNER, False),
            (Rollout.ALL, True),
        ]
    )
    def test_default_client_routes_ai_events_only_at_full_rollout(self, rollout, expected):
        client = Posthog("test-key", send=False, enable_local_evaluation=False)
        original = posthoganalytics.default_client
        posthoganalytics.default_client = client  # ty: ignore[invalid-assignment]
        try:
            with override_settings(POSTHOG_DEDICATED_AI_ENDPOINT_ROLLOUT=rollout):
                enable_dedicated_ai_endpoint_for_default_client()
        finally:
            posthoganalytics.default_client = original
        self.assertEqual(client._dedicated_ai_endpoint, expected)
        self.assertTrue(client.consumers)
        for consumer in client.consumers:
            self.assertEqual(consumer.dedicated_ai_endpoint, expected)
