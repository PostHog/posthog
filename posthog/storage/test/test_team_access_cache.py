"""
Tests for team access token cache functionality.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

from posthog.models.personal_api_key import hash_key_value
from posthog.storage.team_access_cache import (
    TeamAccessTokenCache,
    get_teams_for_single_personal_api_key,
    get_teams_for_user_personal_api_keys,
    get_teams_needing_cache_refresh,
    get_teams_needing_cache_refresh_paginated,
    team_access_tokens_hypercache,
    warm_team_token_cache,
)


class TestTeamAccessTokenCache(TestCase):
    """Test the TeamAccessTokenCache class."""

    def setUp(self):
        """Set up test data."""
        self.cache = TeamAccessTokenCache(ttl=300)
        self.api_token = "phs_test_project_key_123"
        self.team_id = 42
        self.access_token = "phx_test_access_token_456"
        self.hashed_token = hash_key_value(self.access_token, mode="sha256")

        # Clear cache before each test
        cache.clear()
        # Also clear HyperCache
        team_access_tokens_hypercache.clear_cache(self.api_token)

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()
        # Also clear HyperCache
        team_access_tokens_hypercache.clear_cache(self.api_token)

    def test_update_team_tokens(self):
        """Test updating team token list using HyperCache."""
        tokens = [
            hash_key_value("phx_token_one_123", mode="sha256"),
            hash_key_value("phx_token_two_456", mode="sha256"),
        ]

        self.cache.update_team_tokens(self.api_token, self.team_id, tokens)

        # Verify tokens are cached in JSON format
        cached_data = team_access_tokens_hypercache.get_from_cache(self.api_token)

        assert cached_data is not None
        assert cached_data["hashed_tokens"] == tokens
        assert cached_data["team_id"] == self.team_id
        assert "last_updated" in cached_data

    def test_invalidate_team(self):
        """Test invalidating team cache."""
        # Set up cache
        self.cache.update_team_tokens(self.api_token, self.team_id, [self.hashed_token])

        # Verify token is cached
        cached_data = team_access_tokens_hypercache.get_from_cache(self.api_token)
        assert cached_data is not None
        assert self.hashed_token in cached_data.get("hashed_tokens", [])

        # Invalidate cache
        self.cache.invalidate_team(self.api_token)

        # Verify token is no longer cached
        cached_data = team_access_tokens_hypercache.get_from_cache(self.api_token)
        assert cached_data is None


class TestTeamAccessCacheIntegration(TestCase):
    """Integration tests for team access cache with models."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @parameterized.expand(
        [
            ("feature_flag:read", "Test with read scope"),
            ("feature_flag:write", "Test with write scope"),
        ]
    )
    def test_warm_team_token_cache(self, scope, description):
        """Test warming team token cache from database with real data."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        scope_suffix = scope.split(":")[1]  # 'read' or 'write'
        organization = Organization.objects.create(name=f"Test Organization {scope_suffix}")
        team = Team.objects.create(
            organization=organization,
            name=f"Test Team {scope_suffix}",
            api_token=f"phc_test_{scope_suffix}_123",
            secret_api_token=f"phsk_secret_{scope_suffix}_123",
            secret_api_token_backup=f"phsk_backup_{scope_suffix}_456",
        )

        # Create users and personal API keys
        user1 = User.objects.create(email=f"user1_{scope_suffix}@test.com", is_active=True)
        user2 = User.objects.create(email=f"user2_{scope_suffix}@test.com", is_active=True)

        # Add users to organization
        OrganizationMembership.objects.create(organization=organization, user=user1)
        OrganizationMembership.objects.create(organization=organization, user=user2)

        # Create personal API keys with the scope being tested
        PersonalAPIKey.objects.create(
            user=user1,
            label=f"Test Key 1 {scope_suffix}",
            secure_value=hash_key_value(f"test_key_1_{scope_suffix}"),
            scopes=[scope],  # Use the scope being tested
        )
        PersonalAPIKey.objects.create(
            user=user2,
            label=f"Test Key 2 {scope_suffix}",
            secure_value=hash_key_value(f"test_key_2_{scope_suffix}"),
            scoped_teams=[team.id],
            scopes=[scope],  # Use the scope being tested
        )

        # Warm the cache
        result = warm_team_token_cache(team.api_token)

        # Verify cache warming succeeded
        assert result is True, f"Cache warming should succeed for {scope}"

        # Verify cache was populated via HyperCache
        cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)

        assert cached_data is not None, f"Cache should be populated for {scope}"
        hashed_tokens = cached_data["hashed_tokens"]

        # Should contain personal API key hashes and secret tokens
        expected_personal_key_1 = hash_key_value(f"test_key_1_{scope_suffix}", mode="sha256")
        expected_personal_key_2 = hash_key_value(f"test_key_2_{scope_suffix}", mode="sha256")
        expected_secret = hash_key_value(f"phsk_secret_{scope_suffix}_123", mode="sha256")
        expected_secret_backup = hash_key_value(f"phsk_backup_{scope_suffix}_456", mode="sha256")

        assert expected_personal_key_1 in hashed_tokens, f"Unscoped key with {scope} should be in cache"
        assert expected_personal_key_2 in hashed_tokens, f"Scoped key with {scope} should be in cache"
        assert expected_secret in hashed_tokens, f"Secret token should be in cache for {scope}"
        assert expected_secret_backup in hashed_tokens, f"Backup secret token should be in cache for {scope}"

        # Should have team_id for zero-DB-call authentication
        assert cached_data["team_id"] == team.id
        assert "last_updated" in cached_data

    def test_warm_team_token_cache_with_all_access_scope(self):
        """Test that personal API keys with '*' (all access) scope are included in cache.

        This is a regression test for a bug where keys created with 'all access'
        (scopes=["*"]) were not being added to the team access cache because
        the query only checked for feature_flag:read, feature_flag:write, null,
        or empty scopes.
        """
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        organization = Organization.objects.create(name="Test Organization All Access")
        team = Team.objects.create(
            organization=organization,
            name="Test Team All Access",
            api_token="phc_test_all_access_123",
        )

        # Create user with org membership
        user = User.objects.create(email="user_all_access@test.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user)

        # Create personal API key with "*" (all access) scope - this is what the UI creates
        # when selecting "All access"
        PersonalAPIKey.objects.create(
            user=user,
            label="All Access Key",
            secure_value=hash_key_value("test_all_access_key"),
            scopes=["*"],  # All access scope
        )

        # Warm the cache
        result = warm_team_token_cache(team.api_token)

        # Verify cache warming succeeded
        assert result is True, "Cache warming should succeed"

        # Verify cache was populated
        cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
        assert cached_data is not None, "Cache should be populated"

        hashed_tokens = cached_data["hashed_tokens"]
        expected_all_access_key = hash_key_value("test_all_access_key", mode="sha256")

        # The key with "*" scope should be in the cache
        assert expected_all_access_key in hashed_tokens, (
            "Personal API key with '*' (all access) scope should be included in cache"
        )

    def test_warm_team_token_cache_with_scoped_all_access(self):
        """Test that team-scoped personal API keys with '*' scope are included in cache."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        organization = Organization.objects.create(name="Test Org Scoped All Access")
        team = Team.objects.create(
            organization=organization,
            name="Test Team Scoped All Access",
            api_token="phc_test_scoped_all_access_123",
        )

        # Create user with org membership
        user = User.objects.create(email="user_scoped_all_access@test.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user)

        # Create personal API key scoped to specific team with "*" scope
        PersonalAPIKey.objects.create(
            user=user,
            label="Scoped All Access Key",
            secure_value=hash_key_value("test_scoped_all_access_key"),
            scopes=["*"],
            scoped_teams=[team.id],
        )

        # Warm the cache
        result = warm_team_token_cache(team.api_token)

        # Verify cache warming succeeded
        assert result is True, "Cache warming should succeed"

        # Verify cache was populated
        cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
        assert cached_data is not None, "Cache should be populated"

        hashed_tokens = cached_data["hashed_tokens"]
        expected_key = hash_key_value("test_scoped_all_access_key", mode="sha256")

        # The team-scoped key with "*" scope should be in the cache
        assert expected_key in hashed_tokens, "Team-scoped personal API key with '*' scope should be included in cache"

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

    @patch("posthog.storage.team_access_cache.team_access_tokens_hypercache.get_from_cache")
    def test_get_teams_needing_cache_refresh_paginated_generator(self, mock_get_from_cache):
        """Test the paginated generator function by mocking cache checks."""
        from posthog.models import Organization, Team

        # Create test data
        organization = Organization.objects.create(name="Test Organization")
        teams = []
        for i in range(7):  # 7 teams total
            team = Team.objects.create(organization=organization, name=f"Team {i}", api_token=f"phs_team_{i:03d}")
            teams.append(team)

        # Mock cache to return None for all teams (all need refresh)
        mock_get_from_cache.return_value = None

        # Test paginated generator with batch size 3
        all_batches = list(get_teams_needing_cache_refresh_paginated(batch_size=3))

        # Flatten all batches
        all_teams_from_batches = []
        for batch in all_batches:
            all_teams_from_batches.extend(batch)

        # Should match non-paginated result
        expected_teams = get_teams_needing_cache_refresh()
        assert set(all_teams_from_batches) == set(expected_teams)

        # All our test teams should be included (since mock returns None for all)
        expected_api_keys = {f"phs_team_{i:03d}" for i in range(7)}
        # At least our test teams should be present
        assert expected_api_keys.issubset(set(all_teams_from_batches))

        # Should have gotten some batches
        assert len(all_batches) >= 1

        # Each batch should respect the batch size limit
        for batch in all_batches:
            assert len(batch) <= 3


class TestCacheWarmingWithUnscopedKeys(TestCase):
    """Test cache warming functionality with unscoped PersonalAPIKeys."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_warm_team_cache_includes_unscoped_keys(self):
        """Test that cache warming includes unscoped PersonalAPIKeys."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        organization = Organization.objects.create(name="Test Organization")
        team = Team.objects.create(
            organization=organization,
            name="Test Team",
            api_token="phc_test_project_key",
            secret_api_token="phsk_secret_token_123",
        )

        # Create users with both scoped and unscoped keys
        user1 = User.objects.create(email="user1@test.com", is_active=True)
        user2 = User.objects.create(email="user2@test.com", is_active=True)
        user3 = User.objects.create(email="user3@test.com", is_active=True)

        # Add users to organization
        OrganizationMembership.objects.create(organization=organization, user=user1)
        OrganizationMembership.objects.create(organization=organization, user=user2)
        OrganizationMembership.objects.create(organization=organization, user=user3)

        # Create scoped keys (for specific team)
        PersonalAPIKey.objects.create(
            user=user1,
            label="Scoped Key 1",
            secure_value=hash_key_value("scoped_key_1"),
            scoped_teams=[team.id],
            scopes=["feature_flag:read"],
        )
        PersonalAPIKey.objects.create(
            user=user2,
            label="Scoped Key 2",
            secure_value=hash_key_value("scoped_key_2"),
            scoped_teams=[team.id],
            scopes=["feature_flag:read"],
        )

        # Create unscoped key (access to all teams in organization)
        PersonalAPIKey.objects.create(
            user=user3,
            label="Unscoped Key",
            secure_value=hash_key_value("unscoped_key_1"),
            scopes=["feature_flag:read"],  # No scoped_teams means all teams
        )

        # Warm the cache
        result = warm_team_token_cache(team.api_token)
        assert result is True

        # Verify cache contains all keys (scoped and unscoped)
        cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]

        # Should contain hashed versions of all keys
        expected_scoped_1 = hash_key_value("scoped_key_1", mode="sha256")
        expected_scoped_2 = hash_key_value("scoped_key_2", mode="sha256")
        expected_unscoped = hash_key_value("unscoped_key_1", mode="sha256")
        expected_secret = hash_key_value("phsk_secret_token_123", mode="sha256")

        assert expected_scoped_1 in hashed_tokens
        assert expected_scoped_2 in hashed_tokens
        assert expected_unscoped in hashed_tokens
        assert expected_secret in hashed_tokens

    def test_warm_team_cache_no_unscoped_keys(self):
        """Test cache warming when there are no unscoped PersonalAPIKeys."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data with only scoped keys
        organization = Organization.objects.create(name="Test Organization")
        team = Team.objects.create(organization=organization, name="Test Team", api_token="phc_test_project_key")

        # Create user with only scoped key (no unscoped key)
        user1 = User.objects.create(email="user1@test.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user1)

        # Create only scoped key
        PersonalAPIKey.objects.create(
            user=user1,
            label="Scoped Key Only",
            secure_value=hash_key_value("scoped_key_1"),
            scoped_teams=[team.id],
            scopes=["feature_flag:read"],
        )

        # Warm the cache
        result = warm_team_token_cache(team.api_token)
        assert result is True

        # Verify cache was populated with only scoped keys
        cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]

        # Should contain the scoped key
        expected_scoped = hash_key_value("scoped_key_1", mode="sha256")
        assert expected_scoped in hashed_tokens

        # Should not contain any unscoped keys (since none were created)
        assert len(hashed_tokens) == 1  # Only the one scoped key

    def test_warm_team_cache_duplicate_key_handling(self):
        """Test that duplicate keys between scoped and unscoped are handled correctly."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data - scenario where same user might have key that could match both scoped/unscoped
        organization = Organization.objects.create(name="Test Organization")
        team = Team.objects.create(organization=organization, name="Test Team", api_token="phc_test_project_key")

        # Create user
        user1 = User.objects.create(email="user1@test.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user1)

        # Create unscoped key (has access to all teams in org)
        PersonalAPIKey.objects.create(
            user=user1,
            label="Unscoped Key",
            secure_value=hash_key_value("duplicate_key"),
            scopes=["feature_flag:read"],  # No scoped_teams = all teams
        )

        # Warm the cache
        result = warm_team_token_cache(team.api_token)
        assert result is True

        # Verify cache was populated
        cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
        assert cached_data is not None
        hashed_tokens = cached_data["hashed_tokens"]

        # The key should appear in the cache
        expected_key = hash_key_value("duplicate_key", mode="sha256")
        assert expected_key in hashed_tokens

        # Should only appear once (SQL DISTINCT handles duplicates)
        duplicate_count = sum(1 for token in hashed_tokens if token == expected_key)
        assert duplicate_count == 1


class TestGetTeamsForPersonalAPIKey(TestCase):
    """Test the get_teams_for_single_personal_api_key function."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_get_teams_for_scoped_personal_api_key(self):
        """Test getting teams for a PersonalAPIKey with scoped teams."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        organization = Organization.objects.create(name="Test Organization")
        team1 = Team.objects.create(organization=organization, name="Team 1", api_token="phs_team1_123")
        team2 = Team.objects.create(organization=organization, name="Team 2", api_token="phs_team2_456")
        team3 = Team.objects.create(organization=organization, name="Team 3", api_token="phs_team3_789")

        # Create user and add to organization
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user)

        # Create PersonalAPIKey with scoped teams (only team1 and team2)
        personal_key = PersonalAPIKey.objects.create(
            user=user,
            label="Scoped Key",
            secure_value=hash_key_value("scoped_key_1"),
            scoped_teams=[team1.id, team2.id],
            scopes=["feature_flag:read"],
        )

        # Call the function
        result = get_teams_for_single_personal_api_key(personal_key)

        # Verify correct teams were returned (should only include scoped teams)
        expected_tokens = {team1.api_token, team2.api_token}
        assert set(result) == expected_tokens
        assert team3.api_token not in result

    def test_get_teams_for_unscoped_personal_api_key(self):
        """Test getting teams for an unscoped PersonalAPIKey (all user's org teams)."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data - multiple organizations
        org1 = Organization.objects.create(name="Organization 1")
        org2 = Organization.objects.create(name="Organization 2")
        org3 = Organization.objects.create(name="Organization 3")

        # Create teams in different organizations
        team1 = Team.objects.create(organization=org1, name="Team 1", api_token="phs_team1_123")
        team2 = Team.objects.create(organization=org1, name="Team 2", api_token="phs_team2_456")
        team3 = Team.objects.create(organization=org2, name="Team 3", api_token="phs_team3_789")
        team4 = Team.objects.create(organization=org3, name="Team 4", api_token="phs_team4_abc")  # User not in this org

        # Create user and add to org1 and org2 only
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org1, user=user)
        OrganizationMembership.objects.create(organization=org2, user=user)

        # Create PersonalAPIKey without scoped teams (unscoped)
        personal_key = PersonalAPIKey.objects.create(
            user=user,
            label="Unscoped Key",
            secure_value=hash_key_value("unscoped_key_1"),
            scopes=["feature_flag:read"],  # No scoped_teams means all teams
        )

        # Call the function
        result = get_teams_for_single_personal_api_key(personal_key)

        # Verify correct teams were returned (should include all teams from user's organizations)
        expected_tokens = {team1.api_token, team2.api_token, team3.api_token}
        assert set(result) == expected_tokens
        assert team4.api_token not in result  # User not in org3

    def test_get_teams_for_unscoped_personal_api_key_empty_scoped_teams(self):
        """Test getting teams for PersonalAPIKey with empty scoped_teams list."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        organization = Organization.objects.create(name="Test Organization")
        team = Team.objects.create(organization=organization, name="Team 1", api_token="phs_team1_123")

        # Create user and add to organization
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user)

        # Create PersonalAPIKey with empty scoped teams list (unscoped)
        personal_key = PersonalAPIKey.objects.create(
            user=user,
            label="Unscoped Key",
            secure_value=hash_key_value("unscoped_key_1"),
            scoped_teams=[],  # Empty list = unscoped
            scopes=["feature_flag:read"],
        )

        # Call the function
        result = get_teams_for_single_personal_api_key(personal_key)

        # Verify correct team was returned
        assert result == [team.api_token]

    def test_get_teams_for_unscoped_personal_api_key_no_organizations(self):
        """Test getting teams when user has no organization memberships."""
        from posthog.models import PersonalAPIKey, User
        from posthog.models.personal_api_key import hash_key_value

        # Create user without any organization memberships
        user = User.objects.create(email="test@example.com", is_active=True)

        # Create PersonalAPIKey without scoped teams
        personal_key = PersonalAPIKey.objects.create(
            user=user,
            label="Unscoped Key",
            secure_value=hash_key_value("unscoped_key_1"),
            scopes=["feature_flag:read"],
        )

        # Call the function
        result = get_teams_for_single_personal_api_key(personal_key)

        # Verify empty list was returned (no organizations = no teams)
        assert result == []

    def test_get_teams_for_scoped_personal_api_key_nonexistent_team_ids(self):
        """Test getting teams for PersonalAPIKey with non-existent scoped team IDs."""
        from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, User
        from posthog.models.personal_api_key import hash_key_value

        # Create real test data
        organization = Organization.objects.create(name="Test Organization")
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=organization, user=user)

        # Create PersonalAPIKey with non-existent scoped team IDs
        personal_key = PersonalAPIKey.objects.create(
            user=user,
            label="Scoped Key",
            secure_value=hash_key_value("scoped_key_1"),
            scoped_teams=[999, 1000],  # Non-existent team IDs
            scopes=["feature_flag:read"],
        )

        # Call the function
        result = get_teams_for_single_personal_api_key(personal_key)

        # Verify empty list was returned (no matching teams)
        assert result == []


