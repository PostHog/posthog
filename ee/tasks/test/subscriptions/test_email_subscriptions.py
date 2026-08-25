import uuid
import smtplib

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.email import EmailDeliveryError
from posthog.models.instance_setting import set_instance_setting
from posthog.models.messaging import MessagingRecord, get_email_hashes
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.models.subscription import Subscription
from products.product_analytics.backend.facade.models import Insight

from ee.tasks.subscriptions.email_subscriptions import send_email_subscription_report
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


def mock_ee_email_messages(MockEmailMessage: MagicMock):
    return mock_email_messages(MockEmailMessage, path="ee/tasks/test/__emails__/")


@patch("ee.tasks.subscriptions.email_subscriptions.EmailMessage")
@freeze_time("2022-02-02T08:55:00.000Z")
class TestEmailSubscriptionsTasks(APIBaseTest):
    subscription: Subscription
    dashboard: Dashboard
    insight: Insight
    asset: ExportedAsset

    def setUp(self) -> None:
        self.dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        self.insight = Insight.objects.create(team=self.team, short_id="123456", name="My Test subscription")

        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

        self.asset = ExportedAsset.objects.create(
            team=self.team,
            insight_id=self.insight.id,
            export_format="image/png",
            content_location="s3://bucket/test.png",
        )
        self.subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)

    def test_subscription_delivery(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report("test1@posthog.com", self.subscription, [self.asset])

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert str(self.subscription.pk) in mocked_email_messages[0].campaign_key
        assert "is ready!" in mocked_email_messages[0].html_body
        assert (
            f"/exporter/export-my-test-subscription-2022-02-02-085500.png?token=ey"
            in mocked_email_messages[0].html_body
        )

    def test_new_subscription_delivery(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report(
            "test1@posthog.com",
            self.subscription,
            [self.asset],
            invite_message="My invite message",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1

        assert "has subscribed you" in mocked_email_messages[0].html_body
        assert "Someone subscribed you to a PostHog Insight" == mocked_email_messages[0].subject
        self.subscription.refresh_from_db()
        next_delivery_date = self.subscription.next_delivery_date
        assert next_delivery_date is not None
        expected_schedule_summary = (
            f"This subscription is {self.subscription.summary}. "
            f"The next subscription will be sent on "
            f"{next_delivery_date.strftime('%A %B %d, %Y')}"
        )
        assert expected_schedule_summary in mocked_email_messages[0].html_body
        assert "My invite message" in mocked_email_messages[0].html_body

    def test_should_have_different_text_for_self(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report(
            self.user.email,
            self.subscription,
            [self.asset],
            invite_message="My invite message",
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "You have been subscribed" in mocked_email_messages[0].html_body
        assert "You have been subscribed to a PostHog Insight" == mocked_email_messages[0].subject

    def test_sends_dashboard_subscription(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        subscription = create_subscription(team=self.team, dashboard=self.dashboard, created_by=self.user)

        send_email_subscription_report(
            self.user.email,
            subscription,
            [self.asset],
            invite_message="My invite message",
            total_asset_count=10,
        )

        assert len(mocked_email_messages) == 1
        assert mocked_email_messages[0].send.call_count == 1
        assert "You have been subscribed" in mocked_email_messages[0].html_body
        assert "You have been subscribed to a PostHog Dashboard" == mocked_email_messages[0].subject
        assert f"SHOWING 1 OF 10 DASHBOARD INSIGHTS" in mocked_email_messages[0].html_body

    def test_shows_summary_skipped_notice_when_over_budget(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report(
            "test1@posthog.com",
            self.subscription,
            [self.asset],
            summary_skipped_over_budget=True,
        )

        assert "AI summary skipped" in mocked_email_messages[0].html_body
        assert "AI credit usage limit" in mocked_email_messages[0].html_body
        # The notice links straight to the billing page so the user can lift the limit.
        assert "/organization/billing" in mocked_email_messages[0].html_body

    def test_no_summary_skipped_notice_when_summary_present(self, MockEmailMessage: MagicMock) -> None:
        # A generated summary renders instead of the skip notice — never both.
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        send_email_subscription_report(
            "test1@posthog.com",
            self.subscription,
            [self.asset],
            change_summary="- Pageviews trending up",
            summary_skipped_over_budget=True,
        )

        assert "AI summary:" in mocked_email_messages[0].html_body
        assert "AI summary skipped" not in mocked_email_messages[0].html_body

    def test_hides_out_of_memory_cause_in_failed_asset(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)
        oom_error = (
            "This query ran out of memory before it could finish, usually because it's scanning too "
            "much data. Try a shorter date range or narrower filters."
        )
        failed_asset = ExportedAsset.objects.create(
            team=self.team, insight_id=self.insight.id, export_format="image/png", exception=oom_error
        )

        send_email_subscription_report("test1@posthog.com", self.subscription, [failed_asset])

        body = mocked_email_messages[0].html_body
        assert "ran out of memory" not in body
        assert "shorter date range" not in body
        assert "Failed to generate content" in body

    def test_same_recipient_gets_distinct_campaign_per_subscription(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)

        insight_b = Insight.objects.create(team=self.team, short_id="789abc", name="Second insight")
        subscription_b = create_subscription(team=self.team, insight=insight_b, created_by=self.user)
        shared = "shared@posthog.com"

        send_email_subscription_report(shared, self.subscription, [self.asset])
        send_email_subscription_report(shared, subscription_b, [self.asset])

        assert len(mocked_email_messages) == 2
        assert mocked_email_messages[0].campaign_key != mocked_email_messages[1].campaign_key
        assert str(self.subscription.pk) in mocked_email_messages[0].campaign_key
        assert str(subscription_b.pk) in mocked_email_messages[1].campaign_key

    def test_delivery_id_scopes_campaign_deduplication(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)
        first_delivery_id = uuid.uuid4()
        second_delivery_id = uuid.uuid4()

        send_email_subscription_report(
            "test1@posthog.com", self.subscription, [self.asset], delivery_id=first_delivery_id
        )
        send_email_subscription_report(
            "test1@posthog.com", self.subscription, [self.asset], delivery_id=first_delivery_id
        )
        send_email_subscription_report(
            "test1@posthog.com", self.subscription, [self.asset], delivery_id=second_delivery_id
        )

        assert mocked_email_messages[0].campaign_key == mocked_email_messages[1].campaign_key
        assert mocked_email_messages[0].campaign_key != mocked_email_messages[2].campaign_key
        assert str(first_delivery_id) in mocked_email_messages[0].campaign_key
        assert str(second_delivery_id) in mocked_email_messages[2].campaign_key

    def test_invite_retries_reuse_delivery_campaign(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_ee_email_messages(MockEmailMessage)
        delivery_id = uuid.uuid4()

        for _ in range(2):
            send_email_subscription_report(
                "test1@posthog.com",
                self.subscription,
                [self.asset],
                invite_message="Welcome",
                delivery_id=delivery_id,
            )

        assert mocked_email_messages[0].campaign_key == mocked_email_messages[1].campaign_key
        assert str(delivery_id) in mocked_email_messages[0].campaign_key


@freeze_time("2022-02-02T08:55:00.000Z")
class TestEmailSubscriptionDeliveryDetection(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, short_id="detect", name="Detection insight")
        self.asset = ExportedAsset.objects.create(
            team=self.team,
            insight_id=self.insight.id,
            export_format="image/png",
            content_location="s3://bucket/test.png",
        )
        self.subscription = create_subscription(team=self.team, insight=self.insight, created_by=self.user)
        set_instance_setting("EMAIL_HOST", "localhost")
        set_instance_setting("EMAIL_ENABLED", True)

    def test_raises_when_permanent_smtp_failure_is_swallowed(self) -> None:
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=smtplib.SMTPRecipientsRefused({"bounce@posthog.com": (550, b"no such user")}),
        ):
            with self.assertRaises(EmailDeliveryError):
                send_email_subscription_report("bounce@posthog.com", self.subscription, [self.asset], send_async=False)

    def test_does_not_raise_when_delivery_recorded(self) -> None:
        send_email_subscription_report("ok@posthog.com", self.subscription, [self.asset], send_async=False)

        assert MessagingRecord.objects.filter(
            email_hash__in=get_email_hashes("ok@posthog.com"), sent_at__isnull=False
        ).exists()

    def test_raises_when_smtp_backend_accepts_no_messages(self) -> None:
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages", return_value=0):
            with self.assertRaises(EmailDeliveryError):
                send_email_subscription_report("zero@posthog.com", self.subscription, [self.asset], send_async=False)
