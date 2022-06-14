from unittest.mock import patch

from rest_framework import status

from posthog.models.dashboard import Dashboard
from posthog.models.filters.filter import Filter
from posthog.models.insight import Insight
from posthog.models.subscription import Subscription
from posthog.test.base import APIBaseTest


@patch("posthog.api.subscription.subscriptions")
class TestSubscription(APIBaseTest):
    subscription: Subscription = None  # type: ignore
    dashboard: Dashboard = None  # type: ignore
    insight: Insight = None  # type: ignore

    insight_filter_dict = {
        "events": [{"id": "$pageview"}],
        "properties": [{"key": "$browser", "value": "Mac OS X"}],
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.dashboard = Dashboard.objects.create(team=cls.team, name="example dashboard", created_by=cls.user)
        cls.insight = Insight.objects.create(
            filters=Filter(data=cls.insight_filter_dict).to_dict(), team=cls.team, created_by=cls.user
        )

    def _create_subscription(self, **kwargs):
        payload = {
            "insight": self.insight.id,
            "target_type": "email",
            "target_value": "test@posthog.com",
            "frequency": "weekly",
            "interval": 1,
            "start_date": "2022-01-01T00:00:00",
            "title": "My Subscription",
            "invite_message": "hey there!",
        }

        payload.update(kwargs)
        return self.client.post(f"/api/projects/{self.team.id}/subscriptions", payload)

    def test_can_create_new_subscription(self, mock_subscription_tasks):
        response = self._create_subscription()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(
            data,
            {
                "id": data["id"],
                "dashboard": None,
                "insight": self.insight.id,
                "target_type": "email",
                "target_value": "test@posthog.com",
                "frequency": "weekly",
                "interval": 1,
                "byweekday": None,
                "bysetpos": None,
                "count": None,
                "start_date": "2022-01-01T00:00:00Z",
                "until_date": None,
                "created_at": data["created_at"],
                "created_by": data["created_by"],
                "deleted": False,
                "title": "My Subscription",
                "next_delivery_date": data["next_delivery_date"],
                "invite_message": None,
            },
        )

        mock_subscription_tasks.deliver_new_subscription.delay.assert_called_once_with(
            data["id"], ["test@posthog.com"], "hey there!"
        )

    def test_can_create_new_subscription_without_invite_message(self, mock_subscription_tasks):
        response = self._create_subscription(invite_message=None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()

        mock_subscription_tasks.deliver_new_subscription.delay.assert_called_once_with(
            data["id"], ["test@posthog.com"], None
        )

    def test_can_update_existing_subscription(self, mock_subscription_tasks):
        response = self._create_subscription(invite_message=None)
        data = response.json()

        mock_subscription_tasks.deliver_new_subscription.delay.assert_called_once_with(
            data["id"], ["test@posthog.com"], None
        )

        mock_subscription_tasks.deliver_new_subscription.delay.reset_mock()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{data['id']}",
            {"target_value": "test@posthog.com,new_user@posthog.com", "invite_message": "hi new user"},
        )
        updated_data = response.json()
        assert updated_data["target_value"] == "test@posthog.com,new_user@posthog.com"

        mock_subscription_tasks.deliver_new_subscription.delay.assert_called_once_with(
            data["id"], ["new_user@posthog.com"], "hi new user"
        )
