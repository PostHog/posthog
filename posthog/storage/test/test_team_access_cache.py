"""
Tests for team access token cache functionality.
"""

import pytest
from unittest.mock import MagicMock, patch

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
        cached_data = team_access_tokens_hypercache.get_from_cache(self.project_api_key)
        assert cached_data is not None
        assert self.hashed_token in cached_data.get("hashed_tokens", [])

        # Invalidate cache
        self.cache.invalidate_team(self.project_api_key)

        # Verify token is no longer cached
        cached_data = team_access_tokens_hypercache.get_from_cache(self.project_api_key)
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


class TestUpdateUserAuthenticationCache(TestCase):
    """Test the update_user_authentication_cache function."""

    def setUp(self):
        """Set up test data."""
        cache.clear()
        # Note: HyperCache doesn't support wildcard clearing, individual tests will clear as needed

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_user_activated_warms_affected_team_caches(self):
        """Test that when a user is activated, caches are warmed for all teams they have access to."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1")
        team2 = Team.objects.create(organization=org, name="Team 2")
        team3 = Team.objects.create(organization=org, name="Team 3")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API keys with different scopes
        token1_value = generate_random_token_personal()
        token2_value = generate_random_token_personal()

        # Scoped key for team1 and team2
        PersonalAPIKey.objects.create(
            label="Scoped Key",
            user=user,
            scoped_teams=[team1.id, team2.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token1_value),
            mask_value=mask_key_value(token1_value),
        )

        # Another scoped key for team2 and team3
        PersonalAPIKey.objects.create(
            label="Another Scoped Key",
            user=user,
            scoped_teams=[team2.id, team3.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token2_value),
            mask_value=mask_key_value(token2_value),
        )

        # Track cache warming calls
        warmed_teams = []
        original_warm_cache = warm_team_token_cache

        def track_warm_cache(project_api_key):
            warmed_teams.append(project_api_key)
            return original_warm_cache(project_api_key)

        with patch(
            "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache", side_effect=track_warm_cache
        ):
            # Call function for user status change
            update_user_authentication_cache(instance=user, update_fields=["is_active"])

        # Verify cache warming was called for all unique teams (team1, team2, team3)
        assert len(set(warmed_teams)) == 3
        assert team1.api_token in warmed_teams
        assert team2.api_token in warmed_teams
        assert team3.api_token in warmed_teams

    def test_user_deactivated_warms_affected_team_caches(self):
        """Test that when a user is deactivated, caches are warmed for all affected teams to remove their tokens."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1")
        team2 = Team.objects.create(organization=org, name="Team 2")

        user = User.objects.create(email="test@example.com", is_active=False)  # Deactivated
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key
        token_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=user,
            scoped_teams=[team1.id, team2.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value),
            mask_value=mask_key_value(token_value),
        )

        # Track cache warming calls
        warmed_teams = []
        original_warm_cache = warm_team_token_cache

        def track_warm_cache(project_api_key):
            warmed_teams.append(project_api_key)
            return original_warm_cache(project_api_key)

        with patch(
            "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache", side_effect=track_warm_cache
        ):
            # Call function for user deactivation
            update_user_authentication_cache(instance=user, update_fields=["is_active"])

        # Verify cache warming was called for affected teams (to remove deactivated user's tokens)
        assert len(warmed_teams) == 2
        assert team1.api_token in warmed_teams
        assert team2.api_token in warmed_teams

    @parameterized.expand(
        [
            # (update_fields, num_teams, has_api_keys, expected_warm_calls, description)
            (["email", "name"], 1, True, 1, "non-is_active fields with API keys"),
            (None, 2, True, 2, "no update_fields (bulk operation) with multiple teams"),
            (["is_active"], 0, False, 0, "user with no API keys"),
        ]
    )
    def test_update_user_authentication_cache_scenarios(
        self, update_fields, num_teams, has_api_keys, expected_warm_calls, description
    ):
        """Test update_user_authentication_cache function with various scenarios."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create org and teams
        org = Organization.objects.create(name=f"Test Org {description}")
        teams = []
        for i in range(max(1, num_teams)):  # Create at least 1 team even if user has no keys
            team = Team.objects.create(organization=org, name=f"Team {i+1}")
            teams.append(team)

        user = User.objects.create(email=f"test_{description}@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key if needed
        if has_api_keys and teams:
            token_value = generate_random_token_personal()
            team_ids = [t.id for t in teams[:num_teams]] if num_teams > 0 else []
            PersonalAPIKey.objects.create(
                label="Test Key",
                user=user,
                scoped_teams=team_ids,
                scopes=["feature_flag:read"],
                secure_value=hash_key_value(token_value),
                mask_value=mask_key_value(token_value),
            )

        # Track cache warming calls
        warmed_teams = []
        original_warm_cache = warm_team_token_cache

        def track_warm_cache(project_api_key):
            warmed_teams.append(project_api_key)
            return original_warm_cache(project_api_key)

        with patch(
            "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache", side_effect=track_warm_cache
        ):
            # Call with specified update_fields
            update_user_authentication_cache(instance=user, update_fields=update_fields)

        # Verify expected cache warming calls
        assert len(warmed_teams) == expected_warm_calls
        if expected_warm_calls > 0:
            for team in teams[:num_teams]:
                assert team.api_token in warmed_teams

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_adding_user_to_organization_adds_keys_to_team_caches(self, mock_on_commit):
        """Test that adding a user to an organization adds their unscoped keys to all team caches."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create first organization with teams
        org1 = Organization.objects.create(name="Org 1")
        team1 = Team.objects.create(organization=org1, name="Team 1")

        # Create user and add to first org
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org1, user=user)

        # Create an unscoped personal API key (has access to all user's orgs)
        token = generate_random_token_personal()
        unscoped_key = PersonalAPIKey.objects.create(
            label="Unscoped Key",
            user=user,
            scoped_teams=None,  # Unscoped
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
        )

        # Create a scoped key that only has access to team1
        scoped_token = generate_random_token_personal()
        scoped_key = PersonalAPIKey.objects.create(
            label="Scoped Key",
            user=user,
            scoped_teams=[team1.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(scoped_token),
            mask_value=mask_key_value(scoped_token),
        )

        # Warm team1 cache
        warm_team_token_cache(team1.api_token)
        cache1 = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        assert cache1 is not None, "Cache should exist for team1"
        assert unscoped_key.secure_value in cache1["hashed_tokens"], "Unscoped key should be in team1"
        assert scoped_key.secure_value in cache1["hashed_tokens"], "Scoped key should be in team1"

        # Create second organization with teams
        org2 = Organization.objects.create(name="Org 2")
        team2 = Team.objects.create(organization=org2, name="Team 2")
        team3 = Team.objects.create(organization=org2, name="Team 3")

        # Warm org2 team caches BEFORE adding user
        warm_team_token_cache(team2.api_token)
        warm_team_token_cache(team3.api_token)

        # Verify keys are NOT in org2 teams yet
        cache2_before = team_access_tokens_hypercache.get_from_cache(team2.api_token)
        cache3_before = team_access_tokens_hypercache.get_from_cache(team3.api_token)
        assert cache2_before is not None, "Cache should exist for team2"
        assert cache3_before is not None, "Cache should exist for team3"
        assert (
            unscoped_key.secure_value not in cache2_before["hashed_tokens"]
        ), "Unscoped key should NOT be in team2 before joining"
        assert (
            unscoped_key.secure_value not in cache3_before["hashed_tokens"]
        ), "Unscoped key should NOT be in team3 before joining"
        assert scoped_key.secure_value not in cache2_before["hashed_tokens"], "Scoped key should NOT be in team2"
        assert scoped_key.secure_value not in cache3_before["hashed_tokens"], "Scoped key should NOT be in team3"

        # Add user to org2 - this should trigger cache updates
        OrganizationMembership.objects.create(organization=org2, user=user)

        # Verify unscoped key is now in org2 team caches, but scoped key is not
        cache2_after = team_access_tokens_hypercache.get_from_cache(team2.api_token)
        cache3_after = team_access_tokens_hypercache.get_from_cache(team3.api_token)
        assert cache2_after is not None, "Cache should exist for team2"
        assert cache3_after is not None, "Cache should exist for team3"
        assert (
            unscoped_key.secure_value in cache2_after["hashed_tokens"]
        ), "Unscoped key should be in team2 after joining"
        assert (
            unscoped_key.secure_value in cache3_after["hashed_tokens"]
        ), "Unscoped key should be in team3 after joining"
        assert scoped_key.secure_value not in cache2_after["hashed_tokens"], "Scoped key should still NOT be in team2"
        assert scoped_key.secure_value not in cache3_after["hashed_tokens"], "Scoped key should still NOT be in team3"

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_removing_user_from_organization_removes_keys_from_team_caches(self, mock_on_commit):
        """Test that removing a user from an organization removes their keys from all team caches."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create organization with multiple teams
        org = Organization.objects.create(name="Test Org for Removal")
        team1 = Team.objects.create(organization=org, name="Team 1", api_token="phc_removal_team1")
        team2 = Team.objects.create(organization=org, name="Team 2", api_token="phc_removal_team2")
        team3 = Team.objects.create(organization=org, name="Team 3", api_token="phc_removal_team3")

        # Create users
        user_to_remove = User.objects.create(email="remove_me@example.com", is_active=True)
        user_to_keep = User.objects.create(email="keep_me@example.com", is_active=True)

        # Add both users to organization
        membership_to_remove = OrganizationMembership.objects.create(organization=org, user=user_to_remove)
        OrganizationMembership.objects.create(organization=org, user=user_to_keep)

        # Create personal API keys for both users
        token_to_remove = generate_random_token_personal()
        key_to_remove = PersonalAPIKey.objects.create(
            label="Key to Remove",
            user=user_to_remove,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_to_remove),
            mask_value=mask_key_value(token_to_remove),
        )

        token_to_keep = generate_random_token_personal()
        key_to_keep = PersonalAPIKey.objects.create(
            label="Key to Keep",
            user=user_to_keep,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_to_keep),
            mask_value=mask_key_value(token_to_keep),
        )

        # Warm caches for all teams (simulate normal operation)
        for team in [team1, team2, team3]:
            warm_team_token_cache(team.api_token)

        # Verify both users' keys are in all team caches
        for team in [team1, team2, team3]:
            cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
            assert cached_data is not None, f"Cache should exist for {team.api_token}"
            hashed_tokens = cached_data["hashed_tokens"]

            assert key_to_remove.secure_value in hashed_tokens, f"User to remove's key should be in {team.name} cache"
            assert key_to_keep.secure_value in hashed_tokens, f"User to keep's key should be in {team.name} cache"

        # Remove user from organization - signal will trigger cache update
        membership_to_remove.delete()

        # After removal, caches should be updated for all teams
        # The removed user's keys should no longer be in any team cache
        for team in [team1, team2, team3]:
            cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
            assert cached_data is not None, f"Cache should still exist for {team.api_token}"
            hashed_tokens = cached_data["hashed_tokens"]

            assert (
                key_to_remove.secure_value not in hashed_tokens
            ), f"Removed user's key should NOT be in {team.name} cache"
            assert key_to_keep.secure_value in hashed_tokens, f"Kept user's key should still be in {team.name} cache"

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_personal_api_key_deleted_updates_all_team_caches(self, mock_on_commit):
        """Test that deleting a PersonalAPIKey removes it from all affected team caches."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create organization with multiple teams
        org = Organization.objects.create(name="Test Org for Key Deletion")
        team1 = Team.objects.create(organization=org, name="Team 1", api_token="phc_key_del_team1")
        team2 = Team.objects.create(organization=org, name="Team 2", api_token="phc_key_del_team2")

        # Create another org with a team to ensure we don't affect other orgs
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team", api_token="phc_key_del_other")

        # Create users
        user1 = User.objects.create(email="user1@example.com", is_active=True)
        user2 = User.objects.create(email="user2@example.com", is_active=True)

        # Add users to organizations
        OrganizationMembership.objects.create(organization=org, user=user1)
        OrganizationMembership.objects.create(organization=org, user=user2)
        OrganizationMembership.objects.create(organization=other_org, user=user1)

        # Create multiple personal API keys
        # Key 1: User1's unscoped key (affects all teams in org)
        token1 = generate_random_token_personal()
        key1_to_delete = PersonalAPIKey.objects.create(
            label="Key 1 to Delete",
            user=user1,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token1),
            mask_value=mask_key_value(token1),
        )

        # Key 2: User1's scoped key (only team1)
        token2 = generate_random_token_personal()
        key2_scoped = PersonalAPIKey.objects.create(
            label="Key 2 Scoped",
            user=user1,
            scopes=["feature_flag:write"],
            scoped_teams=[team1.id],
            secure_value=hash_key_value(token2),
            mask_value=mask_key_value(token2),
        )

        # Key 3: User2's key (to ensure it's not affected)
        token3 = generate_random_token_personal()
        key3_keep = PersonalAPIKey.objects.create(
            label="Key 3 Keep",
            user=user2,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token3),
            mask_value=mask_key_value(token3),
        )

        # Warm all caches
        for team in [team1, team2, other_team]:
            warm_team_token_cache(team.api_token)

        # Verify initial state - all keys are in appropriate caches
        cached_data_team1 = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        cached_data_team2 = team_access_tokens_hypercache.get_from_cache(team2.api_token)
        cached_data_other = team_access_tokens_hypercache.get_from_cache(other_team.api_token)

        assert cached_data_team1 is not None, "Cache should exist for team1"
        assert cached_data_team2 is not None, "Cache should exist for team2"
        assert cached_data_other is not None, "Cache should exist for other team"

        assert key1_to_delete.secure_value in cached_data_team1["hashed_tokens"], "Key1 should be in team1"
        assert key1_to_delete.secure_value in cached_data_team2["hashed_tokens"], "Key1 should be in team2"
        assert key1_to_delete.secure_value in cached_data_other["hashed_tokens"], "Key1 should be in other team"
        assert key2_scoped.secure_value in cached_data_team1["hashed_tokens"], "Key2 should be in team1"
        assert key2_scoped.secure_value not in cached_data_team2["hashed_tokens"], "Key2 should NOT be in team2"
        assert key3_keep.secure_value in cached_data_team1["hashed_tokens"], "Key3 should be in team1"
        assert key3_keep.secure_value in cached_data_team2["hashed_tokens"], "Key3 should be in team2"

        # Delete key1 (unscoped key) - signal will trigger cache update
        key1_to_delete.delete()

        # Verify key1 is removed from all caches but other keys remain
        cached_data_team1 = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        cached_data_team2 = team_access_tokens_hypercache.get_from_cache(team2.api_token)
        cached_data_other = team_access_tokens_hypercache.get_from_cache(other_team.api_token)

        assert cached_data_team1 is not None, "Cache should exist for team1"
        assert cached_data_team2 is not None, "Cache should exist for team2"
        assert cached_data_other is not None, "Cache should exist for other team"

        assert (
            key1_to_delete.secure_value not in cached_data_team1["hashed_tokens"]
        ), "Deleted key1 should NOT be in team1"
        assert (
            key1_to_delete.secure_value not in cached_data_team2["hashed_tokens"]
        ), "Deleted key1 should NOT be in team2"
        assert (
            key1_to_delete.secure_value not in cached_data_other["hashed_tokens"]
        ), "Deleted key1 should NOT be in other team"
        assert key2_scoped.secure_value in cached_data_team1["hashed_tokens"], "Key2 should still be in team1"
        assert key3_keep.secure_value in cached_data_team1["hashed_tokens"], "Key3 should still be in team1"
        assert key3_keep.secure_value in cached_data_team2["hashed_tokens"], "Key3 should still be in team2"

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_personal_api_key_rolled_updates_cache(self, mock_on_commit):
        """Test that rolling a PersonalAPIKey updates cache with new token."""

        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create two teams that the personal API key has access to
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1")
        team2 = Team.objects.create(organization=org, name="Team 2")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key with unscoped access
        original_token = generate_random_token_personal()
        original_secure = hash_key_value(original_token)
        personal_key = PersonalAPIKey.objects.create(
            label="Test Key to Roll",
            user=user,
            scoped_teams=None,  # Unscoped - has access to all teams
            scopes=["feature_flag:read"],
            secure_value=original_secure,
            mask_value=mask_key_value(original_token),
        )

        # Warm initial caches
        warm_team_token_cache(team1.api_token)
        warm_team_token_cache(team2.api_token)

        # Verify original token is in cache
        cached_data_team1 = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        cached_data_team2 = team_access_tokens_hypercache.get_from_cache(team2.api_token)

        assert cached_data_team1 is not None, "Team1 cache should exist"
        assert cached_data_team2 is not None, "Team2 cache should exist"
        assert original_secure in cached_data_team1["hashed_tokens"], "Original token should be in team1 cache"
        assert original_secure in cached_data_team2["hashed_tokens"], "Original token should be in team2 cache"

        # Roll the key using the serializer's roll method (same as API endpoint)
        from unittest.mock import MagicMock

        from posthog.api.personal_api_key import PersonalAPIKeySerializer

        # Create a mock request context for the serializer
        mock_request = MagicMock()
        mock_request.user = user
        serializer = PersonalAPIKeySerializer(instance=personal_key, context={"request": mock_request})
        rolled_key = serializer.roll(personal_key)

        # Get the new secure value from the rolled key
        new_secure = rolled_key.secure_value

        # Get updated cache data
        cached_data_team1_after = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        cached_data_team2_after = team_access_tokens_hypercache.get_from_cache(team2.api_token)

        # Verify old token is NOT in cache and new token IS in cache
        assert cached_data_team1_after is not None, "Team1 cache should still exist"
        assert cached_data_team2_after is not None, "Team2 cache should still exist"
        assert original_secure not in cached_data_team1_after["hashed_tokens"], "Old token should NOT be in team1 cache"
        assert original_secure not in cached_data_team2_after["hashed_tokens"], "Old token should NOT be in team2 cache"
        assert new_secure in cached_data_team1_after["hashed_tokens"], "New token should be in team1 cache"
        assert new_secure in cached_data_team2_after["hashed_tokens"], "New token should be in team2 cache"

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_user_deleted_removes_all_personal_api_keys_from_caches(self, mock_on_commit):
        """Test that deleting a user removes all their PersonalAPIKeys from team caches via CASCADE delete."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache import team_access_tokens_hypercache

        # Create organization with teams
        org = Organization.objects.create(name="Test Org for User Deletion")
        team1 = Team.objects.create(organization=org, name="Team 1", api_token="phc_user_del_team1")
        team2 = Team.objects.create(organization=org, name="Team 2", api_token="phc_user_del_team2")

        # Create users
        user_to_delete = User.objects.create(email="delete_me@example.com", is_active=True)
        user_to_keep = User.objects.create(email="keep_me@example.com", is_active=True)

        # Add users to organization
        OrganizationMembership.objects.create(organization=org, user=user_to_delete)
        OrganizationMembership.objects.create(organization=org, user=user_to_keep)

        # Create personal API keys for both users
        # User to delete: 2 keys
        token1 = generate_random_token_personal()
        key1 = PersonalAPIKey.objects.create(
            label="Delete User Key 1",
            user=user_to_delete,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token1),
            mask_value=mask_key_value(token1),
        )

        token2 = generate_random_token_personal()
        key2 = PersonalAPIKey.objects.create(
            label="Delete User Key 2",
            user=user_to_delete,
            scopes=["feature_flag:write"],
            secure_value=hash_key_value(token2),
            mask_value=mask_key_value(token2),
        )

        # User to keep: 1 key
        token3 = generate_random_token_personal()
        key3 = PersonalAPIKey.objects.create(
            label="Keep User Key",
            user=user_to_keep,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token3),
            mask_value=mask_key_value(token3),
        )

        # Warm caches - both users' keys should be present
        from posthog.storage.team_access_cache import warm_team_token_cache

        warm_team_token_cache(team1.api_token)
        warm_team_token_cache(team2.api_token)

        # Verify initial state - both users' keys are in caches
        for team in [team1, team2]:
            cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
            assert cached_data is not None, f"Cache should exist for {team.api_token}"
            hashed_tokens = cached_data["hashed_tokens"]

            assert key1.secure_value in hashed_tokens, f"Delete user key1 should be in {team.name} cache"
            assert key2.secure_value in hashed_tokens, f"Delete user key2 should be in {team.name} cache"
            assert key3.secure_value in hashed_tokens, f"Keep user key should be in {team.name} cache"

        # Delete the user - this should CASCADE delete their PersonalAPIKeys
        user_to_delete.delete()

        # The CASCADE delete of PersonalAPIKeys should trigger personal_api_key_deleted signals
        # which should update the caches

        # Verify deleted user's keys are removed from all team caches
        for team in [team1, team2]:
            cached_data = team_access_tokens_hypercache.get_from_cache(team.api_token)
            assert cached_data is not None, f"Cache should still exist for {team.api_token}"
            hashed_tokens = cached_data["hashed_tokens"]

            # Deleted user's keys should NOT be in cache
            assert key1.secure_value not in hashed_tokens, f"Deleted user key1 should NOT be in {team.name} cache"
            assert key2.secure_value not in hashed_tokens, f"Deleted user key2 should NOT be in {team.name} cache"

            # Kept user's key should still be in cache
            assert key3.secure_value in hashed_tokens, f"Kept user key should still be in {team.name} cache"

        # Verify PersonalAPIKeys were actually deleted
        assert not PersonalAPIKey.objects.filter(user_id=user_to_delete.id).exists(), "User's keys should be deleted"
        assert PersonalAPIKey.objects.filter(user_id=user_to_keep.id).exists(), "Other user's keys should remain"

    @pytest.mark.skip(reason="Flaky in CI, works fine locally")
    def test_update_user_authentication_cache_handles_warm_cache_failures(self):
        """Test function handles individual cache warming failures gracefully."""
        import logging

        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_user_authentication_cache

        # Create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1")
        team2 = Team.objects.create(organization=org, name="Team 2")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key
        token_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=user,
            scoped_teams=[team1.id, team2.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value),
            mask_value=mask_key_value(token_value),
        )

        # Track cache warming calls and make one fail
        warmed_teams = []
        original_warm_cache = warm_team_token_cache

        def failing_warm_cache(project_api_key):
            warmed_teams.append(project_api_key)
            if project_api_key == team1.api_token:
                raise Exception("Cache warming failed")
            return original_warm_cache(project_api_key)

        # Capture log messages
        with self.assertLogs("posthog.storage.team_access_cache_signal_handlers", level=logging.WARNING) as log_context:
            with patch(
                "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache",
                side_effect=failing_warm_cache,
            ):
                # Should not raise exception
                update_user_authentication_cache(instance=user, update_fields=["is_active"])

        # Verify both cache warming attempts were made
        assert len(warmed_teams) == 2
        assert team1.api_token in warmed_teams
        assert team2.api_token in warmed_teams

        # Verify warning was logged for the failure
        assert any(f"Failed to warm cache for team {team1.api_token}" in record for record in log_context.output)

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    @patch("posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache")
    def test_personal_api_key_last_used_at_update_skips_cache_warming(self, mock_warm_cache, mock_on_commit):
        """Test that updating only last_used_at field doesn't trigger cache warming."""

        from django.utils import timezone

        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create test data
        org = Organization.objects.create(name="Test Org")
        Team.objects.create(organization=org, name="Team 1")  # Team is created to ensure proper org setup
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key
        token = generate_random_token_personal()
        personal_key = PersonalAPIKey.objects.create(
            label="Test Key",
            user=user,
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
        )

        # Clear any calls from the initial creation
        mock_warm_cache.reset_mock()

        # Update only the last_used_at field (simulating authentication)
        now = timezone.now()
        personal_key.last_used_at = now
        personal_key.save(update_fields=["last_used_at"])

        # Verify that cache update was NOT called
        mock_warm_cache.assert_not_called()

        # Now update a different field
        mock_warm_cache.reset_mock()
        personal_key.label = "Updated Label"
        personal_key.save(update_fields=["label"])

        # Verify that cache update WAS called for non-last_used_at update
        # It should be called once per team the user has access to
        assert mock_warm_cache.call_count > 0, "Cache warming should be called for non-last_used_at updates"

        # Reset and test updating without specifying update_fields
        mock_warm_cache.reset_mock()
        personal_key.label = "Another Label"
        personal_key.save()

        # Should trigger cache update when update_fields is not specified
        assert mock_warm_cache.call_count > 0, "Cache warming should be called when update_fields is not specified"


