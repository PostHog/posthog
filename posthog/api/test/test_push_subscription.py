import json

from posthog.test.base import APIBaseTest, BaseTest

from django.test import Client

from rest_framework import status

from posthog.api.push_subscription import PushSubscriptionSerializer

from products.workflows.backend.models.push_subscription import PushPlatform, PushSubscription


class TestPushSubscriptionAPI(BaseTest):
    def setUp(self):
        super().setUp()
        team = self.organization.teams.first()
        if not team:
            raise ValueError("Test requires a team")
        self.team = team
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


class TestPushSubscriptionViewSet(APIBaseTest):
    """Tests for PushSubscriptionViewSet endpoints."""

    def test_viewset_register_success(self):
        """Test register action creates a new subscription and excludes token."""
        response = self.client.post(
            f"/api/environments/{self.team.id}/push_subscriptions/register/",
            data={
                "distinct_id": "user-123",
                "token": "fcm-token-abc123",
                "platform": "android",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("id", data)
        self.assertEqual(data["distinct_id"], "user-123")
        self.assertNotIn("token", data)  # Security: token should never be in response

        subscription = PushSubscription.objects.get(
            team=self.team,
            distinct_id="user-123",
            token_hash=PushSubscription._hash_token("fcm-token-abc123"),
        )
        self.assertEqual(subscription.token, "fcm-token-abc123")

    def test_viewset_register_invalid_platform(self):
        """Test register action rejects invalid platform."""
        response = self.client.post(
            f"/api/environments/{self.team.id}/push_subscriptions/register/",
            data={
                "distinct_id": "user-123",
                "token": "fcm-token-abc123",
                "platform": "invalid",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid platform", response.json()["error"])

    def test_viewset_register_updates_existing(self):
        """Test register action updates existing subscription."""
        subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=False,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/push_subscriptions/register/",
            data={
                "distinct_id": "user-123",
                "token": "fcm-token-abc123",
                "platform": "ios",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)
        self.assertEqual(subscription.platform, PushPlatform.IOS)

    def test_viewset_unregister_success(self):
        """Test unregister action deactivates token."""
        subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/push_subscriptions/unregister/",
            data={"token": "fcm-token-abc123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)
        self.assertEqual(subscription.disabled_reason, "unregistered")

    def test_viewset_list_excludes_token(self):
        """Test list action excludes token from response."""
        PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/push_subscriptions/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("results", data)
        if data["results"]:
            result = data["results"][0]
            self.assertNotIn("token", result)  # Security: token must never be exposed
            self.assertNotIn("is_active", result)  # Should not return is_active
            self.assertNotIn("person_id", result)  # Should not return person_id


class TestPushSubscriptionSerializer(APIBaseTest):
    """Tests for PushSubscriptionSerializer security."""

    def test_serializer_excludes_token_in_response(self):
        """Test that serializer never includes token in response data."""
        subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
        )

        serializer = PushSubscriptionSerializer(subscription)
        data = serializer.data

        self.assertNotIn("token", data)  # Security: token must never be exposed
        self.assertIn("id", data)
        self.assertIn("distinct_id", data)
