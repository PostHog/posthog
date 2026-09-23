"""Slack delivery.

The wire and its telemetry come from `posthog/egress/slack`, through `SlackIntegration`. What
stays here is the part that is about alerts: which destination a message goes to, and how a
message becomes blocks.
"""

from typing import Any, Final

from posthog.models.integration import SLACK_INTEGRATION_KINDS, Integration, SlackIntegration

from products.alerts.backend.delivery.message import AlertMessage
from products.alerts.backend.delivery.transport import REPLY, UPDATE, DeliveryError, MessageHandle
from products.alerts.backend.facade.contracts import AlertDestinationData

PROVIDER: Final = "slack"

# Slack refuses a header block longer than this, and an alert name can reach 255 characters.
_HEADER_MAX_LEN: Final = 150


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def blocks_for(message: AlertMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _clip(message.headline, _HEADER_MAX_LEN)}}
    ]
    if message.details:
        body = "\n".join(f"*{label}:* {value}" for label, value in message.details)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
    return blocks


class SlackTransport:
    capabilities = frozenset({REPLY, UPDATE})
    provider = PROVIDER

    def channel_target(self, target: AlertDestinationData) -> str:
        return target.get("slack_channel_id", "")

    def deliver(
        self,
        *,
        team_id: int,
        target: AlertDestinationData,
        message: AlertMessage,
        in_reply_to: MessageHandle | None = None,
    ) -> MessageHandle | None:
        workspace_id = target.get("slack_workspace_id")
        channel = target.get("slack_channel_id")
        if workspace_id is None or channel is None:
            raise DeliveryError("This Slack destination is missing its workspace or channel.")

        response = SlackIntegration(
            self._integration(team_id=team_id, workspace_id=workspace_id)
        ).client.chat_postMessage(
            channel=channel,
            text=message.headline,
            blocks=blocks_for(message),
            thread_ts=in_reply_to.external_ref.get("ts") if in_reply_to else None,
        )
        timestamp = response.get("ts")
        if not timestamp:
            raise DeliveryError("Slack accepted the message but returned no timestamp to reply to.")
        return MessageHandle(external_ref={"channel": channel, "ts": timestamp})

    def _integration(self, *, team_id: int, workspace_id: int) -> Integration:
        # Scoped by team as well as by id. The destination names an integration, and nothing
        # between the destination and here checks that it still belongs to the sending team.
        integration = Integration.objects.filter(
            id=workspace_id, team_id=team_id, kind__in=SLACK_INTEGRATION_KINDS
        ).first()
        if integration is None:
            raise DeliveryError("The Slack workspace for this alert is not connected.")
        return integration
