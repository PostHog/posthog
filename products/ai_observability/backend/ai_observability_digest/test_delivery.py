from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.ai_observability.backend.ai_observability_digest.delivery import (
    SlackDeliveryError,
    deliver_overview_to_slack,
)
from products.ai_observability.backend.ai_observability_digest.schema import AIObservabilityOverview, OverviewSection


def _overview(section_count: int) -> AIObservabilityOverview:
    return AIObservabilityOverview(
        headline="AI observability digest",
        summary="All systems nominal.",
        sections=[OverviewSection(title=f"Section {i}", body=f"Body {i}") for i in range(section_count)],
    )


class TestDeliverOverviewToSlack(SimpleTestCase):
    def _patch_slack(self):
        integration = MagicMock()
        integration_objects = MagicMock()
        integration_objects.get.return_value = MagicMock()
        integration.objects = integration_objects
        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "1234.5678"}
        slack_integration = MagicMock()
        slack_integration.return_value.client = client
        return integration, client, slack_integration

    def test_raises_when_no_integration_or_channel(self):
        with self.assertRaises(SlackDeliveryError):
            deliver_overview_to_slack(team_id=1, integration_id=None, channel="#x", overview=_overview(1))
        with self.assertRaises(SlackDeliveryError):
            deliver_overview_to_slack(team_id=1, integration_id=7, channel="", overview=_overview(1))

    def test_scopes_lookup_by_team_and_posts_single_message_for_one_section(self):
        integration, client, slack_integration = self._patch_slack()
        with (
            patch("products.ai_observability.backend.ai_observability_digest.delivery.Integration", integration),
            patch(
                "products.ai_observability.backend.ai_observability_digest.delivery.SlackIntegration", slack_integration
            ),
        ):
            ts = deliver_overview_to_slack(team_id=42, integration_id=7, channel="#aio", overview=_overview(1))

        self.assertEqual(ts, "1234.5678")
        # Integration lookup is scoped to the team and the slack kind.
        integration.objects.get.assert_called_once_with(id=7, team_id=42, kind="slack")
        # One main message, no thread replies (only one section).
        self.assertEqual(client.chat_postMessage.call_count, 1)
        main_call = client.chat_postMessage.call_args
        self.assertEqual(main_call.kwargs["channel"], "#aio")
        block_types = [b["type"] for b in main_call.kwargs["blocks"]]
        self.assertEqual(block_types[0], "header")
        self.assertIn("section", block_types)

    def test_threads_remaining_sections(self):
        integration, client, slack_integration = self._patch_slack()
        with (
            patch("products.ai_observability.backend.ai_observability_digest.delivery.Integration", integration),
            patch(
                "products.ai_observability.backend.ai_observability_digest.delivery.SlackIntegration", slack_integration
            ),
        ):
            deliver_overview_to_slack(team_id=1, integration_id=7, channel="#aio", overview=_overview(3))

        # 1 main message + 2 thread replies for sections[1:].
        self.assertEqual(client.chat_postMessage.call_count, 3)
        thread_calls = client.chat_postMessage.call_args_list[1:]
        for call in thread_calls:
            self.assertEqual(call.kwargs["thread_ts"], "1234.5678")

    def test_raises_slack_delivery_error_when_integration_missing(self):
        integration, _client, slack_integration = self._patch_slack()

        class _DoesNotExist(Exception):
            pass

        integration.DoesNotExist = _DoesNotExist
        integration.objects.get.side_effect = _DoesNotExist()

        with (
            patch("products.ai_observability.backend.ai_observability_digest.delivery.Integration", integration),
            patch(
                "products.ai_observability.backend.ai_observability_digest.delivery.SlackIntegration", slack_integration
            ),
        ):
            with self.assertRaises(SlackDeliveryError):
                deliver_overview_to_slack(team_id=1, integration_id=7, channel="#aio", overview=_overview(1))
