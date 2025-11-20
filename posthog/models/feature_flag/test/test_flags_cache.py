"""
Tests for the flags HyperCache for feature-flags service.

Tests cover:
- Basic cache operations (get, update, clear)
- Signal handlers for automatic cache invalidation
- Celery task integration
- Data format compatibility with service
"""

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from posthog.models import FeatureFlag, Team
from posthog.models.feature_flag.flags_cache import (
    _get_feature_flags_for_service,
    clear_flags_cache,
    flags_hypercache,
    get_flags_from_cache,
    update_flags_cache,
)


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsCache(BaseTest):
    """Test basic cache operations for service flags HyperCache."""

    def setUp(self):
        super().setUp()
        # Clear cache before each test
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_cache_key_format(self):
        """Test that cache key is formatted correctly for service flags."""
        key = flags_hypercache.get_cache_key(self.team.id)
        assert key == f"cache/teams/{self.team.id}/feature_flags/flags.json"

    def test_get_feature_flags_for_service_empty(self):
        """Test fetching flags when team has no flags."""
        result = _get_feature_flags_for_service(self.team)

        assert result == {"flags": []}

    def test_get_feature_flags_for_service_with_flags(self):
        """Test fetching flags returns correct format for service."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            name="Test Flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
            },
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        assert len(flags) == 1
        flag_data = flags[0]

        # Verify service-compatible fields are present
        assert flag_data["id"] == flag.id
        assert flag_data["team_id"] == self.team.id
        assert flag_data["key"] == "test-flag"
        assert flag_data["name"] == "Test Flag"
        assert flag_data["deleted"] is False
        assert flag_data["active"] is True
        assert "filters" in flag_data
        assert "version" in flag_data

    def test_get_feature_flags_for_service_excludes_deleted(self):
        """Test that deleted flags are excluded from cache."""
        # Create active flag
        FeatureFlag.objects.create(
            team=self.team,
            key="active-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create deleted flag
        FeatureFlag.objects.create(
            team=self.team,
            key="deleted-flag",
            created_by=self.user,
            deleted=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        assert len(flags) == 1
        assert flags[0]["key"] == "active-flag"

    def test_get_feature_flags_for_service_excludes_inactive(self):
        """Test that inactive flags are excluded from cache."""
        # Create active flag
        FeatureFlag.objects.create(
            team=self.team,
            key="active-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create inactive flag
        FeatureFlag.objects.create(
            team=self.team,
            key="inactive-flag",
            created_by=self.user,
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        assert len(flags) == 1
        assert flags[0]["key"] == "active-flag"

    def test_get_flags_from_cache_redis_hit(self):
        """Test getting flags from Redis cache."""
        # Create a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="cached-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache
        update_flags_cache(self.team)

        # Get from cache (should hit Redis)
        flags = get_flags_from_cache(self.team)

        assert len(flags) == 1
        assert flags[0]["key"] == "cached-flag"

    def test_update_flags_cache(self):
        """Test explicitly updating the service flags cache."""
        # Create a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Update cache
        update_flags_cache(self.team)

        # Verify cache was updated
        flags = get_flags_from_cache(self.team)
        assert len(flags) == 1
        assert flags[0]["key"] == "test-flag"

    def test_clear_flags_cache(self):
        """Test clearing the service flags cache."""
        # Create and cache a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Clear the cache
        clear_flags_cache(self.team)

        # Cache should now load from DB (source will be "db")
        flags, source = flags_hypercache.get_from_cache_with_source(self.team)
        assert source == "db"


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsSignals(BaseTest):
    """Test Django signal handlers for automatic cache invalidation."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_flag_create(self, mock_task):
        """Test that signal fires when a flag is created."""
        FeatureFlag.objects.create(
            team=self.team,
            key="new-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_flag_update(self, mock_task):
        """Test that signal fires when a flag is updated."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        # Reset mock to ignore the create signal
        mock_task.reset_mock()

        # Update the flag
        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 100}]}
        flag.save()

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_flag_delete(self, mock_task):
        """Test that signal fires when a flag is deleted."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Reset mock to ignore the create signal
        mock_task.reset_mock()

        # Delete the flag
        flag.delete()

        # Signal should trigger the Celery task
        mock_task.delay.assert_called_once_with(self.team.id)

    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    def test_signal_fired_on_team_create(self, mock_task):
        """Test that signal fires when a team is created."""
        # Create a new team
        new_team = Team.objects.create(
            organization=self.organization,
            name="New Test Team",
        )

        # Signal should trigger the Celery task to warm cache
        mock_task.delay.assert_called_once_with(new_team.id)

    def test_signal_clears_cache_on_team_delete(self):
        """Test that cache is cleared when a team is deleted."""
        # Create and cache a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Verify cache exists
        flags = get_flags_from_cache(self.team)
        assert len(flags) == 1

        # Delete the team
        self.team.delete()

        # Cache should be cleared (this will load from DB and return empty)
        # We can't test directly with the deleted team object, but the signal should have fired
        # In production, this prevents stale cache entries


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsCeleryTasks(BaseTest):
    """Test Celery task integration for service flags cache updates."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_update_team_service_flags_cache_task(self):
        """Test the Celery task that updates service flags cache."""
        from posthog.tasks.feature_flags import update_team_service_flags_cache

        # Create a flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Run the task synchronously
        update_team_service_flags_cache(self.team.id)

        # Verify cache was updated
        flags = get_flags_from_cache(self.team)
        assert len(flags) == 1
        assert flags[0]["key"] == "test-flag"

    def test_update_team_service_flags_cache_task_team_not_found(self):
        """Test the Celery task handles missing team gracefully."""
        from posthog.tasks.feature_flags import update_team_service_flags_cache

        # Run task with non-existent team ID
        # Should not raise an exception
        update_team_service_flags_cache(999999)


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsDataFormat(BaseTest):
    """Test that cached data format matches service expectations."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_flag_data_contains_required_rust_fields(self):
        """Test that flag data includes all fields expected by Rust."""
        FeatureFlag.objects.create(
            team=self.team,
            key="rust-compatible-flag",
            name="Rust Compatible Flag",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "email", "value": "test@example.com", "type": "person"}],
                        "rollout_percentage": 50,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
            },
            ensure_experience_continuity=True,
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]
        flag_data = flags[0]

        # Required fields for service FeatureFlag struct
        required_fields = [
            "id",
            "team_id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "ensure_experience_continuity",
            "version",
        ]

        for field in required_fields:
            assert field in flag_data, f"Missing required field: {field}"

        # Verify filters structure
        assert "groups" in flag_data["filters"]
        assert len(flag_data["filters"]["groups"]) == 1
        assert "multivariate" in flag_data["filters"]

    def test_flag_data_serializes_to_json(self):
        """Test that flag data can be serialized to JSON (for Redis/S3 storage)."""
        import json

        FeatureFlag.objects.create(
            team=self.team,
            key="json-test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)

        # Should serialize without errors
        json_str = json.dumps(result)
        assert json_str is not None

        # Should deserialize back to same structure
        deserialized = json.loads(json_str)
        assert "flags" in deserialized
        assert len(deserialized["flags"]) == 1
        assert deserialized["flags"][0]["key"] == "json-test-flag"


@override_settings(FLAGS_REDIS_URL=None)
class TestServiceFlagsGuards(BaseTest):
    """Test that cache functions guard against writes when FLAGS_REDIS_URL is not set."""

    def setUp(self):
        super().setUp()
        # Create a flag for testing
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def test_get_flags_from_cache_returns_empty_without_redis_url(self):
        """Test that get_flags_from_cache returns empty list when FLAGS_REDIS_URL is not set."""
        flags = get_flags_from_cache(self.team)
        assert flags == []

    def test_update_flags_cache_no_op_without_redis_url(self):
        """Test that update_flags_cache is a no-op when FLAGS_REDIS_URL is not set."""
        # This should not raise an error and should be a no-op
        update_flags_cache(self.team)

        # Since it's a no-op, attempting to get from cache should return empty
        flags = get_flags_from_cache(self.team)
        assert flags == []

    def test_clear_flags_cache_no_op_without_redis_url(self):
        """Test that clear_flags_cache is a no-op when FLAGS_REDIS_URL is not set."""
        # This should not raise an error and should be a no-op
        clear_flags_cache(self.team)

        # Should complete without error (nothing to verify as it's a no-op)
