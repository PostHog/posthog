"""Slack delivery.

The wire and its telemetry come from `posthog/egress/slack`, through `SlackIntegration`. What
stays here is the part that is about alerts: which destination a message goes to, and how a
message becomes blocks.
"""

from typing import Any, Final

from slack_sdk.errors import SlackApiError

from posthog.models.integration import SLACK_INTEGRATION_KINDS, Integration, SlackIntegration
from posthog.slack.channels import MAX_SECTION_CHARS, clip_text, header_block, post_message, section_block
from posthog.slack.formatting import escape_slack_mrkdwn

from products.alerts_platform.backend.delivery.message import AlertMessage, MessageDetail
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import AlertDestinationData

PROVIDER: Final = "slack"

# Separates alert traffic from the API-driven calls on the shared Slack egress metrics.
EGRESS_SOURCE: Final = "alerts"


def _line(detail: MessageDetail) -> str:
    # The value carries a query error, which is user-written text. Unescaped `<...>` is live in
    # mrkdwn, so `<!channel>` would broadcast and `<url|label>` would render a disguised link.
    return f"*{detail.label}:* {escape_slack_mrkdwn(detail.value)}"


def _body(details: tuple[MessageDetail, ...]) -> str:
    lines = [_line(detail) for detail in details]
    body = "\n".join(lines)
    if len(body) <= MAX_SECTION_CHARS:
        return body
    # An error message can carry a whole query, so it is the value that overflows. Clipping the
    # joined body would drop every detail after it, and the failure count is one of those.
    share = (MAX_SECTION_CHARS - len(lines) + 1) // len(lines)
    return "\n".join(clip_text(line, share) for line in lines)


def blocks_for(message: AlertMessage) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [header_block(message.headline)]
    if message.details:
        blocks.append(section_block(_body(message.details)))
    return blocks


class SlackTransport:
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

        slack = SlackIntegration(self._integration(team_id=team_id, workspace_id=workspace_id), source=EGRESS_SOURCE)
        try:
            response = post_message(
                slack,
                channel,
                blocks_for(message),
                # The one place the alert's name reaches mrkdwn: the header renders plain text.
                escape_slack_mrkdwn(message.headline),
                thread_ts=in_reply_to.external_ref.get("ts") if in_reply_to else None,
            )
        except SlackApiError as error:
            # A refusal a person can fix, such as a channel the bot has left, rather than a
            # transport failure a retry would clear.
            raise DeliveryError(f"Slack refused the message: {error.response.get('error')}") from error
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
