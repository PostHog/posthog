"""
Tests for team access token cache functionality.
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from posthog.models.personal_api_key import hash_key_value
from posthog.storage.team_access_cache import (
    TeamAccessTokenCache,
    get_teams_for_personal_api_key,
    get_teams_needing_cache_refresh,
    team_access_cache,
    team_access_tokens_hypercache,
    warm_team_token_cache,
)


class TestTeamAccessTokenCache(TestCase):
    """Test the TeamAccessTokenCache class."""

    def setUp(self):
        """Set up test data."""
        self.cache = TeamAccessTokenCache(ttl=300)
        self.project_api_key = "phs_test_project_key_123"
        self.team_id = 42
        self.access_token = "phx_test_access_token_456"
        self.hashed_token = hash_key_value(self.access_token, mode="sha256")

        # Clear cache before each test
        cache.clear()
        # Also clear HyperCache
        team_access_tokens_hypercache.clear_cache(self.project_api_key)

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        # Also clear HyperCache
        team_access_tokens_hypercache.clear_cache(self.project_api_key)

    def test_cache_key_generation(self):
        """Test cache key generation via HyperCache."""
        expected_key = f"cache/team_tokens/{self.project_api_key}/team_access_tokens/access_tokens.json"
        actual_key = team_access_tokens_hypercache.get_cache_key(self.project_api_key)
        assert actual_key == expected_key

    def test_update_team_tokens(self):
        """Test updating team token list using HyperCache."""
        tokens = [
            hash_key_value("phx_token_one_123", mode="sha256"),
            hash_key_value("phx_token_two_456", mode="sha256"),
        ]

        self.cache.update_team_tokens(self.project_api_key, self.team_id, tokens)

        # Verify tokens are cached in JSON format
        cached_data = team_access_tokens_hypercache.get_from_cache(self.project_api_key)

        assert cached_data is not None
        assert cached_data["hashed_tokens"] == tokens
        assert cached_data["team_id"] == self.team_id
        assert "last_updated" in cached_data

    def test_invalidate_team(self):
        """Test invalidating team cache."""
        # Set up cache
        self.cache.update_team_tokens(self.project_api_key, self.team_id, [self.hashed_token])

        # Verify token is cached
        has_access, _ = self.cache.has_access_with_team(self.project_api_key, self.access_token)
        assert has_access is True

        # Invalidate cache
        self.cache.invalidate_team(self.project_api_key)

        # Verify token is no longer cached
        has_access, _ = self.cache.has_access_with_team(self.project_api_key, self.access_token)
        assert has_access is False

    def test_get_cached_token_count(self):
        """Test getting token count from HyperCache."""
        # Empty cache
        count = self.cache.get_cached_token_count(self.project_api_key)
        assert count is None

        # Cache with tokens
        tokens = [
            hash_key_value("phx_token_one_123", mode="sha256"),
            hash_key_value("phx_token_two_456", mode="sha256"),
            hash_key_value("phx_token_three_789", mode="sha256"),
        ]
        self.cache.update_team_tokens(self.project_api_key, self.team_id, tokens)

        count = self.cache.get_cached_token_count(self.project_api_key)
        assert count == 3

    @patch("posthog.storage.team_access_cache.logger")
    def test_error_handling_in_has_access_with_team(self, mock_logger):
        """Test error handling in has_access method."""
        # First, add some tokens to cache so the method doesn't exit early
        self.cache.update_team_tokens(self.project_api_key, self.team_id, [self.hashed_token])

        # Then patch hash_key_value to raise an error (patch the imported name)
        with patch("posthog.storage.team_access_cache.hash_key_value", side_effect=Exception("Hash error")):
            result, _ = self.cache.has_access_with_team(self.project_api_key, "invalid_token")
            assert result is False
            mock_logger.warning.assert_called_once()

    def test_ttl_configuration(self):
        """Test that TTL can be configured (HyperCache manages TTL automatically)."""
        custom_cache = TeamAccessTokenCache(ttl=600)
        assert custom_cache.ttl == 600

        # Test that cache respects configuration
        custom_cache.update_team_tokens(self.project_api_key, self.team_id, [self.hashed_token])

        # Verify cache was set via HyperCache
        cached_data = team_access_tokens_hypercache.get_from_cache(self.project_api_key)
        assert cached_data is not None
        assert self.hashed_token in cached_data["hashed_tokens"]

    def test_has_access_with_team_authorized(self):
        """Test has_access_with_team returns True and MinimalTeam when token is authorized."""
        # Set up cache with token and team_id
        self.cache.update_team_tokens(self.project_api_key, self.team_id, [self.hashed_token])

        # Test the combined method
        has_access, team = self.cache.has_access_with_team(self.project_api_key, self.access_token)

        assert has_access is True
        assert team is not None
        assert team.id == self.team_id
        assert team.pk == self.team_id
        assert team.api_token == self.project_api_key

    def test_has_access_with_team_not_authorized(self):
        """Test has_access_with_team returns False and None when token is not authorized."""
        # Set up cache with different token
        other_token = "phx_different_token_789"
        other_hashed = hash_key_value(other_token, mode="sha256")
        self.cache.update_team_tokens(self.project_api_key, self.team_id, [other_hashed])

        # Test with our token (not in cache)
        has_access, team = self.cache.has_access_with_team(self.project_api_key, self.access_token)

        assert has_access is False
        assert team is None

    def test_has_access_with_team_cache_miss(self):
        """Test has_access_with_team returns False and None on cache miss."""
        # Don't put anything in cache
        has_access, team = self.cache.has_access_with_team("unknown_project_key", self.access_token)

        assert has_access is False
        assert team is None

    def test_has_access_with_team_missing_team_id(self):
        """Test has_access_with_team returns True but None team when team_id is missing from cache."""
        # Manually set cache data without team_id (simulate old cache format)
        token_data = {
            "hashed_tokens": [self.hashed_token],
            "last_updated": "2024-01-01T00:00:00Z",
            # team_id missing
        }
        team_access_tokens_hypercache.set_cache_value(self.project_api_key, token_data)

        # Test the method
        has_access, team = self.cache.has_access_with_team(self.project_api_key, self.access_token)

        assert has_access is True  # Token is authorized
        assert team is None  # But no team metadata available

    def test_has_access_with_team_with_multiple_tokens(self):
        """Test has_access works with multiple tokens in JSON list."""
        token1 = "phx_token_one_123"
        token2 = "phx_token_two_456"
        token3 = "phx_token_three_789"

        hashed1 = hash_key_value(token1, mode="sha256")
        hashed2 = hash_key_value(token2, mode="sha256")
        hashed3 = hash_key_value(token3, mode="sha256")

        # Set up cache with multiple tokens using JSON format
        token_data = {
            "hashed_tokens": [hashed1, hashed2, hashed3],
            "token_count": 3,
            "last_updated": "2024-01-01T00:00:00Z",
        }
        team_access_tokens_hypercache.set_cache_value(self.project_api_key, token_data)

        # Test each token can be found
        has_access, _ = self.cache.has_access_with_team(self.project_api_key, token1)
        assert has_access is True
        has_access, _ = self.cache.has_access_with_team(self.project_api_key, token2)
        assert has_access is True
        has_access, _ = self.cache.has_access_with_team(self.project_api_key, token3)
        assert has_access is True

        # Test unknown token is not found
        unknown_token = "phx_unknown_token_999"
        has_access, _ = self.cache.has_access_with_team(self.project_api_key, unknown_token)
        assert has_access is False


class TestTeamAccessCacheIntegration(TestCase):
    """Integration tests for team access cache with models."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("posthog.models.team.team.Team.objects.get")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_warm_team_token_cache(self, mock_org_membership, mock_personal_keys, mock_team_get):
        """Test warming team token cache from database."""
        # Mock team
        mock_team = MagicMock()
        mock_team.id = 123
        mock_team.organization_id = "12345678-1234-5678-9012-123456789abc"  # UUID format
        mock_team.secret_api_token = "phsk_secret_token_123"
        mock_team.secret_api_token_backup = "phsk_backup_token_456"
        mock_team_get.return_value = mock_team

        # Mock organization membership query (for unscoped keys)
        mock_org_membership.return_value.values_list.return_value = [1, 2]  # User IDs

        # Mock personal API key queries
        scoped_call_count = 0
        unscoped_call_count = 0

        def mock_filter_side_effect(*args, **kwargs):
            nonlocal scoped_call_count, unscoped_call_count
            mock_qs = MagicMock()

            # Check if this is the scoped keys query
            if "scoped_teams__contains" in kwargs:
                scoped_call_count += 1
                mock_qs.values_list.return_value = [
                    "sha256$personal_key_hash_1",
                    "sha256$personal_key_hash_2",
                ]
            else:
                # This is the unscoped keys query
                unscoped_call_count += 1
                mock_qs.values_list.return_value = []  # No unscoped keys in this test

            return mock_qs

        mock_personal_keys.side_effect = mock_filter_side_effect

        project_api_key = "phs_test_project_key"

        # Warm the cache
        warm_team_token_cache(project_api_key)

        # Verify both scoped and unscoped queries were made
        assert scoped_call_count == 1
        assert unscoped_call_count == 1

        # Verify organization membership query was called
        mock_org_membership.assert_called_once_with(organization_id="12345678-1234-5678-9012-123456789abc")

        # Verify cache was populated via HyperCache
        cached_data = team_access_tokens_hypercache.get_from_cache(project_api_key)

        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]

        # Should contain personal API key hashes
        assert "sha256$personal_key_hash_1" in hashed_tokens
        assert "sha256$personal_key_hash_2" in hashed_tokens

        # Should contain hashed secret tokens
        expected_secret_hash = hash_key_value("phsk_secret_token_123", mode="sha256")
        expected_backup_hash = hash_key_value("phsk_backup_token_456", mode="sha256")
        assert expected_secret_hash in hashed_tokens
        assert expected_backup_hash in hashed_tokens

        # Verify metadata
        assert cached_data["team_id"] == 123
        assert "last_updated" in cached_data

    @patch("posthog.models.team.team.Team.objects.get")
    def test_warm_team_token_cache_team_not_found(self, mock_team_get):
        """Test warming cache when team doesn't exist."""
        from posthog.models.team.team import Team

        mock_team_get.side_effect = Team.DoesNotExist()

        # Should not raise exception
        warm_team_token_cache("nonexistent_project_key")

        # Cache should remain empty
        cached_data = team_access_tokens_hypercache.get_from_cache("nonexistent_project_key")
        assert cached_data is None

    @patch("posthog.models.team.team.Team.objects.filter")
    def test_get_teams_needing_cache_refresh(self, mock_teams_filter):
        """Test getting teams that need cache refresh."""
        mock_teams_filter.return_value.values_list.return_value = [
            "phs_team_one_123",
            "phs_team_two_456",
            "phs_team_three_789",
        ]

        # Populate cache for team two only via HyperCache
        token_data = {
            "hashed_tokens": ["sha256$some_hash"],
            "token_count": 1,
            "last_updated": "2024-01-01T00:00:00Z",
        }
        team_access_tokens_hypercache.set_cache_value("phs_team_two_456", token_data)

        teams_needing_refresh = get_teams_needing_cache_refresh()

        # Should return teams one and three (missing cache)
        expected = {"phs_team_one_123", "phs_team_three_789"}
        assert set(teams_needing_refresh) == expected


