from posthog.test.base import APIBaseTest

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight

from ee.tasks.subscriptions.teams_subscriptions import build_teams_subscription_card
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

VALID_TEAMS_WEBHOOK_URL = (
    "https://prod-25.westeurope.logic.azure.com:443/workflows/abc123/triggers/manual/paths/invoke?sig=secret"
)


class TestTeamsSubscriptionCard(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")
        self.asset = ExportedAsset.objects.create(
            team=self.team,
            insight_id=self.insight.id,
            export_format="image/png",
            content_location="s3://bucket/test.png",
        )
        self.subscription = create_subscription(
            team=self.team,
            insight=self.insight,
            created_by=self.user,
            target_type="teams",
            target_value=VALID_TEAMS_WEBHOOK_URL,
        )

    def _card_content(self, **kwargs) -> dict:
        message = build_teams_subscription_card(self.subscription, [self.asset], 1, **kwargs)
        assert message["type"] == "message"
        attachment = message["attachments"][0]
        assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
        return attachment["content"]

    def test_card_links_the_asset_image_and_action_urls(self) -> None:
        content = self._card_content()

        assert content["version"] == "1.2"
        assert content["body"][0]["text"] == "Your subscription to the Insight **My Test subscription** is ready! 🎉"
        image = content["body"][1]
        assert image["type"] == "Image"
        assert image["url"].startswith("http://localhost:8010/exporter/")
        assert image["altText"] == "My Test subscription"
        assert content["actions"] == [
            {
                "type": "Action.OpenUrl",
                "title": "View in PostHog",
                "url": "http://localhost:8010/insights/123456?utm_source=posthog&utm_campaign=subscription_report&utm_medium=teams",
            },
            {
                "type": "Action.OpenUrl",
                "title": "Manage subscription",
                "url": f"http://localhost:8010/insights/123456/subscriptions/{self.subscription.id}?utm_source=posthog&utm_campaign=subscription_report&utm_medium=teams",
            },
        ]

    def test_capped_assets_get_a_trailer_pointing_at_the_rest(self) -> None:
        message = build_teams_subscription_card(self.subscription, [self.asset], 4)
        trailer = message["attachments"][0]["content"]["body"][-1]

        assert trailer["type"] == "TextBlock"
        assert trailer["text"].startswith("Showing 1 of 4 insights.")

    def test_failed_asset_renders_as_text_not_a_broken_image(self) -> None:
        self.asset.content_location = None
        self.asset.exception = "Query timed out"
        self.asset.save()

        content = self._card_content()
        block = content["body"][1]

        assert block["type"] == "TextBlock"
        assert "Query timed out" in block["text"]

    def test_change_summary_is_placed_above_the_charts(self) -> None:
        content = self._card_content(change_summary="Signups doubled")

        assert content["body"][1]["text"] == "**AI summary**\n\nSignups doubled"
        assert content["body"][2]["type"] == "Image"
