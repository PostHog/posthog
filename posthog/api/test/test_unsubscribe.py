from posthog.test.base import BaseTest

from posthog.tasks.email import NotificationSetting, get_notification_unsubscribe_token


class TestNotificationUnsubscribe(BaseTest):
    def test_valid_token_disables_the_setting_without_login(self) -> None:
        self.client.logout()
        token = get_notification_unsubscribe_token(self.user.id, NotificationSetting.PLUGIN_DISABLED.value)

        response = self.client.get(f"/api/notification_unsubscribe?token={token}")

        assert response.status_code == 200
        self.user.refresh_from_db()
        assert self.user.notification_settings["plugin_disabled"] is False

    def test_invalid_token_does_not_change_settings(self) -> None:
        response = self.client.get("/api/notification_unsubscribe?token=not-a-real-token")

        assert response.status_code == 400
        self.user.refresh_from_db()
        assert self.user.notification_settings["plugin_disabled"] is True

    def test_missing_token_returns_error(self) -> None:
        response = self.client.get("/api/notification_unsubscribe")

        assert response.status_code == 400
