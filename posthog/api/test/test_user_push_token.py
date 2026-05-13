from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.user_push_token import UserPushToken
from posthog.push_notifications import send_push_to_user


class TestUserPushTokenEndpoints(APIBaseTest):
    def test_register_creates_row(self):
        response = self.client.post(
            "/api/users/@me/push_tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "ios"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["platform"], "ios")
        self.assertEqual(UserPushToken.objects.filter(user=self.user, token="ExponentPushToken[abc]").count(), 1)

    def test_register_is_idempotent_and_updates_platform(self):
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[abc]", platform="ios")

        response = self.client.post(
            "/api/users/@me/push_tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "android"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        tokens = UserPushToken.objects.filter(user=self.user, token="ExponentPushToken[abc]")
        self.assertEqual(tokens.count(), 1)
        self.assertEqual(tokens.first().platform, "android")

    def test_register_rejects_invalid_platform(self):
        response = self.client.post(
            "/api/users/@me/push_tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "blackberry"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_requires_token(self):
        response = self.client.post(
            "/api/users/@me/push_tokens/",
            {"platform": "ios"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_remove_deletes_row(self):
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[abc]", platform="ios")

        response = self.client.delete(
            "/api/users/@me/push_tokens/remove/",
            {"token": "ExponentPushToken[abc]"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserPushToken.objects.filter(user=self.user, token="ExponentPushToken[abc]").exists())

    def test_remove_unknown_token_is_a_noop(self):
        response = self.client.delete(
            "/api/users/@me/push_tokens/remove/",
            {"token": "ExponentPushToken[never-registered]"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_register_does_not_leak_across_users(self):
        other_user = self._create_user("other@example.com")
        UserPushToken.objects.create(user=other_user, token="ExponentPushToken[abc]", platform="ios")

        response = self.client.post(
            "/api/users/@me/push_tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "ios"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Both users now own a row for that token (unique together is per-user).
        self.assertEqual(UserPushToken.objects.filter(token="ExponentPushToken[abc]").count(), 2)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.logout()
        response = self.client.post(
            "/api/users/@me/push_tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "ios"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestPushNotifications(APIBaseTest):
    def _stub_response(self, *, ok: list[str], not_registered: list[str] | None = None):
        not_registered = not_registered or []
        tickets = [{"status": "ok"} for _ in ok] + [
            {"status": "error", "details": {"error": "DeviceNotRegistered"}} for _ in not_registered
        ]

        class _StubResponse:
            status_code = 200

            def json(self_inner):
                return {"data": tickets}

            @property
            def text(self_inner):
                return ""

        return _StubResponse()

    def test_send_push_to_user_returns_zero_with_no_tokens(self):
        sent = send_push_to_user(self.user, title="t", body="b")
        self.assertEqual(sent, 0)

    @patch("posthog.push_notifications.requests.post")
    def test_send_push_to_user_calls_expo(self, mock_post):
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[a]", platform="ios")
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[b]", platform="android")
        mock_post.return_value = self._stub_response(ok=["a", "b"])

        accepted = send_push_to_user(
            self.user,
            title="PostHog Code",
            body="task done",
            data={"taskId": "t1", "taskRunId": "r1"},
        )

        self.assertEqual(accepted, 2)
        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["title"], "PostHog Code")
        self.assertEqual(payload[0]["body"], "task done")
        self.assertEqual(payload[0]["data"], {"taskId": "t1", "taskRunId": "r1"})

    @patch("posthog.push_notifications.requests.post")
    def test_send_push_prunes_invalid_tokens(self, mock_post):
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[a]", platform="ios")
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[b]", platform="android")
        mock_post.return_value = self._stub_response(ok=["a"], not_registered=["b"])

        accepted = send_push_to_user(self.user, title="t", body="b")
        self.assertEqual(accepted, 1)
        remaining = list(UserPushToken.objects.filter(user=self.user).values_list("token", flat=True))
        self.assertEqual(remaining, ["ExponentPushToken[a]"])

    @patch("posthog.push_notifications.requests.post")
    def test_send_push_swallows_http_errors(self, mock_post):
        UserPushToken.objects.create(user=self.user, token="ExponentPushToken[a]", platform="ios")

        class _BadResponse:
            status_code = 500
            text = "boom"

            def json(self_inner):
                raise ValueError("not json")

        mock_post.return_value = _BadResponse()

        accepted = send_push_to_user(self.user, title="t", body="b")
        self.assertEqual(accepted, 0)
        # Token preserved — only DeviceNotRegistered prunes.
        self.assertTrue(UserPushToken.objects.filter(token="ExponentPushToken[a]").exists())
