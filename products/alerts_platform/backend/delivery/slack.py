"""Slack delivery.

The wire and its telemetry come from `posthog/egress/slack`, through `SlackIntegration`. What
stays here is the part that is about alerts: which destination a message goes to, and how a
message becomes blocks.
"""

from typing import Any, Final

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SLACK_INTEGRATION_KINDS, Integration, SlackIntegration
from posthog.slack.channels import (
    MAX_SECTION_CHARS,
    SlackButton,
    actions_block,
    clip_text,
    context_block,
    header_block,
    image_block,
    post_message,
    section_block,
    update_message,
)
from posthog.slack.formatting import escape_slack_mrkdwn

from products.alerts_platform.backend.delivery.describers import slack_renderer_for
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    MessageDetail,
    SlackMessageContent,
)

logger = structlog.get_logger(__name__)

PROVIDER: Final = "slack"

# Slack refuses a post whose context element is over 3000 characters.
MAX_CONTEXT_CHARS: Final = 3000

# Separates alert traffic from the API-driven calls on the shared Slack egress metrics.
EGRESS_SOURCE: Final = "alerts"

# What Slack answers when it cannot fetch an image block, such as an expired chart URL. It refuses
# the whole message, so the message goes again without its image rather than not at all.
IMAGE_REFUSAL: Final = "invalid_blocks"


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
    elements: list[str] = []
    if message.context:
        # Context names things a user chose, such as services, so it is escaped like a detail.
        # Escaping can grow it fourfold, so the clip comes after it.
        elements.append(clip_text(" | ".join(escape_slack_mrkdwn(line) for line in message.context), MAX_CONTEXT_CHARS))
    if message.project is not None:
        # Its own element, so a clipped context line never cuts the link in half.
        elements.append(f"Project: <{message.project.url}|{escape_slack_mrkdwn(message.project.label)}>")
    if elements:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": text} for text in elements]})
    if message.image is not None:
        blocks.append(image_block(message.image.url, message.image.alt_text))
    actions = actions_block([SlackButton(text=link.label, url=link.url) for link in message.links])
    actions["elements"].extend(message.slack_elements)
    blocks.append(actions)
    return blocks


def _without_images(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [block for block in blocks if block.get("type") != "image"]


def content_for(*, team_id: int, message: AlertMessage) -> SlackMessageContent:
    renderer = slack_renderer_for(message.source)
    if renderer is not None:
        try:
            content = renderer(
                team_id=team_id,
                transition=message.transition,
                alert_name=message.alert_name,
                alert_url=message.alert_url,
                project=message.project,
                image=message.image,
            )
            if content is not None:
                return content
        except Exception:
            logger.exception("alerts_platform.slack_renderer_failed", source=message.source.value)
    return SlackMessageContent(text=escape_slack_mrkdwn(message.title), blocks=blocks_for(message))


def _without_image_content(content: SlackMessageContent) -> SlackMessageContent:
    return SlackMessageContent(
        text=content.text,
        blocks=_without_images(content.blocks),
        attachments=[
            {**attachment, "blocks": _without_images(attachment.get("blocks", []))}
            for attachment in content.attachments
        ],
    )


def _refused_image(error: SlackApiError, content: SlackMessageContent) -> bool:
    return error.response.get("error") == IMAGE_REFUSAL and _without_image_content(content) != content


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
        content = content_for(team_id=team_id, message=message)

        def post(content: SlackMessageContent) -> Any:
            return post_message(
                slack,
                channel,
                content.blocks,
                content.text,
                thread_ts=in_reply_to.external_ref.get("ts") if in_reply_to else None,
                # A root edit notifies nobody, and a thread reply notifies only the people who follow
                # the thread. So a resolve and a repeat firing also go to the channel, where legacy
                # posted each one as a new message.
                reply_broadcast=in_reply_to is not None
                and message.transition.kind in (AlertEventKind.RESOLVED, AlertEventKind.FIRING),
                **({"attachments": content.attachments} if content.attachments else {}),
            )

        try:
            try:
                response = post(content)
            except SlackApiError as error:
                if not _refused_image(error, content):
                    raise
                content = _without_image_content(content)
                response = post(content)
        except SlackApiError as error:
            raise DeliveryError(f"Slack refused the message: {error.response.get('error')}") from error
        timestamp = response.get("ts")
        if not timestamp:
            raise DeliveryError("Slack accepted the message but returned no timestamp to reply to.")
        root_content = None
        if in_reply_to is None:
            root_content = {"blocks": content.blocks, "text": content.text}
            if content.attachments:
                root_content["attachments"] = content.attachments
        return MessageHandle(external_ref={"channel": channel, "ts": timestamp}, root_content=root_content)

    def edit_root(self, *, team_id: int, target: AlertDestinationData, root: MessageHandle, state_line: str) -> None:
        workspace_id = target.get("slack_workspace_id")
        channel = root.external_ref.get("channel")
        ts = root.external_ref.get("ts")
        if workspace_id is None or not channel or not ts or not root.root_content:
            raise DeliveryError("This Slack conversation has no opening message to edit.")
        slack = SlackIntegration(self._integration(team_id=team_id, workspace_id=workspace_id), source=EGRESS_SOURCE)
        original = root.root_content
        attachments = original.get("attachments") or []
        text = f"{original['text']} ({state_line})" if original["text"] else ""
        if attachments:
            attachments = [
                *attachments[:-1],
                {
                    **attachments[-1],
                    "blocks": _with_state_line(attachments[-1].get("blocks", []), state_line),
                },
            ]
            blocks = original["blocks"]
        else:
            blocks = _with_state_line(original["blocks"], state_line)
        content = SlackMessageContent(text=text, blocks=blocks, attachments=attachments)

        def update(content: SlackMessageContent) -> None:
            update_message(
                slack,
                channel,
                ts,
                content.blocks,
                content.text,
                **({"attachments": content.attachments} if content.attachments else {}),
            )

        try:
            try:
                update(content)
            except SlackApiError as error:
                if not _refused_image(error, content):
                    raise
                update(_without_image_content(content))
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