class TestGlobalCacheInstance(TestCase):
    """Test the global team_access_cache instance."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_global_instance_exists(self):
        """Test that global instance exists and works."""
        project_api_key = "phs_global_test_key"
        access_token = "phx_global_test_token"

        # Invalidate the cache
        team_access_cache.invalidate_team(project_api_key)

        # Should start with no access
        has_access, _ = team_access_cache.has_access_with_team(project_api_key, access_token)
        assert has_access is False

        # Add token
        hashed_token = hash_key_value(access_token, mode="sha256")
        team_access_cache.update_team_tokens(project_api_key, 42, [hashed_token])

        # Should now have access
        has_access, _ = team_access_cache.has_access_with_team(project_api_key, access_token)
        assert has_access is True


class TestCacheWarmingWithUnscopedKeys(TestCase):
    """Test cache warming functionality with unscoped PersonalAPIKeys."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("posthog.models.team.team.Team.objects.get")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_warm_team_cache_includes_unscoped_keys(self, mock_org_membership, mock_personal_keys, mock_team_get):
        """Test that cache warming includes unscoped PersonalAPIKeys."""
        # Mock team
        mock_team = MagicMock()
        mock_team.id = 123
        mock_team.organization_id = "org1"
        mock_team.secret_api_token = "phsk_secret_token_123"
        mock_team.secret_api_token_backup = None
        mock_team_get.return_value = mock_team

        # Mock organization membership query (for unscoped keys)
        mock_org_membership.return_value.values_list.return_value = [1, 2, 3]  # User IDs

        # Mock personal API key queries
        scoped_call_count = 0
        unscoped_call_count = 0

        def mock_filter_side_effect(*args, **kwargs):
            nonlocal scoped_call_count, unscoped_call_count
            mock_qs = MagicMock()

            # Check if this is the scoped keys query
            if "scoped_teams__contains" in kwargs:
                scoped_call_count += 1
                mock_qs.values_list.return_value = ["sha256$scoped_key_1", "sha256$scoped_key_2"]
            else:
                # This is the unscoped keys query
                unscoped_call_count += 1
                # Mock the chained filter call for scope filtering
                mock_qs.filter.return_value.values_list.return_value = ["sha256$unscoped_key_1"]
                mock_qs.values_list.return_value = ["sha256$unscoped_key_1"]

            return mock_qs

        mock_personal_keys.side_effect = mock_filter_side_effect

        project_api_key = "phs_test_project_key"

        # Warm the cache
        warm_team_token_cache(project_api_key)

        # Verify both scoped and unscoped queries were made
        assert scoped_call_count == 1
        assert unscoped_call_count == 1

        # Verify organization membership query was called
        mock_org_membership.assert_called_once_with(organization_id="org1")

        # Verify cache was populated with all keys via HyperCache
        cached_data = team_access_tokens_hypercache.get_from_cache(project_api_key)

        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]

        # Should contain scoped keys
        assert "sha256$scoped_key_1" in hashed_tokens
        assert "sha256$scoped_key_2" in hashed_tokens

        # Should contain unscoped keys
        assert "sha256$unscoped_key_1" in hashed_tokens

        # Should contain team secret token
        expected_secret_hash = hash_key_value("phsk_secret_token_123", mode="sha256")
        assert expected_secret_hash in hashed_tokens

    @patch("posthog.models.team.team.Team.objects.get")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_warm_team_cache_no_unscoped_keys(self, mock_org_membership, mock_personal_keys, mock_team_get):
        """Test cache warming when there are no unscoped PersonalAPIKeys."""
        # Mock team
        mock_team = MagicMock()
        mock_team.id = 123
        mock_team.organization_id = "org1"
        mock_team.secret_api_token = None
        mock_team.secret_api_token_backup = None
        mock_team_get.return_value = mock_team

        # Mock organization membership query (no users)
        mock_org_membership.return_value.values_list.return_value = []

        # Mock personal API key queries
        def mock_filter_side_effect(*args, **kwargs):
            mock_qs = MagicMock()
            if "scoped_teams__contains" in kwargs:
                mock_qs.values_list.return_value = ["sha256$scoped_key_1"]
            else:
                mock_qs.values_list.return_value = []  # No unscoped keys
            return mock_qs

        mock_personal_keys.side_effect = mock_filter_side_effect

        project_api_key = "phs_test_project_key"

        # Warm the cache
        warm_team_token_cache(project_api_key)

        # Verify cache was populated with only scoped keys
        cached_data = team_access_tokens_hypercache.get_from_cache(project_api_key)

        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]
        assert "sha256$scoped_key_1" in hashed_tokens
        # Should not contain any unscoped keys
        assert "sha256$unscoped_key_1" not in hashed_tokens

    @patch("posthog.models.team.team.Team.objects.get")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_warm_team_cache_duplicate_key_handling(self, mock_org_membership, mock_personal_keys, mock_team_get):
        """Test that duplicate keys between scoped and unscoped are handled correctly."""
        # Mock team
        mock_team = MagicMock()
        mock_team.id = 123
        mock_team.organization_id = "org1"
        mock_team.secret_api_token = None
        mock_team.secret_api_token_backup = None
        mock_team_get.return_value = mock_team

        # Mock organization membership query
        mock_org_membership.return_value.values_list.return_value = [1]

        # Mock personal API key queries to return the same key in both queries
        # This could happen if a user has an unscoped key and it appears in both queries
        def mock_filter_side_effect(*args, **kwargs):
            mock_qs = MagicMock()
            mock_qs.values_list.return_value = ["sha256$duplicate_key"]
            # Mock the chained filter call for scope filtering (for unscoped queries)
            mock_qs.filter.return_value.values_list.return_value = ["sha256$duplicate_key"]
            return mock_qs

        mock_personal_keys.side_effect = mock_filter_side_effect

        project_api_key = "phs_test_project_key"

        # Warm the cache
        warm_team_token_cache(project_api_key)

        # Verify cache was populated
        cached_data = team_access_tokens_hypercache.get_from_cache(project_api_key)

        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]

        # The key should appear in the cache (duplicates don't matter for our use case)
        assert "sha256$duplicate_key" in hashed_tokens

        # Count occurrences - should work even with duplicates
        duplicate_count = sum(1 for token in hashed_tokens if token == "sha256$duplicate_key")
        # We expect 2 duplicates since it comes from both scoped and unscoped queries
        assert duplicate_count == 2