class TestSignalHandlerCacheWarming(TestCase):
    """Test that signal handlers properly warm caches instead of just invalidating."""

    def setUp(self):
        """Set up test data."""
        cache.clear()
        # Note: HyperCache doesn't support wildcard clearing, individual tests will clear as needed

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    def test_personal_api_key_signal_handlers_warm_caches(self):
        """Test that personal API key signal handlers warm caches efficiently."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_authentication_cache

        # Create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1")
        team2 = Team.objects.create(organization=org, name="Team 2")
        team3 = Team.objects.create(organization=org, name="Team 3")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key
        token_value = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            label="Test Key",
            user=user,
            scoped_teams=[team1.id, team2.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value),
            mask_value=mask_key_value(token_value),
        )

        # Track cache warming calls for save handler
        warmed_teams_save = []
        original_warm_cache = warm_team_token_cache

        def track_warm_cache_save(project_api_key):
            warmed_teams_save.append(project_api_key)
            return original_warm_cache(project_api_key)

        with patch(
            "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache", side_effect=track_warm_cache_save
        ):
            # Test save handler
            update_personal_api_key_authentication_cache(instance=key)

        # Verify cache warming was called for each affected team
        assert len(warmed_teams_save) == 2
        assert team1.api_token in warmed_teams_save
        assert team2.api_token in warmed_teams_save

        # Test delete handler with different team scope
        key.scoped_teams = [team3.id]
        key.save()

        warmed_teams_delete = []

        def track_warm_cache_delete(project_api_key):
            warmed_teams_delete.append(project_api_key)
            return original_warm_cache(project_api_key)

        with patch(
            "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache",
            side_effect=track_warm_cache_delete,
        ):
            update_personal_api_key_authentication_cache(instance=key)

        # Verify cache warming was called for the new scope
        assert len(warmed_teams_delete) == 1
        assert team3.api_token in warmed_teams_delete

    @patch("posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache")
    def test_team_signal_handlers_warm_caches(self, mock_warm_cache):
        """Test that team signal handlers warm caches instead of just invalidating."""
        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache

        # Create mock Team
        mock_team = MagicMock()
        mock_team.pk = 123
        mock_team.api_token = "phs_team_token_123"
        mock_team._state = MagicMock()
        mock_team._state.adding = False  # Not being created

        # Test save handler (not created)
        update_team_authentication_cache(instance=mock_team, created=False)

        # Verify cache warming was called (not just invalidation)
        mock_warm_cache.assert_called_once_with("phs_team_token_123")

        # Test that it doesn't warm cache for new teams (created=True)
        mock_warm_cache.reset_mock()
        update_team_authentication_cache(instance=mock_team, created=True)

        # Should not warm cache for new teams
        mock_warm_cache.assert_not_called()

    def test_team_deletion_invalidates_cache_and_removes_access(self):
        """Test that team deletion properly invalidates cache and removes all access."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache_on_delete

        # Create organization with multiple teams
        org = Organization.objects.create(name="Test Org for Team Deletion")
        team_to_delete = Team.objects.create(
            organization=org,
            name="Team to Delete",
            api_token="phc_team_delete_1",
            secret_api_token="phsk_team_secret_delete",
        )
        team_to_keep = Team.objects.create(organization=org, name="Team to Keep", api_token="phc_team_keep_1")

        # Create users and add to organization
        user1 = User.objects.create(email="user1@example.com", is_active=True)
        user2 = User.objects.create(email="user2@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user1)
        OrganizationMembership.objects.create(organization=org, user=user2)

        # Create PersonalAPIKeys
        # Key 1: Scoped to team_to_delete only
        token1 = generate_random_token_personal()
        key1_scoped_to_deleted = PersonalAPIKey.objects.create(
            label="Key Scoped to Deleted Team",
            user=user1,
            scopes=["feature_flag:read"],
            scoped_teams=[team_to_delete.id],
            secure_value=hash_key_value(token1),
            mask_value=mask_key_value(token1),
        )

        # Key 2: Scoped to both teams
        token2 = generate_random_token_personal()
        key2_scoped_to_both = PersonalAPIKey.objects.create(
            label="Key Scoped to Both Teams",
            user=user1,
            scopes=["feature_flag:write"],
            scoped_teams=[team_to_delete.id, team_to_keep.id],
            secure_value=hash_key_value(token2),
            mask_value=mask_key_value(token2),
        )

        # Key 3: Unscoped (all teams)
        token3 = generate_random_token_personal()
        key3_unscoped = PersonalAPIKey.objects.create(
            label="Unscoped Key",
            user=user2,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token3),
            mask_value=mask_key_value(token3),
        )

        # Warm both caches
        warm_team_token_cache(team_to_delete.api_token)
        warm_team_token_cache(team_to_keep.api_token)

        # Verify initial state
        cache_delete = team_access_tokens_hypercache.get_from_cache(team_to_delete.api_token)
        cache_keep = team_access_tokens_hypercache.get_from_cache(team_to_keep.api_token)

        assert cache_delete is not None
        assert cache_keep is not None

        # Verify keys are in appropriate caches
        assert key1_scoped_to_deleted.secure_value in cache_delete["hashed_tokens"]
        assert key2_scoped_to_both.secure_value in cache_delete["hashed_tokens"]
        assert key3_unscoped.secure_value in cache_delete["hashed_tokens"]
        assert hash_key_value(team_to_delete.secret_api_token, mode="sha256") in cache_delete["hashed_tokens"]

        assert key1_scoped_to_deleted.secure_value not in cache_keep["hashed_tokens"]  # Not scoped to this team
        assert key2_scoped_to_both.secure_value in cache_keep["hashed_tokens"]
        assert key3_unscoped.secure_value in cache_keep["hashed_tokens"]

        # Store the team ID before deletion for later verification
        deleted_team_id = team_to_delete.id
        deleted_team_api_token = team_to_delete.api_token

        # Delete the team
        team_to_delete.delete()

        # Since we're in a test transaction, manually trigger the cache update
        # Create a mock instance with the necessary attributes for the handler
        from unittest.mock import MagicMock

        mock_deleted_team = MagicMock()
        mock_deleted_team.api_token = deleted_team_api_token
        mock_deleted_team.pk = deleted_team_id

        update_team_authentication_cache_on_delete(instance=mock_deleted_team)

        # Verify the deleted team's cache is invalidated
        cache_delete_after = team_access_tokens_hypercache.get_from_cache(deleted_team_api_token)
        assert cache_delete_after is None, "Deleted team's cache should be invalidated"

        # Verify the kept team's cache is unaffected but properly updated
        # We need to refresh it to simulate what would happen in production
        warm_team_token_cache(team_to_keep.api_token)
        cache_keep_after = team_access_tokens_hypercache.get_from_cache(team_to_keep.api_token)

        assert cache_keep_after is not None
        # Key1 was only for deleted team, still shouldn't be in kept team
        assert key1_scoped_to_deleted.secure_value not in cache_keep_after["hashed_tokens"]
        # Key2 is scoped to both teams, but after deletion it should still be in kept team
        # (the key itself still exists and is still scoped to team_to_keep)
        assert key2_scoped_to_both.secure_value in cache_keep_after["hashed_tokens"]
        # Key3 is unscoped, should still be in kept team
        assert key3_unscoped.secure_value in cache_keep_after["hashed_tokens"]

    def test_organization_deletion_invalidates_all_team_caches(self):
        """Test that organization deletion invalidates all team caches via cascade."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create two organizations
        org_to_delete = Organization.objects.create(name="Org to Delete")
        org_to_keep = Organization.objects.create(name="Org to Keep")

        # Create teams in both orgs
        teams_to_delete = []
        for i in range(3):
            team = Team.objects.create(
                organization=org_to_delete,
                name=f"Team {i} to Delete",
                api_token=f"phc_org_del_team{i}",
                secret_api_token=f"phsk_org_del_secret{i}",
            )
            teams_to_delete.append(team)

        team_to_keep = Team.objects.create(organization=org_to_keep, name="Team to Keep", api_token="phc_org_keep_team")

        # Create users
        user1 = User.objects.create(email="user1@example.com", is_active=True)
        user2 = User.objects.create(email="user2@example.com", is_active=True)

        # Add users to both organizations
        OrganizationMembership.objects.create(organization=org_to_delete, user=user1)
        OrganizationMembership.objects.create(organization=org_to_delete, user=user2)
        OrganizationMembership.objects.create(organization=org_to_keep, user=user1)

        # Create PersonalAPIKeys
        # Key 1: Scoped to a team in org_to_delete
        token1 = generate_random_token_personal()
        key1 = PersonalAPIKey.objects.create(
            label="Key for Deleted Org Team",
            user=user1,
            scopes=["feature_flag:read"],
            scoped_teams=[teams_to_delete[0].id],
            secure_value=hash_key_value(token1),
            mask_value=mask_key_value(token1),
        )

        # Key 2: Unscoped (affects all teams in both orgs)
        token2 = generate_random_token_personal()
        key2 = PersonalAPIKey.objects.create(
            label="Unscoped Key",
            user=user1,
            scopes=["feature_flag:write"],
            secure_value=hash_key_value(token2),
            mask_value=mask_key_value(token2),
        )

        # Key 3: Scoped to team in org_to_keep
        token3 = generate_random_token_personal()
        key3 = PersonalAPIKey.objects.create(
            label="Key for Kept Org Team",
            user=user1,
            scopes=["feature_flag:read"],
            scoped_teams=[team_to_keep.id],
            secure_value=hash_key_value(token3),
            mask_value=mask_key_value(token3),
        )

        # Warm all caches
        for team in [*teams_to_delete, team_to_keep]:
            warm_team_token_cache(team.api_token)

        # Verify initial state - all caches exist
        for team in teams_to_delete:
            cache = team_access_tokens_hypercache.get_from_cache(team.api_token)
            assert cache is not None, f"Cache should exist for {team.api_token}"
            # Verify keys are properly set up
            if team == teams_to_delete[0]:
                assert key1.secure_value in cache["hashed_tokens"]
            assert key2.secure_value in cache["hashed_tokens"]  # Unscoped key in all teams

        cache_keep = team_access_tokens_hypercache.get_from_cache(team_to_keep.api_token)
        assert cache_keep is not None
        assert key2.secure_value in cache_keep["hashed_tokens"]  # Unscoped key
        assert key3.secure_value in cache_keep["hashed_tokens"]  # Scoped to this team

        # Store API tokens before deletion
        deleted_team_api_tokens = [team.api_token for team in teams_to_delete]

        # Delete the organization
        # This will CASCADE delete all teams, which will trigger team deletion handlers
        org_to_delete.delete()

        # Since we're in a test transaction, manually trigger cache invalidation for each team
        from unittest.mock import MagicMock

        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache_on_delete

        for i, api_token in enumerate(deleted_team_api_tokens):
            mock_team = MagicMock()
            mock_team.api_token = api_token
            mock_team.pk = teams_to_delete[i].id if i < len(teams_to_delete) else i
            update_team_authentication_cache_on_delete(instance=mock_team)

        # Verify all caches for deleted org's teams are invalidated
        for api_token in deleted_team_api_tokens:
            cache = team_access_tokens_hypercache.get_from_cache(api_token)
            assert cache is None, f"Cache should be invalidated for deleted team {api_token}"

        # Verify the kept org's team cache is unaffected
        # Refresh the cache to simulate production behavior
        warm_team_token_cache(team_to_keep.api_token)
        cache_keep_after = team_access_tokens_hypercache.get_from_cache(team_to_keep.api_token)
        assert cache_keep_after is not None, "Kept team's cache should still exist"

        # Key1 was scoped to deleted team, no longer relevant
        assert key1.secure_value not in cache_keep_after["hashed_tokens"]
        # Key2 is unscoped, still has access to kept team
        assert key2.secure_value in cache_keep_after["hashed_tokens"]
        # Key3 is scoped to kept team, still has access
        assert key3.secure_value in cache_keep_after["hashed_tokens"]

    def test_personal_api_key_with_deleted_team_references(self):
        """Test that PersonalAPIKeys handle orphaned team references gracefully."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create organization and teams
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1", api_token="phc_orphan_team1")
        team2 = Team.objects.create(organization=org, name="Team 2", api_token="phc_orphan_team2")
        team3_to_delete = Team.objects.create(organization=org, name="Team 3 to Delete", api_token="phc_orphan_team3")

        # Create user and add to organization
        user = User.objects.create(email="user@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create PersonalAPIKey scoped to all three teams
        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            label="Key Scoped to Multiple Teams",
            user=user,
            scopes=["feature_flag:read"],
            scoped_teams=[team1.id, team2.id, team3_to_delete.id],
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
        )

        # Warm caches for all teams
        warm_team_token_cache(team1.api_token)
        warm_team_token_cache(team2.api_token)
        warm_team_token_cache(team3_to_delete.api_token)

        # Verify initial state - key is in all three caches
        cache1 = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        cache2 = team_access_tokens_hypercache.get_from_cache(team2.api_token)
        cache3 = team_access_tokens_hypercache.get_from_cache(team3_to_delete.api_token)

        assert cache1 is not None, "Cache should exist for team1"
        assert cache2 is not None, "Cache should exist for team2"
        assert cache3 is not None, "Cache should exist for team3"

        assert key.secure_value in cache1["hashed_tokens"]
        assert key.secure_value in cache2["hashed_tokens"]
        assert key.secure_value in cache3["hashed_tokens"]

        # Store the deleted team ID and API token
        deleted_team_id = team3_to_delete.id
        deleted_team_api_token = team3_to_delete.api_token

        # Delete team3
        team3_to_delete.delete()

        # Since we're in a test transaction, manually trigger the cache invalidation
        from unittest.mock import MagicMock

        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache_on_delete

        mock_deleted_team = MagicMock()
        mock_deleted_team.api_token = deleted_team_api_token
        mock_deleted_team.pk = deleted_team_id
        update_team_authentication_cache_on_delete(instance=mock_deleted_team)

        # The PersonalAPIKey still exists in the database with scoped_teams including the deleted team ID
        key.refresh_from_db()
        assert deleted_team_id in key.scoped_teams, "Deleted team ID should still be in scoped_teams"

        # Warm the remaining team caches
        # This should handle the orphaned reference gracefully
        warm_team_token_cache(team1.api_token)
        warm_team_token_cache(team2.api_token)

        # Verify the key is still in the remaining teams' caches
        cache1_after = team_access_tokens_hypercache.get_from_cache(team1.api_token)
        cache2_after = team_access_tokens_hypercache.get_from_cache(team2.api_token)

        assert cache1_after is not None, "Cache should exist for team1"
        assert cache2_after is not None, "Cache should exist for team2"

        assert key.secure_value in cache1_after["hashed_tokens"], "Key should still be in team1's cache"
        assert key.secure_value in cache2_after["hashed_tokens"], "Key should still be in team2's cache"

        # Verify the deleted team's cache is invalidated
        cache3_after = team_access_tokens_hypercache.get_from_cache(deleted_team_api_token)
        assert cache3_after is None, "Deleted team's cache should be invalidated"

        # Test that the system doesn't break when loading tokens for a key with orphaned references
        # This simulates what happens when the cache is being rebuilt
        from posthog.storage.team_access_cache import get_teams_for_single_personal_api_key

        # This should not raise an exception despite having an orphaned team reference
        try:
            affected_teams = get_teams_for_single_personal_api_key(key)
            # Should only return the existing teams, not the deleted one
            assert set(affected_teams) == {team1.api_token, team2.api_token}
        except Exception as e:
            raise AssertionError(f"Should handle orphaned team references gracefully, but raised: {e}")

    @pytest.mark.skip(reason="Flaky in CI, works fine locally")
    def test_signal_handlers_handle_cache_warming_failures(self):
        """Test that signal handlers handle cache warming failures gracefully."""
        import logging

        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_authentication_cache

        # Create real database objects
        org = Organization.objects.create(name="Test Org")
        team1 = Team.objects.create(organization=org, name="Team 1")
        team2 = Team.objects.create(organization=org, name="Team 2")

        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key
        token_value = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            label="Test Key",
            user=user,
            scoped_teams=[team1.id, team2.id],
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value),
            mask_value=mask_key_value(token_value),
        )

        # Track cache warming calls and make one fail
        warmed_teams = []
        original_warm_cache = warm_team_token_cache

        def failing_warm_cache(project_api_key):
            warmed_teams.append(project_api_key)
            if project_api_key == team1.api_token:
                raise Exception("Cache warming failed")
            return original_warm_cache(project_api_key)

        # Capture log messages
        with self.assertLogs("posthog.storage.team_access_cache_signal_handlers", level=logging.WARNING) as log_context:
            with patch(
                "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache",
                side_effect=failing_warm_cache,
            ):
                # Should not raise exception
                update_personal_api_key_authentication_cache(instance=key)

        # Verify both cache warming attempts were made
        assert len(warmed_teams) == 2
        assert team1.api_token in warmed_teams
        assert team2.api_token in warmed_teams

        # Verify warning was logged for the failure
        assert any(f"Failed to warm cache for team {team1.api_token}" in record for record in log_context.output)

    def test_signal_handlers_handle_empty_affected_teams(self):
        """Test signal handlers handle cases where no teams are affected."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, mask_key_value
        from posthog.storage.team_access_cache_signal_handlers import update_personal_api_key_authentication_cache

        # Create org and user but no teams
        org = Organization.objects.create(name="Test Org")
        user = User.objects.create(email="test@example.com", is_active=True)
        OrganizationMembership.objects.create(organization=org, user=user)

        # Create personal API key with no scoped teams (empty list means no teams)
        token_value = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            label="Test Key",
            user=user,
            scoped_teams=[],  # Empty list - no teams
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(token_value),
            mask_value=mask_key_value(token_value),
        )

        # Track cache warming calls
        warmed_teams = []
        original_warm_cache = warm_team_token_cache

        def track_warm_cache(project_api_key):
            warmed_teams.append(project_api_key)
            return original_warm_cache(project_api_key)

        with patch(
            "posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache", side_effect=track_warm_cache
        ):
            # Should not raise exception
            update_personal_api_key_authentication_cache(instance=key)

        # Verify no cache warming attempts (no teams affected)
        assert len(warmed_teams) == 0

    @parameterized.expand(
        [
            # (update_fields, created, adding_state, should_warm_cache, description)
            (["name", "timezone", "capture_performance_opt_in"], False, False, False, "non-auth fields"),
            (["name", "secret_api_token", "timezone"], False, False, True, "auth field secret_api_token"),
            (["secret_api_token_backup"], False, False, True, "auth field secret_api_token_backup"),
            (None, False, False, True, "no update_fields (full save)"),
            (["secret_api_token"], False, True, False, "newly created team via state"),
            ([], False, False, False, "empty update_fields list"),
        ]
    )
    @patch("posthog.storage.team_access_cache_signal_handlers.warm_team_token_cache")
    def test_team_signal_handler_update_fields_scenarios(
        self, update_fields, created, adding_state, should_warm_cache, description, mock_warm_cache
    ):
        """Test team signal handler behavior for various update_fields scenarios."""
        from posthog.storage.team_access_cache_signal_handlers import update_team_authentication_cache

        # Create mock Team
        mock_team = MagicMock()
        mock_team.pk = 123
        mock_team.api_token = "phs_team_token_123"
        mock_team._state = MagicMock()
        mock_team._state.adding = adding_state

        # Call the signal handler
        update_team_authentication_cache(instance=mock_team, created=created, update_fields=update_fields)

        # Verify cache warming behavior
        if should_warm_cache:
            mock_warm_cache.assert_called_once_with("phs_team_token_123")
        else:
            mock_warm_cache.assert_not_called()


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
            scopes=None,  # No scopes = access to everything
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


class TestOrganizationScopingSignalHandlers(TestCase):
    """Test that signal handlers properly update caches when scoped_organizations changes."""

    def setUp(self):
        """Set up test data."""
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

        # Create teams
        self.team_org1 = Team.objects.create(
            organization=self.org1, name="Team Org 1", api_token="pht_team_org1_signal_test"
        )
        self.team_org2 = Team.objects.create(
            organization=self.org2, name="Team Org 2", api_token="pht_team_org2_signal_test"
        )

        # Create a personal API key initially unscoped
        self.token = generate_random_token_personal()
        self.personal_key = PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=None,  # Initially unscoped
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.token),
            mask_value=mask_key_value(self.token),
        )

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_updating_scoped_organizations_updates_caches(self, mock_on_commit):
        """Test that changing scoped_organizations field triggers cache updates."""
        # Initially warm caches - key should be in both
        warm_team_token_cache(self.team_org1.api_token)
        warm_team_token_cache(self.team_org2.api_token)

        cache1 = team_access_tokens_hypercache.get_from_cache(self.team_org1.api_token)
        cache2 = team_access_tokens_hypercache.get_from_cache(self.team_org2.api_token)

        assert cache1 is not None, "Cache should exist for team_org1"
        assert cache2 is not None, "Cache should exist for team_org2"

        # Initially unscoped, so should be in both teams
        assert hash_key_value(self.token) in cache1["hashed_tokens"]
        assert hash_key_value(self.token) in cache2["hashed_tokens"]

        # Update to be scoped to org1 only
        self.personal_key.scoped_organizations = [str(self.org1.id)]
        self.personal_key.save(update_fields=["scoped_organizations"])

        # Check caches again - should only be in org1 teams now
        cache1_after = team_access_tokens_hypercache.get_from_cache(self.team_org1.api_token)
        cache2_after = team_access_tokens_hypercache.get_from_cache(self.team_org2.api_token)

        assert cache1_after is not None, "Cache should exist for team_org1 after"
        assert cache2_after is not None, "Cache should exist for team_org2 after"

        assert hash_key_value(self.token) in cache1_after["hashed_tokens"]
        assert hash_key_value(self.token) not in cache2_after["hashed_tokens"]

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_removing_organization_scoping_updates_caches(self, mock_on_commit):
        """Test that removing organization scoping makes key available to all orgs again."""
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.utils import generate_random_token_personal, mask_key_value

        # Create a key scoped to org1 only
        scoped_token = generate_random_token_personal()
        scoped_key = PersonalAPIKey.objects.create(
            label="Scoped Key",
            user=self.user,
            scoped_teams=None,
            scoped_organizations=[str(self.org1.id)],  # Initially scoped to org1
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(scoped_token),
            mask_value=mask_key_value(scoped_token),
        )

        # Warm caches
        warm_team_token_cache(self.team_org1.api_token)
        warm_team_token_cache(self.team_org2.api_token)

        # Check initial state - only in org1
        cache1 = team_access_tokens_hypercache.get_from_cache(self.team_org1.api_token)
        cache2 = team_access_tokens_hypercache.get_from_cache(self.team_org2.api_token)

        assert cache1 is not None, "Cache should exist for team_org1"
        assert cache2 is not None, "Cache should exist for team_org2"

        assert hash_key_value(scoped_token) in cache1["hashed_tokens"]
        assert hash_key_value(scoped_token) not in cache2["hashed_tokens"]

        # Remove organization scoping
        scoped_key.scoped_organizations = None
        scoped_key.save(update_fields=["scoped_organizations"])

        # Check caches again - should be in both orgs now
        cache1_after = team_access_tokens_hypercache.get_from_cache(self.team_org1.api_token)
        cache2_after = team_access_tokens_hypercache.get_from_cache(self.team_org2.api_token)

        assert cache1_after is not None, "Cache should exist for team_org1 after"
        assert cache2_after is not None, "Cache should exist for team_org2 after"

        assert hash_key_value(scoped_token) in cache1_after["hashed_tokens"]
        assert hash_key_value(scoped_token) in cache2_after["hashed_tokens"]


class TestSecretTokenRotation(TestCase):
    """Test that changes to secret_api_token and secret_api_token_backup update the cache."""

    def setUp(self):
        """Set up test data."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_secret

        # Clear cache before tests
        cache.clear()

        # Create user and organization
        self.user = User.objects.create(email="test@example.com", is_active=True)
        self.org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(user=self.user, organization=self.org)

        # Create team with initial secret token
        self.initial_token = generate_random_token_secret()
        self.team = Team.objects.create(
            organization=self.org,
            name="Test Team",
            api_token="pht_test_rotation_token",
            secret_api_token=self.initial_token,
            secret_api_token_backup=None,
        )

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_secret_api_token_changes_update_cache(self, mock_on_commit):
        """Test that changing secret_api_token updates the cache correctly."""
        from posthog.models.personal_api_key import hash_key_value
        from posthog.models.utils import generate_random_token_secret

        # Warm initial cache
        warm_team_token_cache(self.team.api_token)

        # Verify initial token is in cache
        cache_data = team_access_tokens_hypercache.get_from_cache(self.team.api_token)
        assert cache_data is not None
        initial_token_hash = hash_key_value(self.initial_token, mode="sha256")
        assert initial_token_hash in cache_data["hashed_tokens"]

        # Change secret_api_token
        new_token = generate_random_token_secret()
        self.team.secret_api_token = new_token
        self.team.save(update_fields=["secret_api_token"])

        # Check cache was updated - new token in, old token out
        cache_data = team_access_tokens_hypercache.get_from_cache(self.team.api_token)
        assert cache_data is not None
        assert hash_key_value(new_token, mode="sha256") in cache_data["hashed_tokens"]
        assert hash_key_value(self.initial_token, mode="sha256") not in cache_data["hashed_tokens"]

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_secret_api_token_backup_changes_update_cache(self, mock_on_commit):
        """Test that changing secret_api_token_backup updates the cache correctly."""
        from posthog.models.personal_api_key import hash_key_value
        from posthog.models.utils import generate_random_token_secret

        # Warm initial cache
        warm_team_token_cache(self.team.api_token)

        # Start with backup=None, verify only primary token in cache
        cache_data = team_access_tokens_hypercache.get_from_cache(self.team.api_token)
        assert cache_data is not None
        assert hash_key_value(self.team.secret_api_token, mode="sha256") in cache_data["hashed_tokens"]

        # Set backup to a value
        backup_token1 = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token1
        self.team.save(update_fields=["secret_api_token_backup"])

        # Verify both tokens in cache
        cache_data = team_access_tokens_hypercache.get_from_cache(self.team.api_token)
        assert cache_data is not None, "Cache should exist after backup token set"
        assert hash_key_value(self.team.secret_api_token, mode="sha256") in cache_data["hashed_tokens"]
        assert hash_key_value(backup_token1, mode="sha256") in cache_data["hashed_tokens"]

        # Change backup to different value
        backup_token2 = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token2
        self.team.save(update_fields=["secret_api_token_backup"])

        # Verify new backup in cache, old backup not in cache
        cache_data = team_access_tokens_hypercache.get_from_cache(self.team.api_token)
        assert cache_data is not None, "Cache should exist after backup token change"
        assert hash_key_value(self.team.secret_api_token, mode="sha256") in cache_data["hashed_tokens"]
        assert hash_key_value(backup_token2, mode="sha256") in cache_data["hashed_tokens"]
        assert hash_key_value(backup_token1, mode="sha256") not in cache_data["hashed_tokens"]

        # Set backup=None
        self.team.secret_api_token_backup = None
        self.team.save(update_fields=["secret_api_token_backup"])

        # Verify only primary token remains
        cache_data = team_access_tokens_hypercache.get_from_cache(self.team.api_token)
        assert cache_data is not None
        assert hash_key_value(self.team.secret_api_token, mode="sha256") in cache_data["hashed_tokens"]
        assert hash_key_value(backup_token2, mode="sha256") not in cache_data["hashed_tokens"]


