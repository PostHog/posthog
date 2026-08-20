from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.models.insight import Insight

from ee.tasks.subscriptions.teams_subscriptions import build_teams_subscription_card, is_teams_webhook_url
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription

VALID_TEAMS_WEBHOOK_URL = (
    "https://prod-25.westeurope.logic.azure.com:443/workflows/abc123/triggers/manual/paths/invoke?sig=secret"
)


class TestTeamsWebhookUrlValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("logic_apps", VALID_TEAMS_WEBHOOK_URL),
            (
                "incoming_webhook",
                "https://acme.webhook.office.com/webhookb2/guid@guid/IncomingWebhook/hash/guid",
            ),
            ("power_automate", "https://europe.powerautomate.com/manual/paths/invoke"),
            ("flow", "https://prod-01.flow.microsoft.com/manual/paths/invoke"),
            (
                "power_platform_environment",
                "https://acme.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/abc",
            ),
        ]
    )
    def test_accepts_microsoft_webhook_url(self, _name: str, url: str) -> None:
        assert is_teams_webhook_url(url) is True

    @parameterized.expand(
        [
            # Both hostnames are registrable by anyone and satisfy the unescaped-dot patterns in the
            # CDP Teams template. They must not satisfy these.
            ("lookalike_power_automate", "https://evilpowerautomate.com/x"),
            ("lookalike_flow", "https://aaaflow-microsoft.com/y"),
            ("suffix_in_path", "https://evil.example.com/logic.azure.com/workflows/abc"),
            ("subdomain_prefix", "https://logic.azure.com.evil.example.com/workflows/abc"),
            ("http_scheme", "http://prod-25.westeurope.logic.azure.com/workflows/abc"),
            ("unexpected_port", "https://prod-25.westeurope.logic.azure.com:8443/workflows/abc"),
            ("wrong_path", "https://acme.webhook.office.com/something-else/guid"),
            ("authority_confusion", "https://prod-25.westeurope.logic.azure.com\\@evil.example.com/workflows/abc"),
            ("not_a_url", "definitely not a url"),
            ("empty", ""),
        ]
    )
    def test_rejects_non_teams_url(self, _name: str, url: str) -> None:
        assert is_teams_webhook_url(url) is False


class TestTeamsSubscriptionCard(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, name="Weekly numbers", created_by=self.user)
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