class TestGetTeamsForPersonalAPIKey(TestCase):
    """Test the get_teams_for_personal_api_key function."""

    @patch("posthog.models.team.team.Team.objects.filter")
    def test_get_teams_for_scoped_personal_api_key(self, mock_team_filter):
        """Test getting teams for a PersonalAPIKey with scoped teams."""
        # Mock team query to return project API keys for scoped teams
        mock_team_filter.return_value.values_list.return_value = ["phs_team1_123", "phs_team2_456"]

        # Create mock PersonalAPIKey with scoped teams
        mock_key = MagicMock()
        mock_key.id = 1
        mock_key.scoped_teams = [1, 2]
        mock_key.user.id = 100

        # Call the function
        result = get_teams_for_personal_api_key(mock_key)

        # Verify correct teams were returned
        assert result == ["phs_team1_123", "phs_team2_456"]

        # Verify correct query was made
        mock_team_filter.assert_called_once_with(id__in=[1, 2])
        mock_team_filter.return_value.values_list.assert_called_once_with("api_token", flat=True)

    @patch("posthog.models.team.team.Team.objects.filter")
    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_get_teams_for_unscoped_personal_api_key(self, mock_org_membership, mock_team_filter):
        """Test getting teams for an unscoped PersonalAPIKey (all user's org teams)."""
        # Mock organization membership query
        mock_org_membership.return_value.values_list.return_value = ["org1", "org2"]

        # Mock team query to return teams in those organizations
        mock_team_filter.return_value.values_list.return_value = ["phs_team1_123", "phs_team2_456", "phs_team3_789"]

        # Create mock PersonalAPIKey with no scoped teams (unscoped)
        mock_key = MagicMock()
        mock_key.id = 1
        mock_key.scoped_teams = None  # Unscoped
        mock_key.user.id = 100

        # Call the function
        result = get_teams_for_personal_api_key(mock_key)

        # Verify correct teams were returned
        assert result == ["phs_team1_123", "phs_team2_456", "phs_team3_789"]

        # Verify organization membership query
        mock_org_membership.assert_called_once_with(user=mock_key.user)
        mock_org_membership.return_value.values_list.assert_called_once_with("organization_id", flat=True)

        # Verify team query
        mock_team_filter.assert_called_once_with(organization_id__in=["org1", "org2"])
        mock_team_filter.return_value.values_list.assert_called_once_with("api_token", flat=True)

    @patch("posthog.models.team.team.Team.objects.filter")
    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_get_teams_for_unscoped_personal_api_key_empty_scoped_teams(self, mock_org_membership, mock_team_filter):
        """Test getting teams for PersonalAPIKey with empty scoped_teams list."""
        # Mock organization membership query
        mock_org_membership.return_value.values_list.return_value = ["org1"]

        # Mock team query
        mock_team_filter.return_value.values_list.return_value = ["phs_team1_123"]

        # Create mock PersonalAPIKey with empty scoped teams list
        mock_key = MagicMock()
        mock_key.id = 1
        mock_key.scoped_teams = []  # Empty list = unscoped
        mock_key.user.id = 100

        # Call the function
        result = get_teams_for_personal_api_key(mock_key)

        # Verify correct team was returned
        assert result == ["phs_team1_123"]

        # Verify queries were made for unscoped key logic
        mock_org_membership.assert_called_once_with(user=mock_key.user)
        mock_team_filter.assert_called_once_with(organization_id__in=["org1"])

    @patch("posthog.models.organization.OrganizationMembership.objects.filter")
    def test_get_teams_for_unscoped_personal_api_key_no_organizations(self, mock_org_membership):
        """Test getting teams when user has no organization memberships."""
        # Mock organization membership query to return empty
        mock_org_membership.return_value.values_list.return_value = []

        # Create mock PersonalAPIKey with no scoped teams
        mock_key = MagicMock()
        mock_key.id = 1
        mock_key.scoped_teams = None
        mock_key.user.id = 100

        # Call the function
        result = get_teams_for_personal_api_key(mock_key)

        # Verify empty list was returned
        assert result == []

        # Verify organization membership query was made
        mock_org_membership.assert_called_once_with(user=mock_key.user)
        mock_org_membership.return_value.values_list.assert_called_once_with("organization_id", flat=True)

    @patch("posthog.models.team.team.Team.objects.filter")
    def test_get_teams_for_scoped_personal_api_key_empty_team_ids(self, mock_team_filter):
        """Test getting teams for PersonalAPIKey with empty scoped team IDs."""
        # Mock team query to return empty
        mock_team_filter.return_value.values_list.return_value = []

        # Create mock PersonalAPIKey with scoped teams that don't exist
        mock_key = MagicMock()
        mock_key.id = 1
        mock_key.scoped_teams = [999]  # Non-existent team ID
        mock_key.user.id = 100

        # Call the function
        result = get_teams_for_personal_api_key(mock_key)

        # Verify empty list was returned
        assert result == []

        # Verify correct query was made
        mock_team_filter.assert_called_once_with(id__in=[999])
        mock_team_filter.return_value.values_list.assert_called_once_with("api_token", flat=True)