class TestTeamAPITokenRegeneration(TestCase):
    """Test that regenerating team API token properly cleans up old cache."""

    def setUp(self):
        """Set up test data."""
        from posthog.models.organization import Organization, OrganizationMembership
        from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
        from posthog.models.team.team import Team
        from posthog.models.user import User
        from posthog.models.utils import generate_random_token_personal, generate_random_token_project, mask_key_value

        # Clear cache before tests
        cache.clear()

        # Create user and organization
        self.user = User.objects.create(email="test@example.com", is_active=True)
        self.org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(user=self.user, organization=self.org)

        # Create team with initial API token
        self.initial_api_token = generate_random_token_project()
        self.team = Team.objects.create(organization=self.org, name="Test Team", api_token=self.initial_api_token)

        # Create a personal API key to have some data in cache
        self.personal_token = generate_random_token_personal()
        self.personal_key = PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            scoped_teams=None,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(self.personal_token),
            mask_value=mask_key_value(self.personal_token),
        )

    def tearDown(self):
        """Clean up after tests."""
        cache.clear()

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_regenerating_api_token_cleans_up_old_cache(self, mock_on_commit):
        """Test that regenerating team's API token removes old cache entry."""
        from posthog.models.utils import generate_random_token_project

        # Warm initial cache
        warm_team_token_cache(self.initial_api_token)

        # Verify initial cache exists
        initial_cache = team_access_tokens_hypercache.get_from_cache(self.initial_api_token)
        assert initial_cache is not None
        assert "hashed_tokens" in initial_cache

        # Store the old token for later verification
        old_api_token = self.team.api_token

        # Regenerate the API token
        new_api_token = generate_random_token_project()
        self.team.api_token = new_api_token
        self.team.save(update_fields=["api_token"])

        # Check that new cache exists
        new_cache = team_access_tokens_hypercache.get_from_cache(new_api_token)
        assert new_cache is not None
        assert "hashed_tokens" in new_cache

        # Check that old cache is cleaned up
        old_cache = team_access_tokens_hypercache.get_from_cache(old_api_token)
        assert old_cache is None, "Old cache should be cleaned up after API token regeneration"

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_api_token_change_preserves_data_in_new_cache(self, mock_on_commit):
        """Test that changing API token preserves all token data in new cache."""
        from posthog.models.personal_api_key import hash_key_value
        from posthog.models.utils import generate_random_token_project

        # Warm initial cache
        warm_team_token_cache(self.initial_api_token)

        # Verify personal key is in initial cache
        initial_cache = team_access_tokens_hypercache.get_from_cache(self.initial_api_token)
        assert initial_cache is not None, "Initial cache should exist"
        assert hash_key_value(self.personal_token) in initial_cache["hashed_tokens"]

        # Regenerate the API token
        new_api_token = generate_random_token_project()
        old_api_token = self.team.api_token
        self.team.api_token = new_api_token
        self.team.save(update_fields=["api_token"])

        # Verify personal key is still in new cache
        new_cache = team_access_tokens_hypercache.get_from_cache(new_api_token)
        assert new_cache is not None, "New cache should exist after API token change"
        assert hash_key_value(self.personal_token) in new_cache["hashed_tokens"]

        # Verify old cache is gone
        old_cache = team_access_tokens_hypercache.get_from_cache(old_api_token)
        assert old_cache is None
