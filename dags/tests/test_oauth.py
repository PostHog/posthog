import unittest.mock
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
import dagster
from freezegun import freeze_time

from dags.oauth import (
    clear_expired_oauth_tokens,
    oauth_clear_expired_oauth_tokens_job,
    batch_delete_model,
    clear_expired_tokens_by_type,
)
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthGrant, OAuthRefreshToken
from posthog.models import Organization, User
from django.db.models import Q


class TestOAuthTokenCleanup(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.user = User.objects.create(email="test@example.com")
        self.oauth_application = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )

    @freeze_time("2023-01-15 02:00:00")
    def test_oauth_cleanup_job_with_real_tokens(self):
        expired_time = timezone.now() - timedelta(days=95)  # Beyond retention period
        OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="expired_job_test_token",
            expires=expired_time,
            scope="read write",
        )

        future_time = timezone.now() + timedelta(hours=1)
        valid_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="valid_job_test_token",
            expires=future_time,
            scope="read write",
        )

        initial_count = OAuthAccessToken.objects.count()
        self.assertEqual(initial_count, 2)

        result = oauth_clear_expired_oauth_tokens_job.execute_in_process()

        self.assertTrue(result.success)

        final_count = OAuthAccessToken.objects.count()
        self.assertLess(final_count, initial_count)

        self.assertTrue(OAuthAccessToken.objects.filter(id=valid_token.id).exists())


