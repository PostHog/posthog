"""Slack delivery.

The wire and its telemetry come from `posthog/egress/slack`, through `SlackIntegration`. What
stays here is the part that is about alerts: which destination a message goes to, and how a
message becomes blocks.
"""

from typing import Any, Final

from slack_sdk.errors import SlackApiError

from posthog.models.integration import SLACK_INTEGRATION_KINDS, Integration, SlackIntegration
from posthog.slack.channels import (
    MAX_SECTION_CHARS,
    SlackButton,
    actions_block,
    clip_text,
    context_block,
    header_block,
    post_message,
    section_block,
    update_message,
)
from posthog.slack.formatting import escape_slack_mrkdwn

from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import AlertDestinationData, MessageDetail

PROVIDER: Final = "slack"

# Slack refuses a post whose context element is over 3000 characters.
MAX_CONTEXT_CHARS: Final = 3000

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
    blocks: list[dict[str, Any]] = [header_block(message.title)]
    if message.details:
        blocks.append(section_block(_body(message.details)))
    if message.context:
        # Context names things a user chose, such as services, so it is escaped like a detail.
        # Escaping can grow it fourfold, so the clip comes after it.
        context = " | ".join(escape_slack_mrkdwn(line) for line in message.context)
        blocks.append(context_block(clip_text(context, MAX_CONTEXT_CHARS)))
    blocks.append(actions_block([SlackButton(text=link.label, url=link.url) for link in message.links]))
    return blocks


def _with_state_line(blocks: list[dict[str, Any]], state_line: str) -> list[dict[str, Any]]:
    """The opening blocks unchanged, with the state line above the buttons `blocks_for` ends with.

    The state line is platform text, built from a state and a time, so it is not escaped.
    """
    return [*blocks[:-1], context_block(state_line), blocks[-1]]


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
        blocks = blocks_for(message)
        # The one place the alert's name reaches mrkdwn: the header renders plain text.
        text = escape_slack_mrkdwn(message.title)
        try:
            response = post_message(
                slack, channel, blocks, text, thread_ts=in_reply_to.external_ref.get("ts") if in_reply_to else None
            )
        except SlackApiError as error:
            # A refusal a person can fix, such as a channel the bot has left, rather than a
            # transport failure a retry would clear.
            raise DeliveryError(f"Slack refused the message: {error.response.get('error')}") from error
        timestamp = response.get("ts")
        if not timestamp:
            raise DeliveryError("Slack accepted the message but returned no timestamp to reply to.")
        # An opening message keeps what it posted, so an edit can restate it word for word.
        root_content = {"blocks": blocks, "text": text} if in_reply_to is None else None
        return MessageHandle(external_ref={"channel": channel, "ts": timestamp}, root_content=root_content)

    def edit_root(self, *, team_id: int, target: AlertDestinationData, root: MessageHandle, state_line: str) -> None:
        workspace_id = target.get("slack_workspace_id")
        channel = root.external_ref.get("channel")
        ts = root.external_ref.get("ts")
        if workspace_id is None or not channel or not ts or not root.root_content:
            raise DeliveryError("This Slack conversation has no opening message to edit.")
        slack = SlackIntegration(self._integration(team_id=team_id, workspace_id=workspace_id), source=EGRESS_SOURCE)
        try:
            update_message(
                slack,
                channel,
                ts,
                _with_state_line(root.root_content["blocks"], state_line),
                # Screen readers read the fallback text rather than the blocks, so it carries the
                # current state too.
                f"{root.root_content['text']} ({state_line})",
            )
        except SlackApiError as error:
            raise DeliveryError(f"Slack refused the edit: {error.response.get('error')}") from error

    def _integration(self, *, team_id: int, workspace_id: int) -> Integration:
        # Scoped by team as well as by id. The destination names an integration, and nothing
        # between the destination and here checks that it still belongs to the sending team.
        integration = Integration.objects.filter(
            id=workspace_id, team_id=team_id, kind__in=SLACK_INTEGRATION_KINDS
        ).first()
        if integration is None:
            raise DeliveryError("The Slack workspace for this alert is not connected.")
        return integration
