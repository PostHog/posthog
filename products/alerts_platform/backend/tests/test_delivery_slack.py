from dataclasses import replace
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.slack.channels import MAX_HEADER_CHARS, MAX_SECTION_CHARS

from products.alerts_platform.backend.delivery.message import UNTRACKED_GROUPS_LABEL
from products.alerts_platform.backend.delivery.slack import SlackTransport, blocks_for, content_for
from products.alerts_platform.backend.delivery.transport import DeliveryError, DestinationMisconfigured, MessageHandle
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    MessageDetail,
    MessageImage,
    MessageLink,
    SlackMessageContent,
)
from products.alerts_platform.backend.tests.delivery_messages import ALERT_URL, alert_message, announced_transition

MESSAGE = alert_message(
    headline="API errors is firing",
    details=(MessageDetail(label="Value", value="300"), MessageDetail(label="Threshold", value="above 100")),
)


class TestSlackBlocks(SimpleTestCase):
    def test_the_headline_is_clipped_to_what_slack_accepts(self) -> None:
        message = alert_message(headline="x" * 400, details=())

        header = blocks_for(message)[0]
        assert len(header["text"]["text"]) <= MAX_HEADER_CHARS

    def test_every_detail_reaches_the_body(self) -> None:
        section = blocks_for(MESSAGE)[1]

        assert section["text"]["text"] == "*Value:* 300\n*Threshold:* above 100"

    def test_a_long_detail_keeps_the_body_inside_what_slack_accepts(self) -> None:
        message = alert_message(
            headline="API errors could not be checked",
            details=(
                MessageDetail(label="Error", value="x" * 5000),
                MessageDetail(label="Failed checks", value="3"),
            ),
        )

        section = blocks_for(message)[1]

        # Over the limit Slack rejects the send outright, so the alert reaches nobody. Clipping
        # the joined body instead would take the failure count out with the error.
        assert len(section["text"]["text"]) <= MAX_SECTION_CHARS
        assert "*Failed checks:* 3" in section["text"]["text"]

    def test_user_text_cannot_speak_as_slack_markup(self) -> None:
        message = replace(
            alert_message(
                headline="API errors could not be checked",
                details=(MessageDetail(label="Error", value="no column <!channel> in <http://x|table>"),),
                context=("Services: <!channel>",),
            ),
            project=MessageLink(label="Prod <!channel>", url="https://app.example.com/project/2"),
        )

        blocks = blocks_for(message)
        body = blocks[1]["text"]["text"]
        context, project = (element["text"] for element in blocks[2]["elements"])

        assert "<!channel>" not in body + context + project
        assert "&lt;!channel&gt;" in body
        assert context == "Services: &lt;!channel&gt;"
        assert project == "Project: <https://app.example.com/project/2|Prod &lt;!channel&gt;>"

    def test_escaped_context_stays_inside_what_slack_accepts(self) -> None:
        message = alert_message(context=("&" * 300,) * 3)

        context = blocks_for(message)[-2]["elements"][0]["text"]

        assert len(context) <= 3000

    def test_a_message_without_details_carries_no_empty_section(self) -> None:
        blocks = blocks_for(alert_message(headline="API errors is resolved", details=()))

        assert [block["type"] for block in blocks] == ["header", "actions"]
        assert blocks[1]["elements"][0]["url"] == ALERT_URL

    def test_a_source_image_sits_above_the_buttons(self) -> None:
        # The state line a resolve adds goes above the last block, so the buttons have to stay last.
        message = alert_message(
            context=("Insight: Signups",),
            image=MessageImage(url="https://app.example.com/chart.png", alt_text="Insight chart"),
        )

        blocks = blocks_for(message)

        assert [block["type"] for block in blocks] == ["header", "context", "image", "actions"]
        assert blocks[2] == {
            "type": "image",
            "image_url": "https://app.example.com/chart.png",
            "alt_text": "Insight chart",
        }

    def test_a_source_slack_element_follows_the_buttons_in_their_block(self) -> None:
        menu = {"type": "static_select", "action_id": "snooze"}

        actions = blocks_for(replace(alert_message(), slack_elements=(menu,)))[-1]

        assert [element["type"] for element in actions["elements"]] == ["button", menu["type"]]
        assert actions["elements"][-1] is menu

    def test_the_source_data_link_comes_before_the_alert_link(self) -> None:
        data_url = "https://app.example.com/project/1/logs"
        message = alert_message(data_link=MessageLink(label="View logs", url=data_url))

        buttons = blocks_for(message)[-1]["elements"]

        assert [(button["text"]["text"], button["url"]) for button in buttons] == [
            ("View logs", data_url),
            ("View alert", ALERT_URL),
        ]


