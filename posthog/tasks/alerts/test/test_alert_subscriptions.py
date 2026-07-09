from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import ChartDisplayType, EventsNode, TrendsFilter, TrendsQuery

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import User
from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import Organization, OrganizationMembership
from posthog.tasks.alerts.utils import send_notifications_for_breaches
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.alerts.backend.models import AlertCheck, AlertConfiguration, AlertSubscription


@freeze_time("2024-06-02T08:55:00.000Z")
class TestAlertSubscriptionOrgMembership(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        self.insight = self.dashboard_api.create_insight(data={"name": "insight", "query": query_dict})[1]
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")

        self.alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id, self.other_user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 0}}},
            },
        ).json()

    def test_get_subscribed_users_emails_excludes_removed_members(self) -> None:
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])

        emails = alert.get_subscribed_users_emails()
        assert sorted(emails) == sorted(["user1@posthog.com", "other@posthog.com"])

        OrganizationMembership.objects.filter(user=self.other_user, organization=self.organization).delete()

        emails = alert.get_subscribed_users_emails()
        assert sorted(emails) == ["user1@posthog.com"]

    def test_membership_deletion_removes_alert_subscriptions(self) -> None:
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])
        assert AlertSubscription.objects.filter(alert_configuration=alert, user=self.other_user).exists()

        OrganizationMembership.objects.filter(user=self.other_user, organization=self.organization).delete()

        assert not AlertSubscription.objects.filter(alert_configuration=alert, user=self.other_user).exists()
        assert AlertSubscription.objects.filter(alert_configuration=alert, user=self.user).exists()

    @patch("posthog.tasks.alerts.utils.EmailMessage")
    def test_send_notifications_excludes_removed_members(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])

        OrganizationMembership.objects.filter(user=self.other_user, organization=self.organization).delete()

        alert_check = AlertCheck.objects.create(
            alert_configuration=alert,
            calculated_value=1.0,
            condition=alert.condition,
            targets_notified={},
            state="firing",
        )
        with patch("posthog.tasks.alerts.utils.produce_internal_event"):
            send_notifications_for_breaches(
                alert, alert_check, ["test breach"], idempotency_key="test-excludes-removed-members"
            )

        assert len(mocked_email_messages) == 1
        email = mocked_email_messages[0]
        assert len(email.to) == 1
        assert email.to[0]["recipient"] == "user1@posthog.com"


@freeze_time("2024-06-02T08:55:00.000Z")
class TestGetSubscribedUsersEmails(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        self.insight = self.dashboard_api.create_insight(data={"name": "insight", "query": query_dict})[1]

        self.alert_response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 0}}},
            },
        ).json()

        self.alert = AlertConfiguration.objects.get(pk=self.alert_response["id"])

    def test_filters_out_user_from_different_org_with_stale_subscription(self) -> None:
        other_org = Organization.objects.create(name="Other Org")
        outsider = User.objects.create_and_join(other_org, "outsider@other.com", "password")

        AlertSubscription.objects.create(alert_configuration=self.alert, user=outsider)

        emails = self.alert.get_subscribed_users_emails()
        assert sorted(emails) == ["user1@posthog.com"]

    def test_includes_user_who_is_in_multiple_orgs_including_alerts_org(self) -> None:
        other_org = Organization.objects.create(name="Other Org")
        multi_org_user = User.objects.create_and_join(self.organization, "multi@posthog.com", "password")
        OrganizationMembership.objects.create(user=multi_org_user, organization=other_org)

        AlertSubscription.objects.create(alert_configuration=self.alert, user=multi_org_user)

        emails = self.alert.get_subscribed_users_emails()
        assert sorted(emails) == ["multi@posthog.com", "user1@posthog.com"]

    def test_excludes_multi_org_user_removed_from_alerts_org(self) -> None:
        other_org = Organization.objects.create(name="Other Org")
        multi_org_user = User.objects.create_and_join(self.organization, "multi@posthog.com", "password")
        OrganizationMembership.objects.create(user=multi_org_user, organization=other_org)

        AlertSubscription.objects.create(alert_configuration=self.alert, user=multi_org_user)

        OrganizationMembership.objects.filter(user=multi_org_user, organization=self.organization).delete()

        emails = self.alert.get_subscribed_users_emails()
        assert sorted(emails) == ["user1@posthog.com"]

    def test_returns_empty_list_when_no_subscribers_are_org_members(self) -> None:
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).delete()

        emails = self.alert.get_subscribed_users_emails()
        assert emails == []