class TestUpdateUserAuthenticationCache(TestCase):
    """Test the update_user_authentication_cache function."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    def test_user_activated_warms_affected_team_caches(self, mock_personal_keys, mock_get_teams, mock_warm_cache):
        """Test that when a user is activated, caches are warmed for all teams they have access to."""
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Mock user has personal API keys with access to multiple teams
        mock_key1 = MagicMock()
        mock_key2 = MagicMock()
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_key1, mock_key2])
        mock_personal_keys.return_value = mock_queryset

        # Mock teams each key has access to
        def mock_get_teams_side_effect(key):
            if key == mock_key1:
                return ["phs_team1_123", "phs_team2_456"]
            elif key == mock_key2:
                return ["phs_team2_456", "phs_team3_789"]
            return []

        mock_get_teams.side_effect = mock_get_teams_side_effect

        # Call function for user activation
        update_user_authentication_cache(instance=mock_user, update_fields=["is_active"])

        # Verify cache warming was called for all unique teams
        assert mock_warm_cache.call_count == 3
        mock_warm_cache.assert_any_call("phs_team1_123")
        mock_warm_cache.assert_any_call("phs_team2_456")
        mock_warm_cache.assert_any_call("phs_team3_789")

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    def test_user_deactivated_warms_affected_team_caches(self, mock_personal_keys, mock_get_teams, mock_warm_cache):
        """Test that when a user is deactivated, caches are warmed for all affected teams to remove their tokens."""
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = False  # Deactivated

        # Mock user has personal API keys
        mock_key = MagicMock()
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_key])
        mock_personal_keys.return_value = mock_queryset
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        # Call function for user deactivation
        update_user_authentication_cache(instance=mock_user, update_fields=["is_active"])

        # Verify cache warming was called for affected teams (to remove deactivated user's tokens)
        assert mock_warm_cache.call_count == 2
        mock_warm_cache.assert_any_call("phs_team1_123")
        mock_warm_cache.assert_any_call("phs_team2_456")

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    def test_update_user_authentication_cache_runs_regardless_of_update_fields(
        self, mock_personal_keys, mock_get_teams, mock_warm_cache
    ):
        """Test that function now runs regardless of update_fields since filtering moved to user_saved."""
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Mock user has personal API keys
        mock_key = MagicMock()
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_key])
        mock_personal_keys.return_value = mock_queryset
        mock_get_teams.return_value = ["phs_team1_123"]

        # Should run even when is_active is not in update_fields (filtering moved to user_saved)
        update_user_authentication_cache(instance=mock_user, update_fields=["email", "name"])

        # Verify cache operations occurred
        mock_personal_keys.assert_called_once_with(user_id=42)
        mock_get_teams.assert_called_once_with(mock_key)
        mock_warm_cache.assert_called_once_with("phs_team1_123")

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    def test_update_user_authentication_cache_runs_without_update_fields(
        self, mock_personal_keys, mock_get_teams, mock_warm_cache
    ):
        """Test that function runs when update_fields is None (bulk operations)."""
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Mock user has personal API keys
        mock_key = MagicMock()
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_key])
        mock_personal_keys.return_value = mock_queryset
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        # Call without update_fields (should run)
        update_user_authentication_cache(instance=mock_user)

        # Verify cache operations occurred
        mock_personal_keys.assert_called_once_with(user_id=42)
        mock_get_teams.assert_called_once_with(mock_key)
        assert mock_warm_cache.call_count == 2
        mock_warm_cache.assert_any_call("phs_team1_123")
        mock_warm_cache.assert_any_call("phs_team2_456")

    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    def test_update_user_authentication_cache_handles_no_api_keys(self, mock_personal_keys):
        """Test function handles users with no personal API keys."""
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42

        # Mock user has no personal API keys
        mock_personal_keys.return_value.exists.return_value = False

        # Should not raise exception
        update_user_authentication_cache(instance=mock_user, update_fields=["is_active"])

        # Verify query was made but function returned early
        mock_personal_keys.assert_called_once_with(user_id=42)

    @patch("posthog.storage.team_access_cache_signal_handlers.logger")
    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    @patch("posthog.models.personal_api_key.PersonalAPIKey.objects.filter")
    def test_update_user_authentication_cache_handles_warm_cache_failures(
        self, mock_personal_keys, mock_get_teams, mock_warm_cache, mock_logger
    ):
        """Test function handles individual cache warming failures gracefully."""
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create mock user
        mock_user = MagicMock()
        mock_user.id = 42
        mock_user.is_active = True

        # Mock user has personal API keys
        mock_key = MagicMock()
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__ = lambda self: iter([mock_key])
        mock_personal_keys.return_value = mock_queryset
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        # Make first cache warm fail, second succeed
        def side_effect(project_api_key):
            if project_api_key == "phs_team1_123":
                raise Exception("Cache warming failed")

        mock_warm_cache.side_effect = side_effect

        # Should not raise exception
        update_user_authentication_cache(instance=mock_user, update_fields=["is_active"])

        # Verify both cache warming attempts were made
        assert mock_warm_cache.call_count == 2
        mock_warm_cache.assert_any_call("phs_team1_123")
        mock_warm_cache.assert_any_call("phs_team2_456")

        # Verify warning was logged for the failure
        mock_logger.warning.assert_called_once()
        assert "Failed to warm cache for team phs_team1_123" in str(mock_logger.warning.call_args)


class TestSignalHandlerCacheWarming(TestCase):
    """Test that signal handlers properly warm caches instead of just invalidating."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    def test_personal_api_key_signal_handlers_warm_caches(self, mock_get_teams, mock_warm_cache):
        """Test that personal API key signal handlers warm caches efficiently."""
        from posthog.storage.team_access_cache_signal_handlers import (
            update_personal_api_key_authentication_cache,
            update_personal_api_key_authentication_cache_on_delete,
        )

        # Mock get_teams function returns affected teams
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        # Create mock PersonalAPIKey
        mock_key = MagicMock()
        mock_key.id = "test_key"

        # Test save handler
        update_personal_api_key_authentication_cache(instance=mock_key, created=False)

        # Verify get_teams was called
        mock_get_teams.assert_called_once_with(mock_key)

        # Verify cache warming was called for each affected team
        assert mock_warm_cache.call_count == 2
        mock_warm_cache.assert_any_call("phs_team1_123")
        mock_warm_cache.assert_any_call("phs_team2_456")

        # Reset mocks and test delete handler
        mock_get_teams.reset_mock()
        mock_warm_cache.reset_mock()
        mock_get_teams.return_value = ["phs_team3_789"]

        update_personal_api_key_authentication_cache_on_delete(instance=mock_key)

        # Verify get_teams was called
        mock_get_teams.assert_called_once_with(mock_key)

        # Verify cache warming was called
        mock_warm_cache.assert_called_once_with("phs_team3_789")

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    def test_team_signal_handlers_warm_caches(self, mock_warm_cache):
        """Test that team signal handlers warm caches instead of just invalidating."""
        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache

        # Create mock Team
        mock_team = MagicMock()
        mock_team.pk = 123
        mock_team.api_token = "phs_team_token_123"

        # Test save handler (not created)
        update_team_authentication_cache(instance=mock_team, created=False)

        # Verify cache warming was called (not just invalidation)
        mock_warm_cache.assert_called_once_with("phs_team_token_123")

        # Test that it doesn't warm cache for new teams (created=True)
        mock_warm_cache.reset_mock()
        update_team_authentication_cache(instance=mock_team, created=True)

        # Should not warm cache for new teams
        mock_warm_cache.assert_not_called()

    @patch("posthog.storage.team_access_cache.team_access_cache.invalidate_team")
    def test_team_delete_handler_invalidates_cache(self, mock_invalidate):
        """Test that team delete handler invalidates cache (can't warm deleted team)."""
        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache_on_delete

        # Create mock Team
        mock_team = MagicMock()
        mock_team.pk = 123
        mock_team.api_token = "phs_team_token_123"

        # Test delete handler
        update_team_authentication_cache_on_delete(instance=mock_team)

        # Verify cache invalidation was called (can't warm a deleted team)
        mock_invalidate.assert_called_once_with("phs_team_token_123")

    @patch("posthog.storage.team_access_cache_signal_handlers.logger")
    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    def test_signal_handlers_handle_cache_warming_failures(self, mock_get_teams, mock_warm_cache, mock_logger):
        """Test that signal handlers handle cache warming failures gracefully."""
        from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_authentication_cache

        # Mock get_teams function returns affected teams
        mock_get_teams.return_value = ["phs_team1_123", "phs_team2_456"]

        # Make cache warming fail for one team
        def side_effect(project_api_key):
            if project_api_key == "phs_team1_123":
                raise Exception("Cache warming failed")

        mock_warm_cache.side_effect = side_effect

        # Create mock PersonalAPIKey
        mock_key = MagicMock()
        mock_key.id = "test_key"

        # Should not raise exception
        update_personal_api_key_authentication_cache(instance=mock_key, created=False)

        # Verify both cache warming attempts were made
        assert mock_warm_cache.call_count == 2
        mock_warm_cache.assert_any_call("phs_team1_123")
        mock_warm_cache.assert_any_call("phs_team2_456")

        # Verify warning was logged for the failure
        mock_logger.warning.assert_called_once()
        assert "Failed to warm cache for team phs_team1_123" in str(mock_logger.warning.call_args)

    @patch("posthog.storage.team_access_cache.warm_team_token_cache")
    @patch("posthog.storage.team_access_cache.get_teams_for_personal_api_key")
    def test_signal_handlers_handle_empty_affected_teams(self, mock_get_teams, mock_warm_cache):
        """Test signal handlers handle cases where no teams are affected."""
        from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_authentication_cache

        # Mock get_teams function returns no teams
        mock_get_teams.return_value = []

        # Create mock PersonalAPIKey
        mock_key = MagicMock()
        mock_key.id = "test_key"

        # Should not raise exception
        update_personal_api_key_authentication_cache(instance=mock_key, created=False)

        # Verify get_teams was called
        mock_get_teams.assert_called_once_with(mock_key)

        # Verify no cache warming attempts (no teams affected)
        mock_warm_cache.assert_not_called()
