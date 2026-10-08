import json
from typing import cast

import pytest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.delivery.teams import TeamsTransport, card_for
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import AlertDestinationData
from products.alerts_platform.backend.tests.delivery_messages import alert_message, pinned_post

TEAMS_URL = "https://prod-00.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=fake"


class TestTeamsCard(SimpleTestCase):
    def test_a_message_is_an_adaptive_card_with_a_fact_per_detail(self) -> None:
        message = alert_message(
            headline="[Checkout](https://evil.example) is firing",
            details=(MessageDetail(label="Value", value="312"), MessageDetail(label="Error", value="no *column*")),
        )

        assert card_for(message) == {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.2",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": r"\[Checkout\](https://evil.example) is firing",
                                "weight": "Bolder",
                                "wrap": True,
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Value", "value": "312"},
                                    {"title": "Error", "value": r"no \*column\*"},
                                ],
                            },
                        ],
                    },
                }
            ],
        }

    def test_a_query_error_cannot_push_the_card_past_what_teams_accepts(self) -> None:
        message = alert_message(
            details=(
                MessageDetail(label="Error", value="\x01" * 50_000),
                MessageDetail(label="Query", value="\x01" * 50_000),
                MessageDetail(label="Failed checks", value="3"),
            )
        )
        target = cast(AlertDestinationData, {"type": "teams", "webhook_url": TEAMS_URL})

        with pinned_post(202) as adapter:
            TeamsTransport().deliver(team_id=2, target=target, message=message)

        sent = adapter.sent[-1].body
        assert isinstance(sent, bytes)
        facts = json.loads(sent)["attachments"][0]["content"]["body"][1]["facts"]
        assert len(sent) < 28_000
        assert facts[2] == {"title": "Failed checks", "value": "3"}


class TestTeamsTransport(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "teams_workflow",
                TEAMS_URL,
                True,
            ),
            ("elsewhere", "https://example.com/hook", False),
        ]
    )
    def test_only_a_url_teams_issues_is_posted_to(self, _name: str, url: str, posted: bool) -> None:
        target = cast(AlertDestinationData, {"type": "teams", "webhook_url": url})

        with pinned_post(202) as adapter:
            if posted:
                TeamsTransport().deliver(team_id=2, target=target, message=alert_message())
            else:
                with pytest.raises(DeliveryError):
                    TeamsTransport().deliver(team_id=2, target=target, message=alert_message())

        assert bool(adapter.sent) is posted
