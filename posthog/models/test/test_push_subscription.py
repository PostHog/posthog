from posthog.test.base import BaseTest

from products.workflows.backend.models.push_subscription import PushPlatform, PushSubscription


class TestPushSubscription(BaseTest):
    def setUp(self):
        super().setUp()
        team = self.organization.teams.first()
        if not team:
            raise ValueError("Test requires a team")
        self.team = team

    def test_create_push_subscription(self):
        subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
        )

        self.assertEqual(subscription.distinct_id, "user-123")
        self.assertEqual(subscription.token, "fcm-token-abc123")
        self.assertEqual(subscription.token_hash, PushSubscription._hash_token("fcm-token-abc123"))
        self.assertEqual(subscription.platform, PushPlatform.ANDROID)
        self.assertTrue(subscription.is_active)
        self.assertIsNotNone(subscription.id)

    def test_upsert_token_creates_new(self):
        subscription = PushSubscription.upsert_token(
            team_id=self.team.id,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
        )

        self.assertEqual(subscription.distinct_id, "user-123")
        self.assertEqual(subscription.token, "fcm-token-abc123")
        self.assertEqual(subscription.platform, PushPlatform.ANDROID)
        self.assertTrue(subscription.is_active)

    def test_upsert_token_updates_existing(self):
        subscription1 = PushSubscription.upsert_token(
            team_id=self.team.id,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
        )

        subscription1.is_active = False
        subscription1.save()

        subscription2 = PushSubscription.upsert_token(
            team_id=self.team.id,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.IOS,
        )

        self.assertEqual(subscription1.id, subscription2.id)
        self.assertTrue(subscription2.is_active)
        self.assertEqual(subscription2.platform, PushPlatform.IOS)

    def test_get_active_tokens_for_distinct_id(self):
        PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="token-1",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )
        PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="token-2",
            platform=PushPlatform.IOS,
            is_active=True,
        )
        PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="token-3",
            platform=PushPlatform.ANDROID,
            is_active=False,
        )

        active_tokens = PushSubscription.get_active_tokens_for_distinct_id(
            team_id=self.team.id,
            distinct_id="user-123",
        )

        self.assertEqual(len(active_tokens), 2)
        token_platforms = {token.platform for token in active_tokens}
        self.assertEqual(token_platforms, {PushPlatform.ANDROID, PushPlatform.IOS})

    def test_get_active_tokens_for_distinct_id_with_platform_filter(self):
        PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="token-1",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )
        PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="token-2",
            platform=PushPlatform.IOS,
            is_active=True,
        )

        android_tokens = PushSubscription.get_active_tokens_for_distinct_id(
            team_id=self.team.id,
            distinct_id="user-123",
            platform=PushPlatform.ANDROID,
        )

        self.assertEqual(len(android_tokens), 1)
        self.assertEqual(android_tokens[0].platform, PushPlatform.ANDROID)

    def test_deactivate_token(self):
        subscription_1 = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )
        subscription_2 = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-456",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )

        count = PushSubscription.deactivate_token(team_id=self.team.id, token="fcm-token-abc123")

        self.assertEqual(count, 2)
        subscription_1.refresh_from_db()
        subscription_2.refresh_from_db()
        self.assertFalse(subscription_1.is_active)
        self.assertFalse(subscription_2.is_active)
        self.assertEqual(subscription_1.disabled_reason, "unregistered")
        self.assertEqual(subscription_2.disabled_reason, "unregistered")

    def test_deactivate_token_nonexistent(self):
        count = PushSubscription.deactivate_token(team_id=self.team.id, token="nonexistent-token")
        self.assertEqual(count, 0)

    def test_str_representation(self):
        subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            is_active=True,
        )

        self.assertIn("user-123", str(subscription))
        self.assertIn("android", str(subscription).lower())
        self.assertIn("active", str(subscription).lower())

    def test_upsert_token_ignores_upload_when_existing_has_person_id(self):
        # person_id stores Person ID (from posthog_person table)
        person_id = 12345
        existing_subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            person_id=person_id,
        )

        original_updated_at = existing_subscription.updated_at

        # Try to upload same token without person_id
        result = PushSubscription.upsert_token(
            team_id=self.team.id,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.IOS,  # Different platform, but should be ignored
            person_id=None,
        )

        # Should return existing subscription without updating
        self.assertEqual(existing_subscription.id, result.id)
        self.assertEqual(result.person_id, person_id)
        existing_subscription.refresh_from_db()
        self.assertEqual(existing_subscription.updated_at, original_updated_at)

    def test_upsert_token_allows_update_when_providing_person_id(self):
        import time

        # person_id stores Person ID (from posthog_person table)
        person_id_1 = 12345
        person_id_2 = 67890

        existing_subscription = PushSubscription.objects.create(
            team=self.team,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.ANDROID,
            person_id=person_id_1,
        )

        original_updated_at = existing_subscription.updated_at
        time.sleep(0.01)  # Small delay to ensure timestamp difference

        # Upload with different person_id should update
        result = PushSubscription.upsert_token(
            team_id=self.team.id,
            distinct_id="user-123",
            token="fcm-token-abc123",
            platform=PushPlatform.IOS,
            person_id=person_id_2,
        )

        self.assertEqual(existing_subscription.id, result.id)
        self.assertEqual(result.person_id, person_id_2)
        self.assertGreater(result.updated_at, original_updated_at)
