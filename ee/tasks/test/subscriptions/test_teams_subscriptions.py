from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight

from ee.tasks.subscriptions.subscription_utils import MAX_INSIGHTS, TRUNCATION_MARKER
from ee.tasks.subscriptions.teams_subscriptions import TEAMS_CARD_TEXT_BUDGET, build_teams_subscription_card
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

    def test_external_links_in_subscription_and_resource_names_are_defanged(self) -> None:
        self.subscription.title = "[Open report](https://attacker.example/login)"
        self.subscription.save(update_fields=["title"])
        self.insight.name = "[Quarterly report](https://evil.example.com/report)"
        self.insight.save(update_fields=["name"])

        content = self._card_content()

        assert content["body"][0]["text"] == (
            "Your subscription to **Open report** (Insight: Quarterly report) is ready! 🎉"
        )

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

    def test_failed_asset_external_links_are_defanged(self) -> None:
        self.insight.name = "[Quarterly report](https://evil.example.com/report)"
        self.insight.save(update_fields=["name"])
        self.asset.content_location = None
        self.asset.exception = "[Retry here](https://attacker.example/login)"
        self.asset.save()

        content = self._card_content()
        block = content["body"][1]

        assert "**Quarterly report**" in block["text"]
        assert "There was an error generating your asset: Retry here" in block["text"]
        assert "evil.example.com" not in block["text"]
        assert "attacker.example" not in block["text"]

    def test_a_first_delivery_says_the_channel_is_now_subscribed(self) -> None:
        content = self._card_content(is_new_subscription=True)

        assert content["body"][0]["text"].startswith(
            "This channel has been subscribed to the Insight **My Test subscription** on PostHog!"
        )

    def test_a_summary_skipped_over_budget_says_so_in_subtle_text(self) -> None:
        content = self._card_content(summary_skipped_over_budget=True)
        notice = content["body"][1]

        assert notice["isSubtle"] is True
        assert "Your organization has reached its AI credit usage limit." in notice["text"]
        assert "[Billing settings](" in notice["text"]

    def test_change_summary_is_placed_above_the_charts(self) -> None:
        content = self._card_content(change_summary="Signups doubled")

        assert content["body"][1]["text"] == "**AI summary**\n\nSignups doubled"
        assert content["body"][2]["type"] == "Image"

    def test_change_summary_links_are_defanged(self) -> None:
        content = self._card_content(change_summary="Signups doubled, see [why](https://evil.example.com/x)")

        assert "evil.example.com" not in str(content)

    @parameterized.expand(
        [
            ("single_byte_error_text", "detail "),
            # Three bytes per character, so a card that fits the budget by character count is over
            # it by the byte count Teams measures.
            ("multi_byte_error_text", "詳細 "),
        ]
    )
    def test_a_run_where_every_asset_failed_stays_inside_the_card_budget(self, _label, filler) -> None:
        failed_assets = [
            ExportedAsset.objects.create(
                team=self.team,
                insight_id=self.insight.id,
                export_format="image/png",
                exception="Query timed out. " + filler * 1000,
            )
            for _ in range(MAX_INSIGHTS)
        ]

        card = build_teams_subscription_card(self.subscription, failed_assets, MAX_INSIGHTS)
        body = card["attachments"][0]["content"]["body"]
        shown = sum(1 for element in body if "Query timed out." in element.get("text", ""))

        assert sum(len(element.get("text", "").encode("utf-8")) for element in body) <= TEAMS_CARD_TEXT_BUDGET
        assert shown < MAX_INSIGHTS
        assert body[-1]["text"].startswith(f"Showing {shown} of {MAX_INSIGHTS} insights.")

    def test_an_oversized_multi_byte_summary_is_truncated_within_the_byte_budget(self) -> None:
        content = self._card_content(change_summary="詳" * TEAMS_CARD_TEXT_BUDGET)
        summary = content["body"][1]["text"]

        assert len(summary.encode("utf-8")) <= TEAMS_CARD_TEXT_BUDGET
        assert summary.endswith(TRUNCATION_MARKER)
