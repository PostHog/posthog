from typing import cast

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts_platform.backend.delivery.discord import MAX_CONTENT_CHARS, DiscordTransport, content_for
from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import AlertDestinationData
from products.alerts_platform.backend.tests.delivery_messages import alert_message, pinned_post


class TestDiscordMessage(SimpleTestCase):
    def test_user_text_can_neither_ping_nor_disguise_a_link(self) -> None:
        message = alert_message(
            headline="@everyone [Checkout](https://evil.example) is firing",
            details=(
                MessageDetail(label="Threshold", value="> 300"),
                MessageDetail(label="Error", value="bad query\n# not a heading"),
            ),
        )

        body = DiscordTransport().body_for(message)

        assert body == {
            "content": "**@everyone \\[Checkout\\](https://evil.example) is firing**\n\n"
            "**Threshold:** \\> 300\n**Error:** bad query\n\\# not a heading",
            "allowed_mentions": {"parse": []},
            "flags": 4,
        }

    def test_a_long_error_keeps_the_message_inside_what_discord_accepts(self) -> None:
        message = alert_message(
            headline="API errors could not be checked",
            details=(MessageDetail(label="Error", value="x" * 5000), MessageDetail(label="Failed checks", value="3")),
        )

        content = content_for(message)

        assert len(content) <= MAX_CONTENT_CHARS
        assert content.endswith("**Failed checks:** 3")


class TestDiscordTransport(SimpleTestCase):
    @parameterized.expand(
        [
            ("discord", "https://discord.com/api/webhooks/123/not-a-real-token", True),
            ("elsewhere", "https://example.com/api/webhooks/123/token", False),
            ("lookalike", "https://discord.com.evil.example/api/webhooks/123/token", False),
            ("userinfo", "https://discord.com@evil.example/api/webhooks/123/token", False),
        ]
    )
    def test_only_a_url_discord_issues_is_posted_to(self, _name: str, url: str, posted: bool) -> None:
        target = cast(AlertDestinationData, {"type": "discord", "webhook_url": url})

        with pinned_post(204) as adapter:
            if posted:
                DiscordTransport().deliver(team_id=2, target=target, message=alert_message())
            else:
                with pytest.raises(DeliveryError):
                    DiscordTransport().deliver(team_id=2, target=target, message=alert_message())

        assert bool(adapter.sent) is posted

    def test_a_send_waits_for_discord_to_save_the_message(self) -> None:
        url = "https://discord.com/api/webhooks/123/not-a-real-token?thread_id=456"
        target = cast(AlertDestinationData, {"type": "discord", "webhook_url": url})

        with pinned_post(200) as adapter:
            DiscordTransport().deliver(team_id=2, target=target, message=alert_message())

        assert adapter.sent[-1].url == f"{url}&wait=true"