class TestBatchDeleteFunctionality(TestCase):
    """Test the new DRY batch delete functionality."""

    def setUp(self):
        """Set up test data."""
        self.organization = Organization.objects.create(name="Test Org")
        self.user = User.objects.create(email="test@example.com")
        self.oauth_application = OAuthApplication.objects.create(
            name="Test App",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            organization=self.organization,
            algorithm="RS256",
        )

    @override_settings(CLEAR_EXPIRED_TOKENS_BATCH_SIZE=2, CLEAR_EXPIRED_TOKENS_BATCH_INTERVAL=0.01)
    def test_batch_delete_model_with_small_batches(self):
        """Test batch deletion with small batch sizes."""
        # Create multiple expired tokens
        expired_time = timezone.now() - timedelta(hours=1)
        tokens = []
        for i in range(5):
            token = OAuthAccessToken.objects.create(
                user=self.user,
                application=self.oauth_application,
                token=f"expired_token_{i}",
                expires=expired_time,
                scope="read write",
            )
            tokens.append(token)

        # Test batch delete
        query = Q(expires__lt=timezone.now())
        queryset = OAuthAccessToken.objects.filter(query)
        context = dagster.build_op_context()

        deleted_count = batch_delete_model(queryset, query, context, "test_tokens")

        # Verify all tokens were deleted
        self.assertEqual(deleted_count, 5)
        self.assertEqual(OAuthAccessToken.objects.count(), 0)

    def test_batch_delete_model_with_no_tokens(self):
        """Test batch deletion when no tokens match the query."""
        query = Q(expires__lt=timezone.now() - timedelta(days=1))
        queryset = OAuthAccessToken.objects.filter(query)
        context = dagster.build_op_context()

        deleted_count = batch_delete_model(queryset, query, context, "test_tokens")

        self.assertEqual(deleted_count, 0)

    def test_clear_expired_tokens_by_type_multiple_queries(self):
        """Test clearing tokens by type with multiple query types."""
        now = timezone.now()
        past_time = now - timedelta(hours=2)

        # Create tokens with different expiry scenarios
        expired_access_token = OAuthAccessToken.objects.create(
            user=self.user, application=self.oauth_application, token="expired_access", expires=past_time, scope="read"
        )

        # Create a refresh token without access token (standalone)
        expired_refresh_token = OAuthRefreshToken.objects.create(
            user=self.user, application=self.oauth_application, token="expired_refresh", revoked=past_time
        )

        valid_access_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="valid_access",
            expires=now + timedelta(hours=1),
            scope="read write",
        )

        # Test clearing by type
        context = dagster.build_op_context()

        # Test access tokens
        access_token_queries = {
            "expired_standalone": Q(refresh_token__isnull=True, expires__lt=now),
        }
        access_results = clear_expired_tokens_by_type(OAuthAccessToken, access_token_queries, context)

        # Test refresh tokens
        refresh_token_queries = {
            "revoked": Q(revoked__lt=now),
        }
        refresh_results = clear_expired_tokens_by_type(OAuthRefreshToken, refresh_token_queries, context)

        # Verify results
        self.assertEqual(access_results["expired_standalone"], 1)
        self.assertEqual(refresh_results["revoked"], 1)

        # Verify expired tokens are gone but valid ones remain
        self.assertFalse(OAuthAccessToken.objects.filter(id=expired_access_token.id).exists())
        self.assertFalse(OAuthRefreshToken.objects.filter(id=expired_refresh_token.id).exists())
        self.assertTrue(OAuthAccessToken.objects.filter(id=valid_access_token.id).exists())

    @override_settings(OAUTH_EXPIRED_TOKEN_RETENTION_PERIOD=3600)  # 1 hour
    def test_clear_expired_oauth_tokens_with_custom_retention(self):
        """Test the full cleanup function with custom retention period."""
        now = timezone.now()
        cutoff_time = now - timedelta(hours=2)  # Beyond retention period
        recent_time = now - timedelta(minutes=30)  # Within retention period

        # Create tokens at different times
        old_access_token = OAuthAccessToken.objects.create(
            user=self.user, application=self.oauth_application, token="old_access", expires=cutoff_time, scope="read"
        )

        recent_expired_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="recent_expired",
            expires=recent_time,
            scope="read",
        )

        old_grant = OAuthGrant.objects.create(
            user=self.user,
            application=self.oauth_application,
            code="old_grant",
            expires=cutoff_time,
            redirect_uri="https://example.com/callback",
            code_challenge="old_challenge",
            code_challenge_method="S256",
        )

        context = dagster.build_op_context()

        clear_expired_oauth_tokens(context)

        self.assertFalse(OAuthAccessToken.objects.filter(id=old_access_token.id).exists())
        self.assertTrue(OAuthAccessToken.objects.filter(id=recent_expired_token.id).exists())
        self.assertFalse(OAuthGrant.objects.filter(id=old_grant.id).exists())

    @unittest.mock.patch("dags.oauth.batch_delete_model")
    def test_clear_expired_oauth_tokens_metadata_output(self, mock_batch_delete):
        mock_batch_delete.return_value = 5

        context = dagster.build_op_context()
        clear_expired_oauth_tokens(context)

        self.assertTrue(mock_batch_delete.called)

    def test_token_cleanup_comprehensive_scenario(self):
        now = timezone.now()
        ninety_five_days_ago = now - timedelta(days=95)  # Beyond default retention
        one_day_ago = now - timedelta(days=1)  # Within default retention
        in_one_hour = now + timedelta(hours=1)

        tokens_to_delete = []
        tokens_to_keep = []

        # Old expired access token (should be deleted)
        old_access = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="old_access",
            expires=ninety_five_days_ago,
            scope="read",
        )
        tokens_to_delete.append(("OAuthAccessToken", old_access.id))

        # Recent expired access token (should be kept due to retention)
        recent_access = OAuthAccessToken.objects.create(
            user=self.user, application=self.oauth_application, token="recent_access", expires=one_day_ago, scope="read"
        )
        tokens_to_keep.append(("OAuthAccessToken", recent_access.id))

        # Valid access token (should be kept)
        valid_access = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token="valid_access",
            expires=in_one_hour,
            scope="read write",
        )
        tokens_to_keep.append(("OAuthAccessToken", valid_access.id))

        # Old expired grant (should be deleted)
        old_grant = OAuthGrant.objects.create(
            user=self.user,
            application=self.oauth_application,
            code="old_grant",
            expires=ninety_five_days_ago,
            redirect_uri="https://example.com/callback",
            code_challenge="old_challenge",
            code_challenge_method="S256",
        )
        tokens_to_delete.append(("OAuthGrant", old_grant.id))

        # Valid grant (should be kept)
        valid_grant = OAuthGrant.objects.create(
            user=self.user,
            application=self.oauth_application,
            code="valid_grant",
            expires=in_one_hour,
            redirect_uri="https://example.com/callback",
            code_challenge="valid_challenge",
            code_challenge_method="S256",
        )
        tokens_to_keep.append(("OAuthGrant", valid_grant.id))

        # Old revoked refresh token (should be deleted)
        old_refresh = OAuthRefreshToken.objects.create(
            user=self.user, application=self.oauth_application, token="old_refresh", revoked=ninety_five_days_ago
        )
        tokens_to_delete.append(("OAuthRefreshToken", old_refresh.id))

        # Valid refresh token (should be kept)
        valid_refresh = OAuthRefreshToken.objects.create(
            user=self.user, application=self.oauth_application, token="valid_refresh"
        )
        tokens_to_keep.append(("OAuthRefreshToken", valid_refresh.id))

        # Run cleanup
        context = dagster.build_op_context()
        clear_expired_oauth_tokens(context)

        # Verify tokens to delete are gone
        for model_name, token_id in tokens_to_delete:
            if model_name == "OAuthAccessToken":
                self.assertFalse(OAuthAccessToken.objects.filter(id=token_id).exists())
            elif model_name == "OAuthGrant":
                self.assertFalse(OAuthGrant.objects.filter(id=token_id).exists())
            elif model_name == "OAuthRefreshToken":
                self.assertFalse(OAuthRefreshToken.objects.filter(id=token_id).exists())

        # Verify tokens to keep are still there
        for model_name, token_id in tokens_to_keep:
            if model_name == "OAuthAccessToken":
                self.assertTrue(OAuthAccessToken.objects.filter(id=token_id).exists())
            elif model_name == "OAuthGrant":
                self.assertTrue(OAuthGrant.objects.filter(id=token_id).exists())
            elif model_name == "OAuthRefreshToken":
                self.assertTrue(OAuthRefreshToken.objects.filter(id=token_id).exists())