class TestUserPersonalAPIKeyTeamLookup(TestCase):
    """Test the optimized user-based function that eliminates N+1 queries."""

    def test_user_function_matches_individual_results_scoped_keys(self):
        """Test that user-based function produces same results as individual calls for scoped keys."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create test data
        org1 = Organization.objects.create(name="Org 1")
        org2 = Organization.objects.create(name="Org 2")

        team1 = Team.objects.create(organization=org1, name="Team 1")
        team2 = Team.objects.create(organization=org1, name="Team 2")
        team3 = Team.objects.create(organization=org2, name="Team 3")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org1, user=user)
        OrganizationMembership.objects.create(organization=org2, user=user)

        # Create scoped personal API keys
        token_value1 = generate_random_token_personal()
        key1 = PersonalAPIKey.objects.create(
            label="Scoped Key 1",
            user=user,
            scoped_teams=[team1.id, team2.id],  # Scoped to specific teams
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value1),
            mask_value=mask_key_value(token_value1),
        )

        token_value2 = generate_random_token_personal()
        key2 = PersonalAPIKey.objects.create(
            label="Scoped Key 2",
            user=user,
            scoped_teams=[team3.id],  # Different scoped team
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value2),
            mask_value=mask_key_value(token_value2),
        )

        # Get results using individual function calls (N+1 pattern)
        individual_results = set()
        for key in [key1, key2]:
            individual_results.update(get_teams_for_single_personal_api_key(key))

        # Get results using user-based function (optimized)
        user_results = get_teams_for_user_personal_api_keys(user.id)

        # Results should be identical
        assert individual_results == user_results
        assert len(user_results) == 3  # Should include all 3 teams
        assert team1.api_token in user_results
        assert team2.api_token in user_results
        assert team3.api_token in user_results

    def test_user_function_matches_individual_results_unscoped_keys(self):
        """Test that user-based function produces same results as individual calls for unscoped keys."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create test data
        org1 = Organization.objects.create(name="Org 1")
        org2 = Organization.objects.create(name="Org 2")

        team1 = Team.objects.create(organization=org1, name="Team 1")
        team2 = Team.objects.create(organization=org1, name="Team 2")
        team3 = Team.objects.create(organization=org2, name="Team 3")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org1, user=user)
        OrganizationMembership.objects.create(organization=org2, user=user)

        # Create unscoped personal API keys (access to all teams in user's orgs)
        token_value1 = generate_random_token_personal()
        key1 = PersonalAPIKey.objects.create(
            label="Unscoped Key 1",
            user=user,
            scoped_teams=None,  # Unscoped
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value1),
            mask_value=mask_key_value(token_value1),
        )

        token_value2 = generate_random_token_personal()
        key2 = PersonalAPIKey.objects.create(
            label="Unscoped Key 2",
            user=user,
            scoped_teams=[],  # Empty list = unscoped
            scopes=["*"],  # All scopes
            secure_value=hash_key_value(token_value2),
            mask_value=mask_key_value(token_value2),
        )

        # Get results using individual function calls (N+1 pattern)
        individual_results = set()
        for key in [key1, key2]:
            individual_results.update(get_teams_for_single_personal_api_key(key))

        # Get results using user-based function (optimized)
        user_results = get_teams_for_user_personal_api_keys(user.id)

        # Results should be identical
        assert individual_results == user_results
        assert len(user_results) == 3  # Should include all teams in both organizations
        assert team1.api_token in user_results
        assert team2.api_token in user_results
        assert team3.api_token in user_results

    def test_user_function_mixed_scoped_and_unscoped_keys(self):
        """Test user-based function with mix of scoped and unscoped keys."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create test data
        org1 = Organization.objects.create(name="Org 1")
        org2 = Organization.objects.create(name="Org 2")

        team1 = Team.objects.create(organization=org1, name="Team 1")
        team2 = Team.objects.create(organization=org1, name="Team 2")
        team3 = Team.objects.create(organization=org2, name="Team 3")
        team4 = Team.objects.create(organization=org2, name="Team 4")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org1, user=user)
        OrganizationMembership.objects.create(organization=org2, user=user)

        # Create mix of scoped and unscoped keys
        token_value1 = generate_random_token_personal()
        scoped_key = PersonalAPIKey.objects.create(
            label="Scoped Key",
            user=user,
            scoped_teams=[team1.id],  # Only team1
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value1),
            mask_value=mask_key_value(token_value1),
        )

        token_value2 = generate_random_token_personal()
        unscoped_key = PersonalAPIKey.objects.create(
            label="Unscoped Key",
            user=user,
            scoped_teams=None,  # All teams in user's orgs
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value2),
            mask_value=mask_key_value(token_value2),
        )

        # Get results using individual function calls (N+1 pattern)
        individual_results = set()
        for key in [scoped_key, unscoped_key]:
            individual_results.update(get_teams_for_single_personal_api_key(key))

        # Get results using user-based function (optimized)
        user_results = get_teams_for_user_personal_api_keys(user.id)

        # Results should be identical
        assert individual_results == user_results
        # Should include all teams due to unscoped key (unscoped overrides scoped)
        assert len(user_results) == 4
        assert team1.api_token in user_results
        assert team2.api_token in user_results
        assert team3.api_token in user_results
        assert team4.api_token in user_results

    def test_user_function_no_personal_api_keys(self):
        """Test user-based function with user who has no personal API keys."""
        from posthog.models.user import User

        user = User.objects.create(email="test@example.com", is_active=True)

        # Should return empty set
        user_results = get_teams_for_user_personal_api_keys(user.id)
        assert user_results == set()

    def test_user_function_user_not_in_organizations(self):
        """Test user-based function with user who has keys but no organization memberships."""
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        user = User.objects.create(email="test@example.com", is_active=True)
        # Note: user has no OrganizationMembership records

        # Create unscoped personal API key
        token_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Unscoped Key",
            user=user,
            scoped_teams=None,  # Unscoped but user has no org memberships
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value),
            mask_value=mask_key_value(token_value),
        )

        # Should return empty set (user not in any organizations)
        user_results = get_teams_for_user_personal_api_keys(user.id)
        assert user_results == set()


class TestOrganizationScopedAPIKeys(TestCase):
    """Test that PersonalAPIKeys with scoped_organizations are correctly filtered in cache."""

    def setUp(self):
        """Set up test data with multiple organizations and teams."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Clear cache before tests
        cache.clear()

        # Create user
        self.user = User.objects.create(email="test@example.com", is_active=True)

        # Create two organizations
        self.org1 = Organization.objects.create(name="Org 1")
        self.org2 = Organization.objects.create(name="Org 2")

        # Add user to both organizations
        OrganizationMembership.objects.create(user=self.user, organization=self.org1)
        OrganizationMembership.objects.create(user=self.user, organization=self.org2)

        # Create teams in each organization
        self.team1_org1 = Team.objects.create(
            organization=self.org1, name="Team 1 Org 1", api_token="pht_team1_org1_token"
        )
        self.team2_org1 = Team.objects.create(
            organization=self.org1, name="Team 2 Org 1", api_token="pht_team2_org1_token"
        )
        self.team1_org2 = Team.objects.create(
            organization=self.org2, name="Team 1 Org 2", api_token="pht_team1_org2_token"
        )

        # Create various PersonalAPIKeys with different organization scoping

        # Unscoped key - should appear in all teams
        self.unscoped_token = generate_random_token_personal()
        self.unscoped_key = PersonalAPIKey.objects.create(
            label="Unscoped Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=None,  # No organization restriction
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.unscoped_token),
            mask_value=mask_key_value(self.unscoped_token),
        )

        # Key scoped to org1 only
        self.org1_scoped_token = generate_random_token_personal()
        self.org1_scoped_key = PersonalAPIKey.objects.create(
            label="Org1 Scoped Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=[str(self.org1.id)],  # Only org1
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.org1_scoped_token),
            mask_value=mask_key_value(self.org1_scoped_token),
        )

        # Key scoped to org2 only
        self.org2_scoped_token = generate_random_token_personal()
        self.org2_scoped_key = PersonalAPIKey.objects.create(
            label="Org2 Scoped Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=[str(self.org2.id)],  # Only org2
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.org2_scoped_token),
            mask_value=mask_key_value(self.org2_scoped_token),
        )

        # Key scoped to both organizations
        self.both_orgs_token = generate_random_token_personal()
        self.both_orgs_key = PersonalAPIKey.objects.create(
            label="Both Orgs Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=[str(self.org1.id), str(self.org2.id)],  # Both orgs
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.both_orgs_token),
            mask_value=mask_key_value(self.both_orgs_token),
        )

        # Key scoped to specific team and organization
        self.team_and_org_token = generate_random_token_personal()
        self.team_and_org_key = PersonalAPIKey.objects.create(
            label="Team and Org Scoped Key",
            user=self.user,
            scoped_teams=[self.team1_org1.id],  # Only team1 in org1
            scoped_organizations=[str(self.org1.id)],  # Only org1
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.team_and_org_token),
            mask_value=mask_key_value(self.team_and_org_token),
        )

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_unscoped_key_appears_in_all_team_caches(self):
        """Test that unscoped keys appear in all teams the user has access to."""
        # Warm caches for all teams
        warm_team_token_cache(self.team1_org1.api_token)
        warm_team_token_cache(self.team2_org1.api_token)
        warm_team_token_cache(self.team1_org2.api_token)

        # Check that unscoped key is in all caches
        team1_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org1.api_token)
        team2_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team2_org1.api_token)
        team1_org2_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org2.api_token)

        # Check that unscoped key is in all caches
        assert team1_org1_cache is not None
        assert team2_org1_cache is not None
        assert team1_org2_cache is not None

        assert hash_key_value(self.unscoped_token) in team1_org1_cache["hashed_tokens"]
        assert hash_key_value(self.unscoped_token) in team2_org1_cache["hashed_tokens"]
        assert hash_key_value(self.unscoped_token) in team1_org2_cache["hashed_tokens"]

    def test_org_scoped_key_only_appears_in_correct_org_teams(self):
        """Test that org-scoped keys only appear in teams within their allowed organizations."""
        # Warm caches for all teams
        warm_team_token_cache(self.team1_org1.api_token)
        warm_team_token_cache(self.team2_org1.api_token)
        warm_team_token_cache(self.team1_org2.api_token)

        team1_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org1.api_token)
        team2_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team2_org1.api_token)
        team1_org2_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org2.api_token)

        assert team1_org1_cache is not None, "Cache should exist for team1_org1"
        assert team2_org1_cache is not None, "Cache should exist for team2_org1"
        assert team1_org2_cache is not None, "Cache should exist for team1_org2"

        # Org1-scoped key should only be in org1 teams
        assert hash_key_value(self.org1_scoped_token) in team1_org1_cache["hashed_tokens"]
        assert hash_key_value(self.org1_scoped_token) in team2_org1_cache["hashed_tokens"]
        assert hash_key_value(self.org1_scoped_token) not in team1_org2_cache["hashed_tokens"]

        # Org2-scoped key should only be in org2 teams
        assert hash_key_value(self.org2_scoped_token) not in team1_org1_cache["hashed_tokens"]
        assert hash_key_value(self.org2_scoped_token) not in team2_org1_cache["hashed_tokens"]
        assert hash_key_value(self.org2_scoped_token) in team1_org2_cache["hashed_tokens"]

    def test_multi_org_scoped_key_appears_in_all_specified_orgs(self):
        """Test that keys scoped to multiple organizations appear in all specified orgs."""
        # Warm caches for all teams
        warm_team_token_cache(self.team1_org1.api_token)
        warm_team_token_cache(self.team2_org1.api_token)
        warm_team_token_cache(self.team1_org2.api_token)

        team1_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org1.api_token)
        team2_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team2_org1.api_token)
        team1_org2_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org2.api_token)

        assert team1_org1_cache is not None, "Cache should exist for team1_org1"
        assert team2_org1_cache is not None, "Cache should exist for team2_org1"
        assert team1_org2_cache is not None, "Cache should exist for team1_org2"

        # Both-orgs key should be in all teams (both org1 and org2)
        assert hash_key_value(self.both_orgs_token) in team1_org1_cache["hashed_tokens"]
        assert hash_key_value(self.both_orgs_token) in team2_org1_cache["hashed_tokens"]
        assert hash_key_value(self.both_orgs_token) in team1_org2_cache["hashed_tokens"]

    def test_team_and_org_scoped_key_only_in_specific_team(self):
        """Test that keys scoped to both team and organization only appear in the specific team."""
        # Warm caches for all teams
        warm_team_token_cache(self.team1_org1.api_token)
        warm_team_token_cache(self.team2_org1.api_token)
        warm_team_token_cache(self.team1_org2.api_token)

        team1_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org1.api_token)
        team2_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team2_org1.api_token)
        team1_org2_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org2.api_token)

        assert team1_org1_cache is not None, "Cache should exist for team1_org1"
        assert team2_org1_cache is not None, "Cache should exist for team2_org1"
        assert team1_org2_cache is not None, "Cache should exist for team1_org2"

        # Team-and-org-scoped key should only be in team1 of org1
        assert hash_key_value(self.team_and_org_token) in team1_org1_cache["hashed_tokens"]
        assert hash_key_value(self.team_and_org_token) not in team2_org1_cache["hashed_tokens"]
        assert hash_key_value(self.team_and_org_token) not in team1_org2_cache["hashed_tokens"]

    def test_org_scoped_key_outside_user_membership(self):
        """Test that org-scoped keys don't appear in teams if user is not in that org."""
        from posthog.models.organization import Organization
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create a third organization that user is NOT a member of
        org3 = Organization.objects.create(name="Org 3")
        team_org3 = Team.objects.create(organization=org3, name="Team Org 3", api_token="pht_team_org3_token")

        # Create key scoped to org3 (user not a member)
        org3_token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Org3 Scoped Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=[str(org3.id)],  # Org3 where user is not a member
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(org3_token),
            mask_value=mask_key_value(org3_token),
        )

        # Warm cache for org3 team
        warm_team_token_cache(team_org3.api_token)

        # Key should NOT appear in org3 team cache (user not in org)
        team_org3_cache = team_access_tokens_hypercache.get_from_cache(team_org3.api_token)
        assert team_org3_cache is not None, "Cache should exist for team_org3"
        assert hash_key_value(org3_token) not in team_org3_cache["hashed_tokens"]

    def test_empty_scoped_organizations_behaves_as_unscoped(self):
        """Test that empty scoped_organizations array behaves as unscoped."""
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create key with empty scoped_organizations array
        empty_org_token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Empty Org Array Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=[],  # Empty array should behave as unscoped
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(empty_org_token),
            mask_value=mask_key_value(empty_org_token),
        )

        # Warm caches
        warm_team_token_cache(self.team1_org1.api_token)
        warm_team_token_cache(self.team1_org2.api_token)

        # Key should appear in all teams (unscoped behavior)
        team1_org1_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org1.api_token)
        team1_org2_cache = team_access_tokens_hypercache.get_from_cache(self.team1_org2.api_token)

        assert team1_org1_cache is not None, "Cache should exist for team1_org1"
        assert team1_org2_cache is not None, "Cache should exist for team1_org2"

        assert hash_key_value(empty_org_token) in team1_org1_cache["hashed_tokens"]
        assert hash_key_value(empty_org_token) in team1_org2_cache["hashed_tokens"]