class TestSlackTransport(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T-1", config={})
        self.target = cast(
            AlertDestinationData,
            {"type": "slack", "slack_workspace_id": self.integration.id, "slack_channel_id": "C-ENG"},
        )

    def _send(self, **overrides: Any) -> Any:
        with patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as slack_integration:
            slack_integration.return_value.client.chat_postMessage.return_value = {"ts": "1700000000.1"}
            handle = SlackTransport().deliver(
                team_id=overrides.pop("team_id", self.team.id),
                target=overrides.pop("target", self.target),
                message=overrides.pop("message", MESSAGE),
                **overrides,
            )
        return handle, slack_integration.return_value.client.chat_postMessage

    def test_an_opening_send_returns_the_handle_and_content_a_later_edit_needs(self) -> None:
        handle, post = self._send()

        assert handle.external_ref == {"channel": "C-ENG", "ts": "1700000000.1"}
        assert handle.root_content == {"blocks": blocks_for(MESSAGE), "text": post.call_args.kwargs["text"]}
        assert post.call_args.kwargs["thread_ts"] is None

    @parameterized.expand(
        [("a_resolve", AlertEventKind.RESOLVED, True), ("a_repeat_firing", AlertEventKind.FIRING, True)]
    )
    def test_a_reply_goes_into_the_thread_it_names_and_keeps_no_content(
        self, _name: str, kind: AlertEventKind, broadcast: bool
    ) -> None:
        handle, post = self._send(
            in_reply_to=MessageHandle(external_ref={"channel": "C-ENG", "ts": "1699999999.9"}),
            message=alert_message(transition=announced_transition(kind=kind)),
        )

        assert post.call_args.kwargs["thread_ts"] == "1699999999.9"
        assert post.call_args.kwargs["reply_broadcast"] is broadcast
        assert handle.root_content is None

    def test_an_edit_keeps_the_opening_content_and_adds_the_state_above_the_buttons(self) -> None:
        opening = blocks_for(MESSAGE)
        root = MessageHandle(
            external_ref={"channel": "C-ENG", "ts": "1700000000.1"},
            root_content={"blocks": opening, "text": "API errors is firing"},
        )

        with patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as slack_integration:
            SlackTransport().edit_root(
                team_id=self.team.id, target=self.target, root=root, state_line="Resolved as of 14:32 UTC"
            )
        update = slack_integration.return_value.client.chat_update

        assert update.call_args.kwargs["channel"] == "C-ENG"
        assert update.call_args.kwargs["ts"] == "1700000000.1"
        assert update.call_args.kwargs["text"] == "API errors is firing (Resolved as of 14:32 UTC)"
        blocks = update.call_args.kwargs["blocks"]
        assert [*blocks[:-2], blocks[-1]] == opening
        assert blocks[-2] == {"type": "context", "elements": [{"type": "mrkdwn", "text": "Resolved as of 14:32 UTC"}]}

    def test_a_workspace_another_team_owns_is_refused(self) -> None:
        # An unscoped lookup finds the integration by id alone and sends into it.
        with pytest.raises(DeliveryError):
            self._send(team_id=self.team.id + 1)

    @parameterized.expand(
        [
            ("not_in_channel", True),
            ("account_inactive", True),
            ("channel_not_found", False),
            ("missing_scope", False),
            ("ratelimited", False),
            ("internal_error", False),
        ]
    )
    def test_a_refusal_from_slack_becomes_a_delivery_error(self, code: str, misconfigured: bool) -> None:
        with patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as slack_integration:
            slack_integration.return_value.client.chat_postMessage.side_effect = SlackApiError(code, {"error": code})
            with pytest.raises(DeliveryError) as refused:
                SlackTransport().deliver(team_id=self.team.id, target=self.target, message=MESSAGE)

        assert isinstance(refused.value, DestinationMisconfigured) is misconfigured

    def test_a_message_whose_image_slack_cannot_fetch_goes_again_without_it(self) -> None:
        message = alert_message(image=MessageImage(url="https://app.example.com/chart.png", alt_text="Insight chart"))
        with patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as slack_integration:
            post = slack_integration.return_value.client.chat_postMessage
            post.side_effect = [SlackApiError("invalid_blocks", {"error": "invalid_blocks"}), {"ts": "1700000000.1"}]
            handle = SlackTransport().deliver(team_id=self.team.id, target=self.target, message=message)

        assert post.call_count == 2
        assert "image" not in [block["type"] for block in post.call_args.kwargs["blocks"]]
        # An edit restates what was posted, so it never names the image again.
        assert handle is not None and handle.root_content is not None
        assert handle.root_content["blocks"] == post.call_args.kwargs["blocks"]

    def test_a_destination_missing_its_channel_is_refused(self) -> None:
        target = cast(AlertDestinationData, {"type": "slack", "slack_workspace_id": self.integration.id})

        with pytest.raises(DeliveryError):
            self._send(target=target)


class TestSlackAttachmentTransport(SimpleTestCase):
    @parameterized.expand([(False,), (True,)])
    def test_attachments_survive_send_retry_and_state_update(self, refuse_image: bool) -> None:
        image = {"type": "image", "image_url": "https://example.com/chart.png", "alt_text": "Chart"}
        actions = {
            "type": "actions",
            "elements": [
                {"type": "button", "url": "https://example.com", "text": {"type": "plain_text", "text": "View"}}
            ],
        }
        metadata = {
            "color": "#D97706",
            "blocks": [{"type": "section", "text": {"type": "plain_text", "text": "Limit exceeded"}}],
        }
        content = SlackMessageContent(text="", blocks=[], attachments=[metadata, {"blocks": [image, actions]}])
        target = cast(AlertDestinationData, {"type": "slack", "slack_workspace_id": 1, "slack_channel_id": "C-SAMPLE"})
        with (
            patch("products.alerts_platform.backend.delivery.slack.slack_renderer_for") as renderer,
            patch.object(SlackTransport, "_integration"),
            patch("products.alerts_platform.backend.delivery.slack.SlackIntegration") as integration,
        ):
            renderer.return_value.return_value = content
            post = integration.return_value.client.chat_postMessage
            responses: list[Any] = [{"ts": "1700000000.1"}]
            if refuse_image:
                responses.insert(0, SlackApiError("invalid_blocks", {"error": "invalid_blocks"}))
            post.side_effect = responses
            transport = SlackTransport()
            handle = transport.deliver(team_id=1, target=target, message=MESSAGE)
            assert handle is not None
            sent = post.call_args.kwargs["attachments"]
            assert sent[0] == metadata
            assert sent[1]["blocks"][-1] == actions
            assert any(block["type"] == "image" for block in sent[1]["blocks"]) is not refuse_image
            transport.edit_root(team_id=1, target=target, root=handle, state_line="Resolved")
            update = integration.return_value.client.chat_update.call_args.kwargs
            updated = update["attachments"]
            assert updated[0] == metadata
            assert updated[1]["blocks"][-1] == actions
            assert updated[1]["blocks"][-2]["elements"][0]["text"] == "Resolved"
            # The card is the attachment, so the edit must not promote the stand-in below.
            assert update["blocks"] == []
            assert handle.root_content is not None
            assert handle.root_content["attachments"] == sent
            # A reader from before attachments existed edits `blocks` and indexes its last element,
            # so an attachment card leaves it something to work on rather than an empty list.
            assert handle.root_content["blocks"]
            assert content.attachments[1]["blocks"] == [image, actions]


class TestSourceRendererKeepsGroupLimitNotice(SimpleTestCase):
    @parameterized.expand(
        [
            # The renderer contract promises neither an attachment nor a trailing action row, and
            # the notice is the only sign that the alert stopped at its group limit.
            ("an_attachment", False, False),
            ("blocks_alone", True, False),
            ("blocks_without_an_action_row", True, True),
        ]
    )
    def test_untracked_groups_detail_survives_any_renderer_shape(
        self, _name: str, blocks_only: bool, without_actions: bool
    ) -> None:
        rendered: list[dict[str, Any]] = [{"type": "divider"}]
        if not without_actions:
            rendered.append({"type": "actions", "elements": []})
        content = (
            SlackMessageContent(text="Alert", blocks=rendered)
            if blocks_only
            else SlackMessageContent(text="Alert", blocks=[], attachments=[{"blocks": rendered}])
        )
        message = replace(
            MESSAGE, details=(MessageDetail(label=UNTRACKED_GROUPS_LABEL, value="2 more groups not tracked"),)
        )
        with patch("products.alerts_platform.backend.delivery.slack.slack_renderer_for") as renderer:
            renderer.return_value.return_value = content
            result = content_for(team_id=1, message=message)
        blocks = result.blocks if blocks_only else result.attachments[0]["blocks"]
        assert "2 more groups not tracked" in str(blocks)
        # Above the buttons when there are buttons, so the notice is never read as one of them.
        assert blocks[-1]["type"] == ("section" if without_actions else "actions")
