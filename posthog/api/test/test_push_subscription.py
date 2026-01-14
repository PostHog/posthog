import json

from posthog.test.base import BaseTest

from django.test import Client

from products.workflows.backend.models.push_subscription import PushPlatform, PushSubscription


class TestPushSubscriptionAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.team = self.organization.teams.first()
        if not self.team:
            raise ValueError("Test requires a team")
        self.client = Client()

    def test_sdk_register_push_subscription_success(self):
        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "android",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "ok")
        self.assertIn("subscription_id", data)

        subscription = PushSubscription.objects.get(
            team=self.team,
            distinct_id="user-123",
            token_hash=PushSubscription._hash_token("fcm-token-abc123"),
        )
        self.assertEqual(subscription.distinct_id, "user-123")
        self.assertEqual(subscription.platform, PushPlatform.ANDROID)
        self.assertTrue(subscription.is_active)

    def test_sdk_register_push_subscription_ios(self):
        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "apns-token-xyz789",
            "platform": "ios",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        subscription = PushSubscription.objects.get(
            team=self.team,
            distinct_id="user-123",
            token_hash=PushSubscription._hash_token("apns-token-xyz789"),
        )
        self.assertEqual(subscription.distinct_id, "user-123")
        self.assertEqual(subscription.platform, PushPlatform.IOS)

    def test_sdk_register_allows_same_token_for_multiple_distinct_ids(self):
        payload_1 = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "android",
        }
        payload_2 = {
            "api_key": self.team.api_token,
            "distinct_id": "user-456",
            "token": "fcm-token-abc123",
            "platform": "android",
        }

        response_1 = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload_1),
            content_type="application/json",
        )
        response_2 = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload_2),
            content_type="application/json",
        )

        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_2.status_code, 200)

        self.assertEqual(
            PushSubscription.objects.filter(
                team=self.team, token_hash=PushSubscription._hash_token("fcm-token-abc123")
            ).count(),
            2,
        )

    def test_sdk_register_push_subscription_missing_api_key(self):
        payload = {
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "android",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("api_key is required", data["error"])

    def test_sdk_register_push_subscription_invalid_api_key(self):
        payload = {
            "api_key": "invalid-token",
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "android",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        data = json.loads(response.content)
        self.assertIn("Invalid API key", data["error"])

    def test_sdk_register_push_subscription_missing_distinct_id(self):
        payload = {
            "api_key": self.team.api_token,
            "token": "fcm-token-abc123",
            "platform": "android",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("distinct_id is required", data["error"])

    def test_sdk_register_push_subscription_missing_token(self):
        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "platform": "android",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("token is required", data["error"])

    def test_sdk_register_push_subscription_missing_platform(self):
        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("platform is required", data["error"])

    def test_sdk_register_push_subscription_invalid_platform(self):
        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "invalid",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn("Invalid platform", data["error"])

    def test_sdk_register_push_subscription_updates_existing(self):
        subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=False,
        )

        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "ios",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertEqual(subscription.platform, PushPlatform.IOS)

    def test_sdk_register_push_subscription_cors_headers(self):
        payload = {
            "api_key": self.team.api_token,
            "distinct_id": "user-123",
            "token": "fcm-token-abc123",
            "platform": "android",
        }

        response = self.client.post(
            "/api/sdk/push_subscriptions/register/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_ORIGIN="https://example.com",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Access-Control-Allow-Origin", response)

    def test_sdk_register_push_subscription_options_request(self):
        response = self.client.options(
            "/api/sdk/push_subscriptions/register/",
            HTTP_ORIGIN="https://example.com",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Access-Control-Allow-Origin", response)