@freeze_time("2024-06-02T08:55:00.000Z")
class TestAlertEmailNotifications(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        self.insight = self.dashboard_api.create_insight(data={"name": "insight", "query": query_dict})[1]

        self.alert = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "alert name",
                "insight": self.insight["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 0}}},
            },
        ).json()

    @patch("posthog.tasks.alerts.utils.EmailMessage")
    def test_send_emails(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        alert = AlertConfiguration.objects.get(pk=self.alert["id"])
        alert_check = AlertCheck.objects.create(
            alert_configuration=alert,
            calculated_value=42.0,
            condition=alert.condition,
            targets_notified={},
            state="firing",
        )
        with patch("posthog.tasks.alerts.utils.produce_internal_event"):
            send_notifications_for_breaches(
                alert,
                alert_check,
                ["first anomaly description", "second anomaly description"],
                idempotency_key="test-send-emails",
            )

        assert len(mocked_email_messages) == 1
        email = mocked_email_messages[0]
        assert len(email.to) == 1
        assert email.to[0]["recipient"] == "user1@posthog.com"
        assert "first anomaly description" in email.html_body
        assert "second anomaly description" in email.html_body


@freeze_time("2024-06-02T08:55:00.000Z")
class TestInsightAlertFiringBreachContext(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

        query_dict = TrendsQuery(
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
        ).model_dump()

        _, self.insight_data = self.dashboard_api.create_insight(data={"name": "test insight", "query": query_dict})
        _, self.dashboard_data = self.dashboard_api.create_dashboard({"name": "test dashboard"})
        self.dashboard_api.add_insight_to_dashboard(
            dashboard_ids=[self.dashboard_data["id"]],
            insight_id=self.insight_data["id"],
        )

        alert_response = self.client.post(
            f"/api/projects/{self.team.id}/alerts",
            data={
                "name": "breach context alert",
                "insight": self.insight_data["id"],
                "subscribed_users": [self.user.id],
                "calculation_interval": "daily",
                "config": {"type": "TrendsAlertConfig", "series_index": 0},
                "condition": {"type": "absolute_value"},
                "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 1.0, "upper": 5.0}}},
            },
        ).json()
        self.alert = AlertConfiguration.objects.get(pk=alert_response["id"])
        self.alert_check = AlertCheck.objects.create(
            alert_configuration=self.alert,
            calculated_value=7.5,
            condition=self.alert.condition,
            targets_notified={},
            state="firing",
        )

    @patch("posthog.tasks.alerts.utils.produce_internal_event")
    @patch("posthog.tasks.alerts.utils.EmailMessage")
    def test_insight_alert_firing_event_carries_breach_context(
        self, MockEmailMessage: MagicMock, mock_produce: MagicMock
    ) -> None:
        send_notifications_for_breaches(
            self.alert,
            self.alert_check,
            ["value 7.5 above upper threshold 5.0"],
            idempotency_key=str(self.alert_check.id),
        )

        mock_produce.assert_called_once()
        event_arg = mock_produce.call_args.kwargs["event"]
        props = event_arg.properties

        assert props["alert_check_id"] == str(self.alert_check.id)
        assert props["calculated_value"] == 7.5
        assert props["threshold_lower"] == 1.0
        assert props["threshold_upper"] == 5.0
        assert props["dashboard_ids"] == [self.dashboard_data["id"]]
