"""
Tests for the flags HyperCache for feature-flags service.

Tests cover:
- Basic cache operations (get, update, clear)
- Signal handlers for automatic cache invalidation
- Celery task integration
- Data format compatibility with service
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.management.base import OutputWrapper
from django.test import override_settings

from parameterized import parameterized

from posthog.models import FeatureFlag, Team
from posthog.models.cohort.cohort import Cohort
from posthog.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from posthog.models.feature_flag.flags_cache import (
    _compute_flag_dependencies,
    _extract_cohort_ids_from_flag_filters,
    _extract_direct_dependency_ids,
    _get_feature_flags_for_service,
    _get_feature_flags_for_teams_batch,
    _get_referenced_cohorts,
    _get_team_ids_with_recently_updated_flags,
    _serialize_cohort,
    clear_flags_cache,
    flags_hypercache,
    get_flags_from_cache,
    get_teams_with_flags_queryset,
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

        assert result == {
            "flags": [],
            "evaluation_metadata": {
                "dependency_stages": [],
                "flags_with_missing_deps": [],
                "transitive_deps": {},
            },
            "cohorts": [],
        }

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

    def test_get_feature_flags_for_service_includes_inactive(self):
        """Test that inactive flags are included in cache.

        Inactive flags must be included so that flag dependencies can reference them
        and evaluate them as false, rather than raising DependencyNotFound errors.
        """
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

        # Both active and inactive flags should be included
        assert len(flags) == 2
        flag_keys = {f["key"] for f in flags}
        assert flag_keys == {"active-flag", "inactive-flag"}

        # Verify the inactive flag has active=False
        inactive_flag = next(f for f in flags if f["key"] == "inactive-flag")
        assert inactive_flag["active"] is False

    def test_get_feature_flags_for_teams_batch_includes_inactive(self):
        """Test that batch function includes inactive flags for dependency resolution.

        This tests the same behavior as test_get_feature_flags_for_service_includes_inactive
        but for the batch function used in management commands and cache warming.
        """
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

        result = _get_feature_flags_for_teams_batch([self.team])
        flags = result[self.team.id]["flags"]

        # Both active and inactive flags should be included
        assert len(flags) == 2
        flag_keys = {f["key"] for f in flags}
        assert flag_keys == {"active-flag", "inactive-flag"}

        # Verify the inactive flag has active=False
        inactive_flag = next(f for f in flags if f["key"] == "inactive-flag")
        assert inactive_flag["active"] is False

    def test_get_feature_flags_for_service_excludes_encrypted_remote_config(self):
        """Test that encrypted remote config flags are excluded from cache.

        Encrypted remote config flags can only be accessed via the dedicated
        /remote_config endpoint which handles decryption. Including them in
        /flags would return unusable encrypted ciphertext.

        Unencrypted remote config flags should still be included since they
        work with useFeatureFlagPayload.
        """
        # Create regular feature flag
        FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create unencrypted remote config flag (should be included)
        FeatureFlag.objects.create(
            team=self.team,
            key="unencrypted-remote-config",
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create encrypted remote config flag (should be excluded)
        FeatureFlag.objects.create(
            team=self.team,
            key="encrypted-remote-config",
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)
        flags = result["flags"]

        # Regular and unencrypted remote config should be included
        # Encrypted remote config should be excluded
        assert len(flags) == 2
        flag_keys = {f["key"] for f in flags}
        assert flag_keys == {"regular-flag", "unencrypted-remote-config"}

    def test_get_feature_flags_for_teams_batch_excludes_encrypted_remote_config(self):
        """Test that batch function excludes encrypted remote config flags.

        This tests the same behavior as test_get_feature_flags_for_service_excludes_encrypted_remote_config
        but for the batch function used in management commands and cache warming.
        """
        # Create regular feature flag
        FeatureFlag.objects.create(
            team=self.team,
            key="regular-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create unencrypted remote config flag (should be included)
        FeatureFlag.objects.create(
            team=self.team,
            key="unencrypted-remote-config",
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create encrypted remote config flag (should be excluded)
        FeatureFlag.objects.create(
            team=self.team,
            key="encrypted-remote-config",
            created_by=self.user,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_teams_batch([self.team])
        flags = result[self.team.id]["flags"]

        # Regular and unencrypted remote config should be included
        # Encrypted remote config should be excluded
        assert len(flags) == 2
        flag_keys = {f["key"] for f in flags}
        assert flag_keys == {"regular-flag", "unencrypted-remote-config"}
        assert "encrypted-remote-config" not in flag_keys

    @parameterized.expand(
        [
            # (is_remote_config, has_encrypted, should_include, description)
            (False, False, True, "regular_flag"),
            (False, True, True, "encrypted_but_not_remote_config"),
            (True, False, True, "unencrypted_remote_config"),
            (True, True, False, "encrypted_remote_config"),
            (None, False, True, "null_remote_config_unencrypted"),
            (None, True, True, "null_remote_config_encrypted"),
            (False, None, True, "regular_flag_null_encrypted"),
            (True, None, True, "remote_config_null_encrypted"),
            (None, None, True, "legacy_flag_both_null"),
        ]
    )
    def test_filtering_matrix_for_service(self, is_remote_config, has_encrypted, should_include, desc):
        """Test filtering behavior for all combinations of is_remote_configuration and has_encrypted_payloads.

        This parameterized test covers all 9 combinations including NULL values to ensure
        legacy flags (created before these fields existed) are handled correctly.
        """
        FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{desc}",
            created_by=self.user,
            is_remote_configuration=is_remote_config,
            has_encrypted_payloads=has_encrypted,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_service(self.team)
        flag_keys = {f["key"] for f in result["flags"]}

        if should_include:
            assert f"flag-{desc}" in flag_keys, f"Expected flag-{desc} to be included"
        else:
            assert f"flag-{desc}" not in flag_keys, f"Expected flag-{desc} to be excluded"

    @parameterized.expand(
        [
            # (is_remote_config, has_encrypted, should_include, description)
            (False, False, True, "regular_flag"),
            (False, True, True, "encrypted_but_not_remote_config"),
            (True, False, True, "unencrypted_remote_config"),
            (True, True, False, "encrypted_remote_config"),
            (None, False, True, "null_remote_config_unencrypted"),
            (None, True, True, "null_remote_config_encrypted"),
            (False, None, True, "regular_flag_null_encrypted"),
            (True, None, True, "remote_config_null_encrypted"),
            (None, None, True, "legacy_flag_both_null"),
        ]
    )
    def test_filtering_matrix_for_teams_batch(self, is_remote_config, has_encrypted, should_include, desc):
        """Test batch function filtering for all combinations of is_remote_configuration and has_encrypted_payloads.

        This parameterized test covers all 9 combinations including NULL values to ensure
        legacy flags (created before these fields existed) are handled correctly in batch loading.
        """
        FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{desc}",
            created_by=self.user,
            is_remote_configuration=is_remote_config,
            has_encrypted_payloads=has_encrypted,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_feature_flags_for_teams_batch([self.team])
        flag_keys = {f["key"] for f in result[self.team.id]["flags"]}

        if should_include:
            assert f"flag-{desc}" in flag_keys, f"Expected flag-{desc} to be included"
        else:
            assert f"flag-{desc}" not in flag_keys, f"Expected flag-{desc} to be excluded"

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
        assert flags is not None
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
        assert flags is not None
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

    def test_update_flags_cache_writes_etag(self):
        """The Rust in-memory FlagDefinitionsCache keys on the etag Django writes
        alongside the payload. Without it, the etag_missing branch fires on every
        request and the perf opt is wasted. Pin enable_etag=True for this hypercache.
        """
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        update_flags_cache(self.team)

        etag = flags_hypercache.get_etag(self.team)
        assert etag is not None
        # _compute_etag returns the first 16 hex chars of sha256
        assert len(etag) == 16
        assert all(c in "0123456789abcdef" for c in etag)

    def test_clear_flags_cache_clears_etag(self):
        """clear_cache must remove both the payload and the etag — otherwise
        a stale etag would point at evicted data on the next read."""
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)
        assert flags_hypercache.get_etag(self.team) is not None

        clear_flags_cache(self.team)

        assert flags_hypercache.get_etag(self.team) is None

    def test_missing_sentinel_clears_etag(self):
        """The __missing__ sentinel write (empty team) must clear any prior etag —
        the Rust loader expects sentinel to land on the `sentinel` reason, not
        `etag_missing`, which only fires when data is present without an etag."""
        # Prime an etag by writing real data first
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)
        assert flags_hypercache.get_etag(self.team) is not None

        # Write the sentinel (data=None) and confirm etag is cleared
        flags_hypercache.set_cache_value(self.team, None)

        assert flags_hypercache.get_etag(self.team) is None

    def test_get_feature_flags_for_service_includes_referenced_cohorts(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="cohort-flag",
            created_by=self.user,
            filters={
                "groups": [{"properties": [{"type": "cohort", "value": cohort.id}], "rollout_percentage": 100}],
            },
        )
        result = _get_feature_flags_for_service(self.team)
        assert len(result["cohorts"]) == 1
        assert result["cohorts"][0]["id"] == cohort.id
        assert result["cohorts"][0]["name"] == "Test Cohort"

    def test_get_feature_flags_for_teams_batch_isolates_cohorts_per_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        cohort_a = Cohort.objects.create(
            team=self.team,
            name="Cohort A",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
        )
        cohort_b = Cohort.objects.create(
            team=other_team,
            name="Cohort B",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "b@b.com", "type": "person"}]}],
                }
            },
        )
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            created_by=self.user,
            filters={"groups": [{"properties": [{"type": "cohort", "value": cohort_a.id}], "rollout_percentage": 100}]},
        )
        FeatureFlag.objects.create(
            team=other_team,
            key="flag-b",
            created_by=self.user,
            filters={"groups": [{"properties": [{"type": "cohort", "value": cohort_b.id}], "rollout_percentage": 100}]},
        )
        result = _get_feature_flags_for_teams_batch([self.team, other_team])
        assert len(result[self.team.id]["cohorts"]) == 1
        assert result[self.team.id]["cohorts"][0]["id"] == cohort_a.id
        assert len(result[other_team.id]["cohorts"]) == 1
        assert result[other_team.id]["cohorts"][0]["id"] == cohort_b.id


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
        assert flags is not None
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
        assert flags is not None
        assert len(flags) == 1
        assert flags[0]["key"] == "test-flag"

    def test_update_team_service_flags_cache_task_team_not_found(self):
        """Test the Celery task handles missing team gracefully."""
        from posthog.tasks.feature_flags import update_team_service_flags_cache

        # Run task with non-existent team ID
        # Should not raise an exception
        update_team_service_flags_cache(999999)


# Path from this test file up to the repo root (4 levels: test/ -> feature_flag/ -> models/ -> posthog/ -> repo)
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _extract_schema(obj: Any) -> Any:
    """Extract a type skeleton from a JSON-like object for structural comparison.

    Returns a nested structure of dicts, lists, and leaf type names.
    Dicts with all-numeric keys (e.g. transitive_deps keyed by flag ID) are
    treated as maps — represented as {"<map>": value_schema} so the comparison
    checks value structure, not specific keys.
    """
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        return "str"
    if isinstance(obj, list):
        if not obj:
            return ["empty_list"]
        # Assumes homogeneous lists (all elements same type), which holds for
        # the hypercache JSON schema. Only the first element is inspected.
        return [_extract_schema(obj[0])]
    if isinstance(obj, dict):
        if not obj:
            return {}
        # Dicts with all-numeric keys are ID-keyed maps, not fixed schemas.
        # Derive the map value schema from the first informative (non-empty-list) value
        # so that a breaking type change in non-empty entries isn't masked by leading
        # empty lists (e.g. transitive_deps: {"1": [], "4": [2]}).
        if all(k.isdigit() for k in obj.keys()):
            map_schema = None
            fallback_schema = None
            for val in obj.values():
                candidate = _extract_schema(val)
                if fallback_schema is None:
                    fallback_schema = candidate
                if isinstance(candidate, list) and candidate and candidate[0] == "empty_list":
                    continue
                map_schema = candidate
                break
            return {"<map>": map_schema if map_schema is not None else fallback_schema}
        return {k: _extract_schema(v) for k, v in sorted(obj.items())}
    return type(obj).__name__


def _compare_schemas(fixture_schema: Any, result_schema: Any, path: str = "") -> list[str]:
    """Compare two type skeletons and return human-readable diffs."""
    diffs: list[str] = []
    # If the fixture declares a field as null, the serializer must also return null.
    # This prevents null in the fixture from acting as a wildcard that accepts any
    # non-null type, which would allow breaking type changes on nullable fields to
    # slip through undetected (e.g. changing an Option<i32> field to emit a string).
    if fixture_schema == "null":
        if result_schema != "null":
            diffs.append(f"Fixture expects null at `{path}` but serializer returned {result_schema}")
        return diffs
    if result_schema == "null":
        diffs.append(f"Fixture expects non-null at `{path}` ({fixture_schema}) but serializer returned null")
        return diffs
    if type(fixture_schema) is not type(result_schema):
        diffs.append(f"Type mismatch at `{path}`: fixture={fixture_schema}, serializer={result_schema}")
        return diffs
    if isinstance(fixture_schema, dict):
        all_keys = set(fixture_schema.keys()) | set(result_schema.keys())
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in result_schema:
                diffs.append(f"Key `{child_path}` in fixture but not in serializer output")
            elif key not in fixture_schema:
                diffs.append(f"Key `{child_path}` in serializer output but not in fixture")
            else:
                diffs.extend(_compare_schemas(fixture_schema[key], result_schema[key], child_path))
    elif isinstance(fixture_schema, list) and fixture_schema:
        # If the serializer returned an empty list we can't check element type
        if result_schema[0] == "empty_list":
            return diffs
        diffs.extend(_compare_schemas(fixture_schema[0], result_schema[0], f"{path}[]"))
    elif fixture_schema != result_schema:
        diffs.append(f"Type mismatch at `{path}`: fixture={fixture_schema}, serializer={result_schema}")
    return diffs


class TestExtractSchema:
    @parameterized.expand(
        [
            ("none", None, "null"),
            ("bool_true", True, "bool"),
            ("bool_false", False, "bool"),
            ("int", 42, "int"),
            ("float", 3.14, "float"),
            ("str", "hi", "str"),
            ("empty_list", [], ["empty_list"]),
            ("list_of_int", [1, 2], ["int"]),
            ("empty_dict", {}, {}),
            ("simple_dict", {"a": 1}, {"a": "int"}),
            ("map_skips_empty", {"1": [], "2": [3]}, {"<map>": ["int"]}),
            ("map_all_empty", {"1": [], "2": []}, {"<map>": ["empty_list"]}),
        ]
    )
    def test_extract_schema(self, _name: str, obj: Any, expected: Any):
        assert _extract_schema(obj) == expected

    @parameterized.expand(
        [
            ("null_match", "null", "null", []),
            ("null_vs_str", "null", "str", ["Fixture expects null at `root` but serializer returned str"]),
            ("str_vs_null", "str", "null", ["Fixture expects non-null at `root` (str) but serializer returned null"]),
            ("int_vs_float", "int", "float", ["Type mismatch at `root`: fixture=int, serializer=float"]),
            ("empty_list_compat_rhs", ["int"], ["empty_list"], []),
            (
                "empty_list_compat_lhs",
                ["empty_list"],
                ["str"],
                ["Type mismatch at `root[]`: fixture=empty_list, serializer=str"],
            ),
            (
                "extra_key",
                {"a": "int"},
                {"a": "int", "b": "str"},
                ["Key `root.b` in serializer output but not in fixture"],
            ),
            ("matching_dict", {"a": "int"}, {"a": "int"}, []),
        ]
    )
    def test_compare_schemas(self, _name: str, fixture_schema: Any, result_schema: Any, expected_diffs: list[str]):
        diffs = _compare_schemas(fixture_schema, result_schema, "root")
        assert diffs == expected_diffs


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestServiceFlagsDataFormat(BaseTest):
    """Test that cached data format matches service expectations."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_serializer_output_matches_fixture_schema(self):
        """Golden fixture validation: Python serializer output must match the fixture schema.

        Recursively compares the type skeleton (keys + value types at every nesting
        level) of the fixture against actual serializer output. If this test fails,
        update the golden fixture and verify Rust tests pass.
        """
        fixture_path = _REPO_ROOT / "rust" / "feature-flags" / "tests" / "fixtures" / "hypercache_contract.json"
        fixture = json.loads(fixture_path.read_text())

        # --- Create test data mirroring the 4 fixture flag variants ---

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            created_by=self.user,
            version=1,
            count=42,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "email", "value": "test@example.com", "type": "person", "operator": "exact"}
                            ],
                        }
                    ],
                }
            },
            last_backfill_person_properties_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
        )

        # 1) full-flag: exercises all optional nested structures.
        # Every nullable field that has a typed schema should be non-null here
        # so _compare_schemas can verify its type.
        full_flag = FeatureFlag.objects.create(
            team=self.team,
            key="full-flag",
            name="Full feature flag",
            created_by=self.user,
            ensure_experience_continuity=True,
            version=3,
            evaluation_runtime="all",
            bucketing_identifier="device_id",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "value": "test@example.com", "type": "person", "operator": "exact"}
                        ],
                        "rollout_percentage": 50,
                        "variant": None,
                    }
                ],
                "multivariate": {
                    "variants": [
                        {"key": "control", "name": "Control", "rollout_percentage": 50},
                        {"key": "test", "name": "Test", "rollout_percentage": 50},
                    ]
                },
                "payloads": {"control": "payload-value"},
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "$feature_enrollment/full-flag",
                                "type": "person",
                                "value": ["true"],
                                "operator": "exact",
                            }
                        ],
                        "rollout_percentage": None,
                        "variant": None,
                    }
                ],
                "feature_enrollment": True,
                "holdout": {"id": 42, "exclusion_percentage": 10.0},
                "aggregation_group_type_index": None,
            },
        )

        # Attach evaluation contexts to full-flag
        for ctx_name in ["docs-page", "marketing-site"]:
            ctx, _ = EvaluationContext.objects.get_or_create(team=self.team, name=ctx_name)
            FeatureFlagEvaluationContext.objects.create(feature_flag=full_flag, evaluation_context=ctx)

        # 2) minimal-flag: only required fields, empty/null optionals
        minimal_flag = FeatureFlag.objects.create(
            team=self.team,
            key="minimal-flag",
            name="",
            created_by=self.user,
            version=1,
            evaluation_runtime="all",
            bucketing_identifier=None,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100, "variant": None}],
                "multivariate": None,
                "payloads": {},
            },
        )

        # 3) cohort-flag: cohort-type property
        FeatureFlag.objects.create(
            team=self.team,
            key="cohort-flag",
            name="Cohort flag",
            created_by=self.user,
            version=1,
            evaluation_runtime="all",
            bucketing_identifier=None,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "id", "value": cohort.id, "type": "cohort", "operator": "in"}],
                        "rollout_percentage": 100,
                        "variant": None,
                    }
                ],
                "multivariate": None,
                "payloads": {},
            },
        )

        # 4) dependent-flag: flag-type property with label
        FeatureFlag.objects.create(
            team=self.team,
            key="dependent-flag",
            name="Flag with dependency",
            created_by=self.user,
            version=2,
            evaluation_runtime="all",
            bucketing_identifier=None,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": str(minimal_flag.id),
                                "label": "minimal-flag",
                                "operator": "flag_evaluates_to",
                                "type": "flag",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": None,
                    }
                ],
                "multivariate": None,
                "payloads": {},
            },
        )

        # 5) missing-dep-flag: depends on a flag that doesn't exist,
        # exercises flags_with_missing_deps element type (int)
        FeatureFlag.objects.create(
            team=self.team,
            key="missing-dep-flag",
            name="Flag with missing dependency",
            created_by=self.user,
            version=1,
            evaluation_runtime="all",
            bucketing_identifier=None,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "99999",
                                "label": "nonexistent-flag",
                                "operator": "flag_evaluates_to",
                                "type": "flag",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                        "variant": None,
                    }
                ],
                "multivariate": None,
                "payloads": {},
            },
        )

        result = _get_feature_flags_for_service(self.team)

        # --- Deep recursive schema comparison ---

        all_diffs: list[str] = []

        # Top-level keys
        fixture_top = set(fixture.keys())
        result_top = set(result.keys())
        if fixture_top != result_top:
            if fixture_top - result_top:
                all_diffs.append(f"Top-level keys in fixture but not in serializer: {sorted(fixture_top - result_top)}")
            if result_top - fixture_top:
                all_diffs.append(f"Top-level keys in serializer but not in fixture: {sorted(result_top - fixture_top)}")

        # Per-flag comparison by key — guard against KeyError when "flags" is missing
        # (missing-key diffs are already recorded above; we continue to collect other diffs)
        if "flags" in fixture and "flags" in result:
            fixture_flags_by_key = {f["key"]: f for f in fixture["flags"]}
            result_flags_by_key = {f["key"]: f for f in result["flags"]}

            fixture_keys = set(fixture_flags_by_key.keys())
            result_keys = set(result_flags_by_key.keys())
            missing = fixture_keys - result_keys
            extra = result_keys - fixture_keys
            if missing:
                all_diffs.append(f"Fixture flag keys not in serializer output: {sorted(missing)}")
            if extra:
                all_diffs.append(f"Serializer flag keys not in fixture: {sorted(extra)}")
            for key in sorted(fixture_keys & result_keys):
                all_diffs.extend(
                    _compare_schemas(
                        _extract_schema(fixture_flags_by_key[key]),
                        _extract_schema(result_flags_by_key[key]),
                        f"flags[key={key}]",
                    )
                )

        # evaluation_metadata
        if "evaluation_metadata" in fixture and "evaluation_metadata" in result:
            all_diffs.extend(
                _compare_schemas(
                    _extract_schema(fixture["evaluation_metadata"]),
                    _extract_schema(result["evaluation_metadata"]),
                    "evaluation_metadata",
                )
            )

        # cohorts
        assert result.get("cohorts"), "Expected cohorts in serializer output (flags reference a cohort)"
        if "cohorts" in fixture and "cohorts" in result:
            assert len(result["cohorts"]) == len(fixture["cohorts"]), (
                f"Cohort count mismatch: fixture has {len(fixture['cohorts'])}, serializer has {len(result['cohorts'])}"
            )
            for i, (f_cohort, r_cohort) in enumerate(zip(fixture["cohorts"], result["cohorts"])):
                all_diffs.extend(
                    _compare_schemas(
                        _extract_schema(f_cohort),
                        _extract_schema(r_cohort),
                        f"cohorts[{i}]",
                    )
                )

        assert not all_diffs, (
            "\n"
            + "=" * 78
            + "\n"
            + " WARNING: HYPERCACHE BOUNDARY CONTRACT VIOLATION\n"
            + "=" * 78
            + "\n\n"
            + f"  {len(all_diffs)} schema difference(s) between the Python serializer and\n"
            + "  the golden fixture used by the Rust feature-flags service:\n\n"
            + "\n".join(f"    - {d}" for d in all_diffs)
            + "\n\n"
            + "-" * 78
            + "\n"
            + "  DO NOT just update the fixture to make this test green.\n"
            + "  The Rust service deserializes this data — a schema change can\n"
            + "  break flag evaluation in production.\n\n"
            + "  Before proceeding, consider:\n"
            + "    1. Is the change backwards-compatible? (adding a new nullable\n"
            + "       field is usually safe; renaming/removing a field is not)\n"
            + "    2. Do you need a phased rollout? (deploy Rust changes first\n"
            + "       so the new schema is understood before Python writes it)\n"
            + "    3. Will the cache need re-warming? (old cached payloads will\n"
            + "       still have the previous shape until they expire or are\n"
            + "       invalidated)\n\n"
            + "  Once you have a plan:\n"
            + "    - Update the fixture: rust/feature-flags/tests/fixtures/hypercache_contract.json\n"
            + "    - Verify Rust tests: cargo test -p feature-flags test_hypercache_contract\n"
            + "=" * 78
        )

    def test_flag_data_serializes_to_json(self):
        """Test that flag data can be serialized to JSON (for Redis/S3 storage)."""
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


class TestCacheStats(BaseTest):
    """Test cache statistics functionality."""

    @patch("posthog.storage.hypercache_manager.get_client")
    def test_get_cache_stats_basic(self, mock_get_client):
        """Test basic cache stats gathering with Redis pipelining."""
        from posthog.models.feature_flag.flags_cache import get_cache_stats

        # Mock Redis client with pipelining support
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # scan_iter is called twice: once for TTL collection, once for memory sampling
        # Each call needs to return a fresh iterator
        mock_redis.scan_iter.side_effect = [
            iter(
                [
                    b"cache/teams/1/feature_flags/flags.json",
                    b"cache/teams/2/feature_flags/flags.json",
                ]
            ),  # TTL scan
            iter(
                [
                    b"cache/teams/1/feature_flags/flags.json",
                    b"cache/teams/2/feature_flags/flags.json",
                ]
            ),  # Memory scan
        ]

        # Mock pipeline for batched operations
        mock_pipeline = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_pipeline.execute.side_effect = [
            [3600, 86400],  # TTL results: 1 hour, 1 day
            [1024, 2048],  # Memory usage results
        ]

        # Mock zcard for expiry tracking count
        mock_redis.zcard.return_value = 2

        with patch("posthog.models.team.team.Team.objects.count", return_value=5):
            stats = get_cache_stats()

        self.assertEqual(stats["total_cached"], 2)
        self.assertEqual(stats["total_teams"], 5)
        self.assertEqual(stats["expiry_tracked"], 2)
        self.assertEqual(stats["ttl_distribution"]["expires_1h"], 1)
        self.assertEqual(stats["ttl_distribution"]["expires_24h"], 1)
        self.assertEqual(stats["size_statistics"]["sample_count"], 2)
        self.assertEqual(stats["size_statistics"]["avg_size_bytes"], 1536)  # (1024 + 2048) / 2


class TestGetTeamsWithExpiringCaches(BaseTest):
    """Test get_teams_with_expiring_flags_caches functionality."""

    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_returns_teams_with_expiring_ttl(self, mock_time, mock_get_client):
        """Teams with expiration timestamp < threshold should be returned."""
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_CACHE_EXPIRY_SORTED_SET,
            get_teams_with_expiring_flags_caches,
        )

        team1 = self.team
        team2 = Team.objects.create(
            organization=self.organization,
            name="Team 2",
        )

        # Mock current time and Redis sorted set query
        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Return teams expiring within next 24 hours
        mock_redis.zrangebyscore.return_value = [
            str(team1.id).encode(),
            str(team2.id).encode(),
        ]

        result = get_teams_with_expiring_flags_caches(ttl_threshold_hours=24)

        # Both teams have expiring caches
        self.assertEqual(len(result), 2)
        self.assertIn(team1, result)
        self.assertIn(team2, result)

        # Verify sorted set query was called correctly
        mock_redis.zrangebyscore.assert_called_once_with(
            FLAGS_CACHE_EXPIRY_SORTED_SET,
            "-inf",
            1000000 + (24 * 3600),  # current_time + 24 hours
            start=0,
            num=5000,
        )

    @patch("posthog.storage.cache_expiry_manager.get_client")
    @patch("posthog.storage.cache_expiry_manager.time")
    def test_skips_teams_with_fresh_ttl(self, mock_time, mock_get_client):
        """Teams with expiration timestamp > threshold should not be returned."""
        from posthog.models.feature_flag.flags_cache import get_teams_with_expiring_flags_caches

        # Mock Redis sorted set returning empty (no teams expiring soon)
        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []  # No teams expiring within threshold

        result = get_teams_with_expiring_flags_caches(ttl_threshold_hours=24)

        # No teams returned
        self.assertEqual(len(result), 0)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_returns_empty_when_no_expiring_caches(self, mock_get_client):
        """Should return empty list when sorted set is empty."""
        from posthog.models.feature_flag.flags_cache import get_teams_with_expiring_flags_caches

        # Mock Redis to return empty sorted set
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []

        result = get_teams_with_expiring_flags_caches(ttl_threshold_hours=24)

        self.assertEqual(len(result), 0)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_uses_correct_redis_url(self, mock_get_client):
        """Test that get_client is called with FLAGS_REDIS_URL, not default REDIS_URL.

        This is a regression test for a bug where cache_expiry_manager was using
        the default Redis database (0) instead of the dedicated flags cache database (1).
        """
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            get_teams_with_expiring_caches,
        )

        # Mock Redis to return empty sorted set
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.zrangebyscore.return_value = []

        get_teams_with_expiring_caches(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours=24)

        # Verify get_client was called with the hypercache's redis_url
        mock_get_client.assert_called_once_with(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.redis_url)


@override_settings(FLAGS_REDIS_URL="redis://test:6379/0")
class TestBatchOperations(BaseTest):
    """Test batch operations for flags cache."""

    @patch("posthog.models.feature_flag.flags_cache.refresh_expiring_caches")
    def test_refresh_expiring_caches(self, mock_refresh):
        """Test refreshing expiring caches calls generic function."""
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            refresh_expiring_flags_caches,
        )

        mock_refresh.return_value = (2, 0)  # successful, failed

        successful, failed = refresh_expiring_flags_caches(ttl_threshold_hours=24)

        # Should return result from generic function
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)

        # Should call generic refresh_expiring_caches with correct config
        mock_refresh.assert_called_once_with(FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, 24, settings.FLAGS_CACHE_REFRESH_LIMIT)

    @patch("posthog.storage.cache_expiry_manager.get_client")
    def test_cleanup_stale_expiry_tracking(self, mock_get_client):
        """Test cleaning up stale expiry tracking entries."""
        from posthog.models.feature_flag.flags_cache import FLAGS_CACHE_EXPIRY_SORTED_SET, cleanup_stale_expiry_tracking

        team1 = self.team
        # Create a team that will be deleted
        team2 = Team.objects.create(
            organization=self.organization,
            name="Team 2",
        )
        team2_id = team2.id
        team2.delete()

        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Mock sorted set with both valid and stale team IDs
        mock_redis.zrange.return_value = [
            str(team1.id).encode(),
            str(team2_id).encode(),  # Stale - team deleted
        ]
        mock_redis.zrem.return_value = 1  # Redis returns number of elements removed

        removed = cleanup_stale_expiry_tracking()

        # Should remove 1 stale entry
        self.assertEqual(removed, 1)

        # Should call zrem with the stale team ID
        mock_redis.zrem.assert_called_once_with(FLAGS_CACHE_EXPIRY_SORTED_SET, str(team2_id))

    @patch("posthog.storage.hypercache.get_client")
    @patch("posthog.storage.hypercache.time")
    def test_warm_without_stagger_tracks_expiry_with_default_ttl(self, mock_time, mock_get_client):
        """Test that expiry tracking happens even when stagger_ttl=False (uses batch path)."""
        from posthog.models.feature_flag.flags_cache import (
            FLAGS_CACHE_EXPIRY_SORTED_SET,
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
        )
        from posthog.storage.hypercache_manager import warm_caches

        # Create a flag so batch loading succeeds
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        mock_time.time.return_value = 1000000
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis

        # Call warm WITHOUT staggering (ttl_seconds will be None in batch path)
        warm_caches(
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            stagger_ttl=False,  # This should still track expiry!
            batch_size=1,
            team_ids=[self.team.id],  # Ensure we warm only self.team
        )

        # Should have tracked expiry with default TTL
        mock_redis.zadd.assert_called()
        call_args = mock_redis.zadd.call_args

        # Verify it was added to the correct sorted set
        self.assertEqual(call_args[0][0], FLAGS_CACHE_EXPIRY_SORTED_SET)

        # Verify the TTL is the default (since stagger_ttl=False)
        team_id_str = str(self.team.id)
        expiry_timestamp = call_args[0][1][team_id_str]
        expected_expiry = 1000000 + settings.FLAGS_CACHE_TTL
        self.assertEqual(expiry_timestamp, expected_expiry)


@override_settings(
    FLAGS_REDIS_URL="redis://test:6379/0",
    CACHES={
        **settings.CACHES,
        "flags_dedicated": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "flags-test",
        },
    },
)
class TestManagementCommands(BaseTest):
    """Test management commands for flags cache."""

    @patch("posthog.management.commands.analyze_flags_cache_sizes._get_feature_flags_for_teams_batch")
    def test_analyze_command(self, mock_batch_get_flags):
        """Test analyze_flags_cache_sizes command."""
        from django.core.management import call_command

        # Mock flags data
        mock_batch_get_flags.return_value = {
            self.team.id: {
                "flags": [
                    {
                        "id": 1,
                        "team_id": self.team.id,
                        "key": "test-flag",
                        "name": "Test Flag",
                        "active": True,
                        "deleted": False,
                        "filters": {},
                    }
                ]
            }
        }

        # Call command - should complete without error
        call_command("analyze_flags_cache_sizes", "--sample-size=1")

        # Should have called the batch function
        mock_batch_get_flags.assert_called()

    def test_verify_command(self):
        """Test verify_flags_cache command."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Call command with specific team
        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should show verification results
        self.assertIn("Verification Results", output)
        self.assertIn("Total teams verified: 1", output)

    def test_warm_command_specific_teams(self):
        """Test warm_flags_cache command with specific teams."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Call command with specific team
        out = StringIO()
        call_command("warm_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should show warming results
        self.assertIn("Flags cache warm completed", output)
        self.assertIn("Total teams: 1", output)
        self.assertIn("Successful: 1", output)

    def test_analyze_command_validates_sample_size_too_small(self):
        """Test analyze command rejects sample_size < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)

    def test_analyze_command_validates_sample_size_too_large(self):
        """Test analyze command rejects sample_size > 10000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=10001", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot exceed 10000", output)

    def test_verify_command_validates_sample_too_small(self):
        """Test verify command rejects sample < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", "--sample=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)

    def test_verify_command_validates_sample_too_large(self):
        """Test verify command rejects sample > 10000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", "--sample=10001", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot exceed 10000", output)

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_batch_size_too_small(self, mock_warm):
        """Test warm command rejects batch_size < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_batch_size_too_large(self, mock_warm):
        """Test warm command rejects batch_size > 5000."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=5001", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot be greater than 5000", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_ttl_days_too_small(self, mock_warm):
        """Test warm command rejects min_ttl_days < 1."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=0", stdout=out)

        output = out.getvalue()
        self.assertIn("must be at least 1", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_ttl_days_too_large(self, mock_warm):
        """Test warm command rejects max_ttl_days > 30."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--max-ttl-days=31", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot be greater than 30 days", output)
        mock_warm.assert_not_called()

    @patch("posthog.storage.hypercache_manager.warm_caches")
    def test_warm_command_validates_min_greater_than_max_ttl(self, mock_warm):
        """Test warm command rejects min_ttl_days > max_ttl_days."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=10", "--max-ttl-days=5", stdout=out)

        output = out.getvalue()
        self.assertIn("cannot be greater than", output)
        mock_warm.assert_not_called()

    # Comprehensive tests for analyze_flags_cache_sizes

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_percentile_calculation(self, mock_batch_get_flags):
        """Test that percentile calculation is accurate."""
        from io import StringIO

        from django.core.management import call_command

        # Create multiple teams with varying flag counts to test percentile calculation
        teams = [self.team]
        for i in range(9):  # Total 10 teams
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            teams.append(team)

        # Mock flags with different sizes
        mock_batch_get_flags.return_value = {
            team.id: {
                "flags": [
                    {
                        "id": j,
                        "team_id": team.id,
                        "key": f"flag-{j}",
                        "name": f"Flag {j}",
                        "active": True,
                        "deleted": False,
                        "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                    }
                    for j in range((i + 1) * 10)  # 10, 20, 30... flags per team
                ]
            }
            for i, team in enumerate(teams)
        }

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=10", stdout=out)

        output = out.getvalue()
        # Should show P95 and P99 values
        self.assertIn("P95:", output)
        self.assertIn("P99:", output)
        # Should show flag counts
        self.assertIn("Flag counts per team:", output)

    def test_analyze_no_teams_in_database(self):
        """Test analyze command handles empty database gracefully."""
        from io import StringIO

        from django.core.management import call_command

        # Delete all teams
        Team.objects.all().delete()

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=100", stdout=out)

        output = out.getvalue()
        self.assertIn("No teams found", output)

    @patch("posthog.management.commands.analyze_flags_cache_sizes._get_feature_flags_for_teams_batch")
    def test_analyze_detailed_field_analysis(self, mock_batch_get_flags):
        """Test analyze command with --detailed flag shows field breakdown."""
        from io import StringIO

        from django.core.management import call_command

        # Delete all other teams so our test team is the only one selected
        Team.objects.exclude(id=self.team.id).delete()

        # Mock flags with various field sizes
        mock_batch_get_flags.return_value = {
            self.team.id: {
                "flags": [
                    {
                        "id": 1,
                        "team_id": self.team.id,
                        "key": "test-flag",
                        "name": "Test Flag",
                        "active": True,
                        "deleted": False,
                        "filters": {
                            "groups": [
                                {
                                    "properties": [{"key": "email", "value": "test@example.com", "type": "person"}],
                                    "rollout_percentage": 100,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", "--detailed", stdout=out)

        output = out.getvalue()
        # Should show field-level breakdown
        self.assertIn("FLAG FIELD SIZE ANALYSIS", output)
        self.assertIn("Largest flag fields", output)

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_compression_ratio(self, mock_batch_get_flags):
        """Test that compression ratios are calculated correctly."""
        from io import StringIO

        from django.core.management import call_command

        mock_batch_get_flags.return_value = {
            self.team.id: {
                "flags": [
                    {
                        "id": 1,
                        "team_id": self.team.id,
                        "key": "test-flag",
                        "name": "Test Flag with a long name that should compress well" * 10,
                        "active": True,
                        "deleted": False,
                        "filters": {},
                    }
                ]
            }
        }

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", stdout=out)

        output = out.getvalue()
        # Should show compression ratios
        self.assertIn("Compression ratios:", output)
        self.assertIn(":1", output)  # Ratio format like "3.5:1"

    # Comprehensive tests for warm_flags_cache

    def test_warm_all_teams_success(self):
        """Test warming all teams completes successfully."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("warm_flags_cache", "--batch-size=50", stdout=out)

        output = out.getvalue()
        self.assertIn("successful", output.lower())
        self.assertIn("Batch size: 50", output)

    def test_warm_batch_processing_with_failures(self):
        """Test warm command reports partial failures correctly."""
        from io import StringIO

        from unittest.mock import patch

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Make the cache write fail by mocking set_cache_value to raise an exception
        call_count = 0

        def failing_set_cache(team, value, **kwargs):
            nonlocal call_count
            call_count += 1
            # Fail to simulate a cache write error
            raise Exception("Cache write failed")

        # Mock the hypercache's set_cache_value to fail
        with patch(
            "posthog.models.feature_flag.flags_cache.flags_hypercache.set_cache_value", side_effect=failing_set_cache
        ):
            out = StringIO()
            call_command("warm_flags_cache", stdout=out)

            output = out.getvalue()
            # Should show failed count
            self.assertIn("Failed:", output)
            self.assertIn("1", output)  # 1 team failed

    def test_warm_staggered_ttl_range(self):
        """Test that TTL staggering parameters are passed correctly."""
        from io import StringIO

        from django.core.management import call_command

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("warm_flags_cache", "--min-ttl-days=3", "--max-ttl-days=10", stdout=out)

        output = out.getvalue()
        # Should show TTL range in output
        self.assertIn("TTL range: 3-10 days", output)

    @patch("posthog.models.feature_flag.flags_cache.update_flags_cache")
    def test_warm_missing_team_ids_warning(self, mock_update):
        """Test that warming with non-existent team IDs shows warning."""
        from io import StringIO

        from django.core.management import call_command

        mock_update.return_value = True

        out = StringIO()
        call_command("warm_flags_cache", "--team-ids", str(self.team.id), "99999", "88888", stdout=out)

        output = out.getvalue()
        self.assertIn("Warning", output)
        self.assertIn("99999", output)
        self.assertIn("88888", output)

    # Comprehensive tests for verify_flags_cache

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_verify_cache_miss_detection_and_fix(self):
        """Test that cache misses are detected and can be fixed."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import clear_flags_cache

        # Clear any cache from previous tests
        clear_flags_cache(self.team, kinds=["redis", "s3"])

        # Create a real flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        # The cache starts empty, so this is a CACHE_MISS (no cache entry exists)
        # This is correct regardless of whether the team has 0 or N flags in DB
        self.assertIn("CACHE_MISS", output)
        self.assertIn("FIXED", output)
        self.assertIn("Cache fixes applied:  1", output)

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_verify_cache_mismatch_detection_and_fix(self):
        """Test that cache mismatches are detected and fixed."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import update_flags_cache

        # Create a real flag
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache first
        update_flags_cache(self.team)

        # Modify the flag (creates a mismatch)
        flag.key = "modified-flag"
        flag.save()

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

        output = out.getvalue()
        self.assertIn("DATA_MISMATCH", output)
        self.assertIn("FIXED", output)

    def test_verify_cache_detects_evaluation_context_rename(self):
        """Test that verification detects when an evaluation context is renamed."""
        from posthog.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
        from posthog.models.feature_flag.flags_cache import update_flags_cache, verify_team_flags

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        ctx = EvaluationContext.objects.create(team=self.team, name="original-context-name")
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=ctx)

        # Warm the cache
        update_flags_cache(self.team)

        # Rename the context directly in DB (bypassing signals to simulate stale cache)
        EvaluationContext.objects.filter(id=ctx.id).update(name="renamed-context-name")

        # Verify should detect the mismatch
        result = verify_team_flags(self.team, verbose=True)

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(len(result["diffs"]), 1)
        self.assertEqual(result["diffs"][0]["type"], "FIELD_MISMATCH")
        self.assertIn("evaluation_contexts", result["diffs"][0]["diff_fields"])

        field_diffs = result["diffs"][0]["field_diffs"]
        eval_tag_diff = next(d for d in field_diffs if d["field"] == "evaluation_contexts")
        self.assertEqual(eval_tag_diff["cached_value"], ["original-context-name"])
        self.assertEqual(eval_tag_diff["db_value"], ["renamed-context-name"])

        # Mismatch result should include db_data for cache fix optimization
        self.assertIn("db_data", result)
        self.assertIsInstance(result["db_data"], dict)

    def test_verify_miss_includes_db_data(self):
        """Test that cache miss result includes db_data for direct cache write."""
        from posthog.models.feature_flag.flags_cache import clear_flags_cache, verify_team_flags

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        clear_flags_cache(self.team, kinds=["redis", "s3"])

        result = verify_team_flags(self.team)

        self.assertEqual(result["status"], "miss")
        self.assertIn("db_data", result)
        self.assertIsInstance(result["db_data"], dict)
        self.assertIn("flags", result["db_data"])

    def test_verify_detects_missing_evaluation_metadata(self):
        from posthog.models.feature_flag.flags_cache import update_flags_cache, verify_team_flags

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache normally (includes evaluation_metadata)
        update_flags_cache(self.team)

        # Simulate a pre-evaluation_metadata cache entry by removing the key
        cached_data, _source = flags_hypercache.get_from_cache_with_source(self.team)
        assert cached_data is not None
        del cached_data["evaluation_metadata"]
        flags_hypercache.set_cache_value(self.team, cached_data)

        result = verify_team_flags(self.team)

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["issue"], "MISSING_EVALUATION_METADATA")
        self.assertIn("db_data", result)
        self.assertIn("evaluation_metadata", result["db_data"])

    def test_verify_detects_missing_etag(self):
        """Without an etag, the Rust in-memory cache bypasses every request via
        the etag_missing branch. The verifier must surface this as a counted
        mismatch so the regression class cannot recur silently."""
        from posthog.models.feature_flag.flags_cache import update_flags_cache, verify_team_flags

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache normally (writes payload + etag together)
        update_flags_cache(self.team)
        assert flags_hypercache.get_etag(self.team) is not None

        # Simulate the regression class: payload present, etag absent.
        flags_hypercache.cache_client.delete(flags_hypercache.get_etag_key(self.team))
        assert flags_hypercache.get_etag(self.team) is None

        result = verify_team_flags(self.team)

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["issue"], "MISSING_ETAG")
        self.assertIn("db_data", result)

    def test_verify_missing_etag_takes_priority_over_data_drift(self):
        """Pin the verifier's priority: when a team has both a missing etag AND
        drifted cached flags, MISSING_ETAG is reported, not DATA_MISMATCH. The
        repair path writes db_data back and corrects both, so this is purely
        about which signal surfaces first."""
        from posthog.models.feature_flag.flags_cache import update_flags_cache, verify_team_flags

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )
        update_flags_cache(self.team)

        # Drift the DB out of sync with the cache by bypassing signals.
        FeatureFlag.objects.filter(id=flag.id).update(
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]}
        )
        # And remove the etag key. Now both MISSING_ETAG and DATA_MISMATCH apply.
        flags_hypercache.cache_client.delete(flags_hypercache.get_etag_key(self.team))

        result = verify_team_flags(self.team)

        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["issue"], "MISSING_ETAG")

    def test_verify_uses_batched_etag_no_extra_redis_get(self):
        """In the verifier hot path the etag must come from cache_batch_data, not
        from a per-team Redis GET. Otherwise verify_and_fix_flags_cache_task
        re-introduces an N+1 Redis round trip across ~hundreds of thousands of
        teams every 30 minutes — exactly the load this PR is trying to reduce."""
        from unittest.mock import patch

        from posthog.models.feature_flag.flags_cache import update_flags_cache, verify_team_flags

        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Pre-fetch the batch (one MGET) the way the verifier does.
        cache_batch_data = flags_hypercache.batch_get_from_cache([self.team])
        db_batch_data = {self.team.id: _get_feature_flags_for_service(self.team)}

        with patch.object(flags_hypercache, "get_etag") as m:
            result = verify_team_flags(
                self.team,
                db_batch_data=db_batch_data,
                cache_batch_data=cache_batch_data,
            )

        assert m.call_count == 0, "verifier hot path called get_etag per-team"
        # And the result is sane: etag was present in the batch, status matches.
        self.assertEqual(result["status"], "match")

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_verify_fix_failures_reported(self):
        """Test that fix failures are properly reported."""
        from io import StringIO

        from unittest.mock import patch

        from django.core.management import call_command

        # Create a real flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Make the hypercache update fail by mocking update_cache
        with patch("posthog.models.feature_flag.flags_cache.flags_hypercache.update_cache", return_value=False):
            out = StringIO()
            call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--fix", stdout=out)

            output = out.getvalue()
            self.assertIn("Failed to fix", output)
            self.assertIn("Cache fixes failed:   1", output)

    @patch("posthog.models.feature_flag.flags_cache.get_flags_from_cache")
    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_verify_with_sample(self, mock_batch_get_flags, mock_get_cache):
        """Test verify command with --sample parameter."""
        from io import StringIO

        from django.core.management import call_command

        # Create additional teams with flags so they appear in the scoped queryset
        for i in range(5):
            team = Team.objects.create(organization=self.organization, name=f"Team {i}")
            FeatureFlag.objects.create(
                team=team,
                key="test-flag",
                created_by=self.user,
                filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            )

        mock_get_cache.return_value = []
        mock_batch_get_flags.return_value = {}

        out = StringIO()
        call_command("verify_flags_cache", "--sample=3", stdout=out)

        output = out.getvalue()
        # Should verify exactly 3 teams (randomly sampled)
        self.assertIn("3", output)

    def test_verify_all_caches_match(self):
        """Test verify command when all caches are correct."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import update_flags_cache

        # Create a real flag
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Warm the cache so it matches
        update_flags_cache(self.team)

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # When cache matches, there are no issues
        self.assertIn("Cache matches:", output)
        self.assertIn("1 (100.0%)", output)  # 100% match rate

    def test_verify_detects_missing_cache_for_team_with_zero_flags(self):
        """Test that teams with 0 flags but no cache entry are detected as CACHE_MISS."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import clear_flags_cache

        # Delete any existing flags for this team from previous tests
        FeatureFlag.objects.filter(team=self.team).delete()

        # Clear any cache from previous tests to ensure clean state (both Redis and S3)
        clear_flags_cache(self.team, kinds=["redis", "s3"])

        # Team has no flags in DB and no cache entry
        # This should be detected as CACHE_MISS because ALL teams should be cached
        # (even empty ones) to prevent Rust service from hitting database

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should detect cache miss for team with 0 flags
        self.assertIn("CACHE_MISS", output)
        self.assertIn("Cache misses:", output)

    @patch("posthog.models.feature_flag.flags_cache._get_feature_flags_for_teams_batch")
    def test_analyze_batch_load_fallback(self, mock_batch_get_flags):
        """Test analyze command falls back gracefully when batch load fails."""
        from io import StringIO

        from django.core.management import call_command

        # Create a flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Mock batch load to raise exception
        mock_batch_get_flags.side_effect = Exception("Database connection failed")

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", stdout=out)

        output = out.getvalue()
        # Should show warning about fallback
        self.assertIn("Batch load failed", output)
        self.assertIn("falling back", output)
        # But should still complete successfully using individual loads
        self.assertIn("ANALYSIS RESULTS", output)

    def test_verify_batch_load_fallback(self):
        """Test verify command falls back gracefully when batch load fails."""
        from io import StringIO

        from django.core.management import call_command

        from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG

        # Create a flag for the team
        FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Mock the batch_load_fn on the hypercache instance to raise an exception
        original_batch_fn = FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.batch_load_fn

        def failing_batch_load(teams):
            raise Exception("Database error")

        FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.batch_load_fn = failing_batch_load

        try:
            out = StringIO()
            call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

            output = out.getvalue()
            # Should show warning about fallback
            self.assertIn("Batch load failed", output)
            self.assertIn("falling back", output)
            # Should still complete verification (using individual loads)
            self.assertIn("Verification Results", output)
        finally:
            # Restore original batch function
            FLAGS_HYPERCACHE_MANAGEMENT_CONFIG.hypercache.batch_load_fn = original_batch_fn


@override_settings(
    FLAGS_REDIS_URL=None,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "default-test",
        },
    },
)
class TestManagementCommandsWithoutDedicatedCache(BaseTest):
    """Test management commands properly reject execution without dedicated cache."""

    def test_analyze_command_errors_without_flags_redis_url(self):
        """Test analyze command errors when FLAGS_REDIS_URL not set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("analyze_flags_cache_sizes", "--sample-size=1", stdout=out)

        output = out.getvalue()
        # Should error and explain FLAGS_REDIS_URL requirement
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)

    def test_verify_command_errors_without_flags_redis_url(self):
        """Test verify command errors when FLAGS_REDIS_URL not set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should error and explain FLAGS_REDIS_URL requirement
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)

    def test_warm_command_errors_without_flags_redis_url(self):
        """Test warm command errors when FLAGS_REDIS_URL not set."""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("warm_flags_cache", f"--team-ids={self.team.id}", stdout=out)

        output = out.getvalue()
        # Should error and explain FLAGS_REDIS_URL requirement
        self.assertIn("FLAGS_REDIS_URL", output)
        self.assertIn("NOT configured", output)


@override_settings(
    FLAGS_REDIS_URL="redis://test",
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "flags_dedicated": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
)
class TestVerifyFlagsCacheVerboseOutput(BaseTest):
    """Test verbose output formatting for verify_flags_cache command."""

    def setUp(self):
        super().setUp()
        clear_flags_cache(self.team, kinds=["redis", "s3"])

    def test_verbose_missing_in_cache(self):
        """Test verbose output for MISSING_IN_CACHE diff type."""
        from io import StringIO

        from django.core.management import call_command

        # Create flag but don't cache it - this creates a MISSING_IN_CACHE scenario
        FeatureFlag.objects.create(
            team=self.team,
            key="uncached-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # First warm the cache to establish it, then create a new flag
        update_flags_cache(self.team)

        # Create another flag that won't be in cache
        FeatureFlag.objects.create(
            team=self.team,
            key="new-uncached-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--verbose", stdout=out)

        output = out.getvalue()
        self.assertIn("new-uncached-flag", output)
        self.assertIn("exists in DB but missing from cache", output)

    def test_verbose_stale_in_cache(self):
        """Test verbose output for STALE_IN_CACHE diff type."""
        from io import StringIO

        from django.core.management import call_command

        # Create flag and cache it
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="stale-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        update_flags_cache(self.team)

        # Delete the flag (cache now stale)
        flag.delete()

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--verbose", stdout=out)

        output = out.getvalue()
        self.assertIn("stale-flag", output)
        self.assertIn("exists in cache but deleted from DB", output)

    def test_verbose_field_mismatch(self):
        """Test verbose output for FIELD_MISMATCH diff type with field details."""
        from io import StringIO

        from django.core.management import call_command

        # Create flag and cache it
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="mismatch-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )
        update_flags_cache(self.team)

        # Modify the flag to create a mismatch
        flag.filters = {"groups": [{"properties": [], "rollout_percentage": 100}]}
        flag.save()

        out = StringIO()
        call_command("verify_flags_cache", f"--team-ids={self.team.id}", "--verbose", stdout=out)

        output = out.getvalue()
        self.assertIn("mismatch-flag", output)
        self.assertIn("field values differ", output)
        self.assertIn("Field:", output)
        self.assertIn("DB:", output)
        self.assertIn("Cache:", output)

    def test_verbose_unknown_diff_type_fallback(self):
        """Test verbose output falls back gracefully for unknown diff types."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method with an unknown type
        command = Command()
        out = StringIO()
        command.stdout = OutputWrapper(out)

        unknown_diff = {
            "type": "UNKNOWN_TYPE",
            "flag_key": "test-flag",
        }
        command.format_verbose_diff(unknown_diff)

        output = out.getvalue()
        self.assertIn("Flag 'test-flag'", output)
        self.assertIn("UNKNOWN_TYPE", output)

    def test_verbose_missing_flag_key_uses_flag_id(self):
        """Test verbose output uses flag_id when flag_key is missing."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method without flag_key
        command = Command()
        out = StringIO()
        command.stdout = OutputWrapper(out)

        diff_without_key = {
            "type": "MISSING_IN_CACHE",
            "flag_id": 12345,
            # Note: no flag_key
        }
        command.format_verbose_diff(diff_without_key)

        output = out.getvalue()
        self.assertIn("Flag '12345'", output)

    def test_verbose_empty_field_diffs(self):
        """Test verbose output handles empty field_diffs gracefully."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method with empty field_diffs
        command = Command()
        out = StringIO()
        command.stdout = OutputWrapper(out)

        diff_with_empty_field_diffs = {
            "type": "FIELD_MISMATCH",
            "flag_key": "test-flag",
            "field_diffs": [],  # Empty list
        }
        command.format_verbose_diff(diff_with_empty_field_diffs)

        output = out.getvalue()
        self.assertIn("Flag 'test-flag'", output)
        self.assertIn("field values differ", output)
        # Should not crash despite empty field_diffs

    def test_verbose_missing_field_in_field_diff(self):
        """Test verbose output handles missing 'field' key in field_diff gracefully."""
        from io import StringIO

        from posthog.management.commands.verify_flags_cache import Command

        # Directly test the format_verbose_diff method with malformed field_diff
        command = Command()
        out = StringIO()
        command.stdout = OutputWrapper(out)

        diff_with_malformed_field_diffs = {
            "type": "FIELD_MISMATCH",
            "flag_key": "test-flag",
            "field_diffs": [
                {
                    # Missing 'field' key
                    "db_value": "db_val",
                    "cached_value": "cached_val",
                }
            ],
        }
        command.format_verbose_diff(diff_with_malformed_field_diffs)

        output = out.getvalue()
        self.assertIn("Flag 'test-flag'", output)
        self.assertIn("unknown_field", output)  # Falls back to default
        self.assertIn("db_val", output)
        self.assertIn("cached_val", output)


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

    def test_get_flags_from_cache_returns_none_without_redis_url(self):
        """Test that get_flags_from_cache returns None when FLAGS_REDIS_URL is not set."""
        flags = get_flags_from_cache(self.team)
        assert flags is None

    def test_update_flags_cache_no_op_without_redis_url(self):
        """Test that update_flags_cache is a no-op when FLAGS_REDIS_URL is not set."""
        # This should not raise an error and should be a no-op
        result = update_flags_cache(self.team)

        # Should return False
        assert result is False

        # Since it's a no-op, attempting to get from cache should return None
        flags = get_flags_from_cache(self.team)
        assert flags is None

    def test_clear_flags_cache_no_op_without_redis_url(self):
        """Test that clear_flags_cache is a no-op when FLAGS_REDIS_URL is not set."""
        # This should not raise an error and should be a no-op
        clear_flags_cache(self.team)

        # Should complete without error (nothing to verify as it's a no-op)


@override_settings(FLAGS_REDIS_URL="redis://test", FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=5)
class TestGetTeamIdsWithRecentlyUpdatedFlags(BaseTest):
    """Test _get_team_ids_with_recently_updated_flags batch helper for grace period logic."""

    def test_returns_empty_set_for_team_with_no_flags(self):
        """Test returns empty set for team with no flags."""
        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    def test_returns_team_id_for_recently_updated_flag(self):
        """Test returns team ID for team with recently updated flag."""
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == {self.team.id}

    def test_returns_empty_set_for_old_flag(self):
        """Test returns empty set for team with flag updated outside grace period."""
        from datetime import timedelta

        from django.utils import timezone

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="old-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        # Manually set updated_at to outside grace period
        FeatureFlag.objects.filter(id=flag.id).update(updated_at=timezone.now() - timedelta(minutes=10))

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    @override_settings(FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES=0)
    def test_returns_empty_set_when_grace_period_is_zero(self):
        """Test returns empty set when grace period is disabled (0 minutes)."""
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    def test_returns_empty_set_for_empty_team_ids_list(self):
        """Test returns empty set when given empty list of team IDs."""
        result = _get_team_ids_with_recently_updated_flags([])
        assert result == set()

    def test_returns_team_id_if_any_flag_is_recent(self):
        """Test returns team ID if ANY flag is recent (OR logic across team flags)."""
        from datetime import timedelta

        from django.utils import timezone

        # Old flag outside grace period
        old_flag = FeatureFlag.objects.create(
            team=self.team,
            key="old-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        FeatureFlag.objects.filter(id=old_flag.id).update(updated_at=timezone.now() - timedelta(minutes=10))

        # Recent flag within grace period
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Should return team ID because at least one flag is recent
        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == {self.team.id}

    def test_batch_returns_only_teams_with_recent_flags(self):
        """Test batch query returns only team IDs that have recently updated flags."""
        from datetime import timedelta

        from django.utils import timezone

        # Create second team
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Team 1 has a recent flag
        FeatureFlag.objects.create(
            team=self.team,
            key="recent-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Team 2 has an old flag
        old_flag = FeatureFlag.objects.create(
            team=team2,
            key="old-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        FeatureFlag.objects.filter(id=old_flag.id).update(updated_at=timezone.now() - timedelta(minutes=10))

        # Query both teams - should only return team 1
        result = _get_team_ids_with_recently_updated_flags([self.team.id, team2.id])
        assert result == {self.team.id}

    def test_ignores_recently_deleted_flags(self):
        """Test returns empty set for team with recently deleted flag.

        When a flag is deleted, the cache update removes it. We shouldn't skip
        verification just because a deleted flag was recently updated.
        """
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="deleted-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            deleted=True,  # Flag is deleted
        )
        # Ensure updated_at is recent (within grace period)
        assert flag.updated_at is not None

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()

    def test_ignores_recently_deactivated_flags(self):
        """Test returns empty set for team with recently deactivated flag.

        The grace period function only considers active flags when determining
        whether to skip cache verification. Inactive flags are included in the
        cache (for dependency resolution), but their recent updates should not
        trigger the grace period because their evaluation is deterministic (always false).
        """
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="inactive-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            active=False,  # Flag is inactive
        )
        # Ensure updated_at is recent (within grace period)
        assert flag.updated_at is not None

        result = _get_team_ids_with_recently_updated_flags([self.team.id])
        assert result == set()


class TestGetTeamsWithFlagsQueryset(BaseTest):
    def test_includes_team_with_active_flag(self):
        FeatureFlag.objects.create(team=self.team, key="active-flag", created_by=self.user)
        qs = get_teams_with_flags_queryset()
        assert self.team.id in qs.values_list("id", flat=True)

    def test_includes_team_with_soft_deleted_flag(self):
        FeatureFlag.objects.create(team=self.team, key="del", created_by=self.user, deleted=True)
        qs = get_teams_with_flags_queryset()
        assert self.team.id in qs.values_list("id", flat=True)

    def test_includes_team_with_inactive_flag(self):
        FeatureFlag.objects.create(team=self.team, key="off", created_by=self.user, active=False)
        qs = get_teams_with_flags_queryset()
        assert self.team.id in qs.values_list("id", flat=True)

    def test_excludes_team_with_no_flags(self):
        team_no_flags = Team.objects.create(organization=self.organization, name="No Flags")
        qs = get_teams_with_flags_queryset()
        assert team_no_flags.id not in qs.values_list("id", flat=True)

    def test_queryset_does_not_include_parent_team_join(self):
        """The Q() wrapper in get_teams_with_flags_queryset bypasses
        RootTeamQuerySet.filter() to keep the EXISTS subquery simple.
        If someone removes the Q() wrapper, the query will regress to
        include parent_team joins that are unusable at scale."""
        qs = get_teams_with_flags_queryset()
        sql = str(qs.query).lower()
        # Extract the EXISTS subquery — this is where the regression would appear.
        # The SELECT column list legitimately contains parent_team_id as a Team field.
        exists_start = sql.index("exists(")
        subquery_sql = sql[exists_start:]
        assert "parent_team" not in subquery_sql, (
            f"EXISTS subquery should not reference parent_team, got: {subquery_sql}"
        )

    def test_team_with_multiple_flags_returned_once(self):
        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=self.team, key="flag-2", created_by=self.user)
        qs = get_teams_with_flags_queryset()
        team_ids = list(qs.values_list("id", flat=True))
        assert team_ids.count(self.team.id) == 1


def _make_flag(id: int, key: str, deps: list[int] | None = None, active: bool = True, deleted: bool = False) -> dict:
    """Helper to build a serialized flag dict with optional flag dependencies."""
    properties = []
    for dep_id in deps or []:
        properties.append({"type": "flag", "key": str(dep_id), "value": ["true"], "operator": "exact"})
    return {
        "id": id,
        "key": key,
        "active": active,
        "deleted": deleted,
        "filters": {"groups": [{"properties": properties, "rollout_percentage": 100}]},
    }


class TestExtractDirectDependencyIds:
    @parameterized.expand(
        [
            ("no_dependencies", _make_flag(1, "flag_a"), set()),
            ("single_dependency", _make_flag(1, "flag_a", deps=[2]), {2}),
            ("multiple_dependencies", _make_flag(1, "flag_a", deps=[2, 3]), {2, 3}),
            ("inactive_flag_returns_empty", _make_flag(1, "flag_a", deps=[2], active=False), set()),
            ("deleted_flag_returns_empty", _make_flag(1, "flag_a", deps=[2], deleted=True), set()),
            (
                "non_flag_properties_ignored",
                {
                    "id": 1,
                    "key": "flag_a",
                    "active": True,
                    "deleted": False,
                    "filters": {
                        "groups": [
                            {
                                "properties": [
                                    {"type": "person", "key": "email", "value": "test@example.com"},
                                    {"type": "flag", "key": "2", "value": ["true"], "operator": "exact"},
                                ]
                            }
                        ]
                    },
                },
                {2},
            ),
            (
                "non_numeric_flag_key_ignored",
                {
                    "id": 1,
                    "key": "flag_a",
                    "active": True,
                    "deleted": False,
                    "filters": {
                        "groups": [
                            {
                                "properties": [
                                    {"type": "flag", "key": "not_a_number", "value": ["true"]},
                                ]
                            }
                        ]
                    },
                },
                set(),
            ),
        ]
    )
    def test_extract_direct_dependency_ids(self, _name, flag, expected):
        assert _extract_direct_dependency_ids(flag) == expected


class TestComputeFlagDependencies:
    def test_no_dependencies(self):
        flags = [_make_flag(1, "flag_a"), _make_flag(2, "flag_b")]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == [[1, 2]]
        assert ctx["flags_with_missing_deps"] == []
        assert ctx["transitive_deps"] == {"1": [], "2": []}

    def test_linear_chain(self):
        # A(1) -> B(2) -> C(3)
        flags = [
            _make_flag(1, "flag_a", deps=[2]),
            _make_flag(2, "flag_b", deps=[3]),
            _make_flag(3, "flag_c"),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == [[3], [2], [1]]
        assert ctx["flags_with_missing_deps"] == []
        assert ctx["transitive_deps"] == {"1": [2, 3], "2": [3], "3": []}

    def test_diamond(self):
        # A(1) -> B(2), C(3); B(2) -> D(4); C(3) -> D(4)
        flags = [
            _make_flag(1, "flag_a", deps=[2, 3]),
            _make_flag(2, "flag_b", deps=[4]),
            _make_flag(3, "flag_c", deps=[4]),
            _make_flag(4, "flag_d"),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == [[4], [2, 3], [1]]
        assert ctx["flags_with_missing_deps"] == []
        assert ctx["transitive_deps"] == {"1": [2, 3, 4], "2": [4], "3": [4], "4": []}

    def test_missing_dependency(self):
        # A(1) -> 999 (missing)
        flags = [_make_flag(1, "flag_a", deps=[999])]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == [[1]]
        assert ctx["flags_with_missing_deps"] == [1]
        assert ctx["transitive_deps"] == {"1": []}

    def test_cycle_both_flags_marked(self):
        # A(1) -> B(2) -> A(1)
        # Kahn's: neither flag reaches in-degree 0, so both are excluded from stages.
        flags = [
            _make_flag(1, "flag_a", deps=[2]),
            _make_flag(2, "flag_b", deps=[1]),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == []
        assert ctx["flags_with_missing_deps"] == [1, 2]

    def test_transitive_missing_propagation(self):
        # A(1) -> B(2) -> 999 (missing)
        flags = [
            _make_flag(1, "flag_a", deps=[2]),
            _make_flag(2, "flag_b", deps=[999]),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["flags_with_missing_deps"] == [1, 2]
        assert ctx["dependency_stages"] == [[2], [1]]

    def test_inactive_flag_empty_deps(self):
        # Inactive A(1) has a dep on B(2), but since inactive, deps should be empty
        flags = [
            _make_flag(1, "flag_a", deps=[2], active=False),
            _make_flag(2, "flag_b"),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == [[1, 2]]

    def test_dependency_on_inactive_flag_not_missing(self):
        # A(1) -> inactive B(2). B exists so dependency is valid, but B evaluates to false.
        flags = [
            _make_flag(1, "flag_a", deps=[2]),
            _make_flag(2, "flag_b", active=False),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == [[2], [1]]
        assert ctx["flags_with_missing_deps"] == []

    def test_self_cycle(self):
        # A(1) -> A(1)
        flags = [_make_flag(1, "flag_a", deps=[1])]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == []
        assert ctx["flags_with_missing_deps"] == [1]

    def test_three_node_cycle(self):
        # A(1) -> B(2) -> C(3) -> A(1), plus D(4) -> A(1)
        # Kahn's: A, B, C never reach in-degree 0 (cycle). D depends on cycled A,
        # so D also never reaches in-degree 0. All excluded from stages.
        flags = [
            _make_flag(1, "flag_a", deps=[2]),
            _make_flag(2, "flag_b", deps=[3]),
            _make_flag(3, "flag_c", deps=[1]),
            _make_flag(4, "flag_d", deps=[1]),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["dependency_stages"] == []
        assert ctx["flags_with_missing_deps"] == [1, 2, 3, 4]
        # Cycled flags get empty transitive deps (never peeled by Kahn's)
        assert ctx["transitive_deps"] == {"1": [], "2": [], "3": [], "4": []}

    def test_empty_flags_list(self):
        ctx = _compute_flag_dependencies([])

        assert ctx["dependency_stages"] == []
        assert ctx["flags_with_missing_deps"] == []
        assert ctx["transitive_deps"] == {}

    def test_partial_missing_branch(self):
        # A(1) -> 999 (missing), B(2) -> C(3) (valid)
        flags = [
            _make_flag(1, "flag_a", deps=[999]),
            _make_flag(2, "flag_b", deps=[3]),
            _make_flag(3, "flag_c"),
        ]
        ctx = _compute_flag_dependencies(flags)

        assert ctx["flags_with_missing_deps"] == [1]
        assert ctx["dependency_stages"] == [[1, 3], [2]]


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestComputeFlagDependenciesIntegration(BaseTest):
    def test_get_feature_flags_for_service_includes_dependency_fields(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        result = _get_feature_flags_for_service(self.team)

        assert "evaluation_metadata" in result
        ctx = result["evaluation_metadata"]
        assert "dependency_stages" in ctx
        assert "flags_with_missing_deps" in ctx
        assert "transitive_deps" in ctx
        assert ctx["dependency_stages"] == [[flag.id]]
        assert ctx["flags_with_missing_deps"] == []
        assert ctx["transitive_deps"] == {str(flag.id): []}

        # Per-flag fields should not exist
        flag_data = result["flags"][0]
        assert "direct_dependency_flag_ids" not in flag_data
        assert "dependency_flag_ids" not in flag_data
        assert "has_missing_dependencies" not in flag_data

    def test_batch_includes_dependency_fields(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        result = _get_feature_flags_for_teams_batch([self.team])

        assert "evaluation_metadata" in result[self.team.id]

    def test_service_computes_transitive_deps(self):
        flag_c = FeatureFlag.objects.create(
            team=self.team,
            key="flag-c",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"type": "flag", "key": str(flag_c.id), "value": ["true"], "operator": "exact"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            created_by=self.user,
            filters={
                "groups": [
                    {
                        "properties": [{"type": "flag", "key": str(flag_b.id), "value": ["true"], "operator": "exact"}],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        result = _get_feature_flags_for_service(self.team)
        ctx = result["evaluation_metadata"]

        assert sorted(ctx["transitive_deps"][str(flag_a.id)]) == sorted([flag_b.id, flag_c.id])
        assert ctx["transitive_deps"][str(flag_b.id)] == [flag_c.id]
        assert ctx["transitive_deps"][str(flag_c.id)] == []
        assert ctx["dependency_stages"] == [[flag_c.id], [flag_b.id], [flag_a.id]]


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestExtractCohortIdsFromFlagFilters(BaseTest):
    def test_extracts_cohort_ids_from_active_flag(self):
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": 42}]}],
                },
            }
        ]
        assert _extract_cohort_ids_from_flag_filters(flags_data) == {42}

    @parameterized.expand(
        [
            ("inactive", {"active": False}),
            ("deleted", {"active": True, "deleted": True}),
        ]
    )
    def test_skips_excluded_flag(self, _name, flag_overrides):
        flags_data = [
            {
                **flag_overrides,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": 42}]}],
                },
            }
        ]
        assert _extract_cohort_ids_from_flag_filters(flags_data) == set()

    def test_handles_string_cohort_value(self):
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": "42"}]}],
                },
            }
        ]
        assert _extract_cohort_ids_from_flag_filters(flags_data) == {42}

    def test_skips_non_cohort_properties(self):
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {"type": "person", "key": "email", "value": "test@test.com"},
                                {"type": "cohort", "value": 5},
                            ]
                        }
                    ],
                },
            }
        ]
        assert _extract_cohort_ids_from_flag_filters(flags_data) == {5}

    def test_handles_malformed_value(self):
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": "not_a_number"}]}],
                },
            }
        ]
        assert _extract_cohort_ids_from_flag_filters(flags_data) == set()

    def test_returns_empty_for_no_flags(self):
        assert _extract_cohort_ids_from_flag_filters([]) == set()

    def test_deduplicates_cohort_ids(self):
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 42}]},
                        {"properties": [{"type": "cohort", "value": 42}]},
                    ],
                },
            },
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": 42}]}],
                },
            },
        ]
        assert _extract_cohort_ids_from_flag_filters(flags_data) == {42}


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestGetReferencedCohorts(BaseTest):
    def test_returns_empty_when_no_cohorts_referenced(self):
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "person", "key": "email", "value": "x"}]}],
                },
            }
        ]
        assert _get_referenced_cohorts(self.team.id, flags_data) == []

    def test_returns_referenced_cohort(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
        )
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": cohort.id}]}],
                },
            }
        ]
        result = _get_referenced_cohorts(self.team.id, flags_data)
        assert len(result) == 1
        assert result[0]["id"] == cohort.id
        assert result[0]["name"] == "Test Cohort"

    def test_includes_transitive_cohort_deps(self):
        cohort_b = Cohort.objects.create(
            team=self.team,
            name="Leaf Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "b@b.com", "type": "person"}]}],
                }
            },
        )
        cohort_a = Cohort.objects.create(
            team=self.team,
            name="Parent Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_b.id, "type": "cohort"}]}],
                }
            },
        )
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": cohort_a.id}]}],
                },
            }
        ]
        result = _get_referenced_cohorts(self.team.id, flags_data)
        result_ids = {c["id"] for c in result}
        assert cohort_a.id in result_ids
        assert cohort_b.id in result_ids

    def test_excludes_deleted_cohorts(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Deleted",
            deleted=True,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
        )
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": cohort.id}]}],
                },
            }
        ]
        assert _get_referenced_cohorts(self.team.id, flags_data) == []

    def test_excludes_other_team_cohorts(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        cohort = Cohort.objects.create(
            team=other_team,
            name="Other Team Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
        )
        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": cohort.id}]}],
                },
            }
        ]
        assert _get_referenced_cohorts(self.team.id, flags_data) == []

    def test_handles_circular_cohort_deps(self):
        cohort_a = Cohort.objects.create(
            team=self.team,
            name="A",
            filters={"properties": {"type": "OR", "values": []}},
        )
        cohort_b = Cohort.objects.create(
            team=self.team,
            name="B",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_a.id, "type": "cohort"}]}],
                }
            },
        )
        # Update A to reference B (creating a cycle)
        cohort_a.filters = {
            "properties": {
                "type": "OR",
                "values": [{"type": "OR", "values": [{"key": "id", "value": cohort_b.id, "type": "cohort"}]}],
            }
        }
        cohort_a.save()

        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": cohort_a.id}]}],
                },
            }
        ]
        # Should terminate without infinite loop
        result = _get_referenced_cohorts(self.team.id, flags_data)
        result_ids = {c["id"] for c in result}
        assert cohort_a.id in result_ids
        assert cohort_b.id in result_ids

    def test_terminates_at_depth_limit(self):
        chain: list[Cohort] = []
        for i in range(25):
            filters: dict[str, Any] = {"properties": {"type": "OR", "values": []}}
            if chain:
                filters["properties"]["values"] = [
                    {"type": "OR", "values": [{"key": "id", "value": chain[-1].id, "type": "cohort"}]}
                ]
            cohort = Cohort.objects.create(team=self.team, name=f"chain-{i}", filters=filters)
            chain.append(cohort)

        flags_data = [
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [{"type": "cohort", "value": chain[-1].id}]}],
                },
            }
        ]
        result = _get_referenced_cohorts(self.team.id, flags_data)
        # BFS should stop at depth 20, returning fewer than all 25 cohorts
        assert len(result) <= 20  # BFS loads at most 20 cohorts
        assert len(result) < 25


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestSerializeCohort(BaseTest):
    def test_serializes_all_required_fields(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Test",
            description="A test cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [{"type": "OR", "values": [{"key": "email", "value": "a@a.com", "type": "person"}]}],
                }
            },
        )
        result = _serialize_cohort(cohort)

        # Hypercache/service cohort schema: these 17 fields must always be present in the serialized payload
        expected_fields = {
            "id",
            "name",
            "description",
            "team_id",
            "deleted",
            "filters",
            "query",
            "version",
            "pending_version",
            "count",
            "is_calculating",
            "is_static",
            "errors_calculating",
            "groups",
            "created_by_id",
            "cohort_type",
            "last_backfill_person_properties_at",
        }
        assert set(result.keys()) == expected_fields
        assert result["id"] == cohort.id
        assert result["team_id"] == self.team.id
        assert result["name"] == "Test"
        assert result["deleted"] is False
        assert result["is_static"] is False
        assert result["is_calculating"] is False


@override_settings(FLAGS_REDIS_URL="redis://test")
class TestCohortChangedFlagsCacheSignal(BaseTest):
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    def test_fires_on_cohort_definition_change(self, mock_task):
        cohort = Cohort.objects.create(team=self.team, name="test")
        mock_task.reset_mock()
        cohort.name = "updated"
        cohort.save()
        mock_task.delay.assert_called_with(self.team.id)

    @parameterized.expand(
        [
            ("is_calculating", "is_calculating", True),
            ("count", "count", 100),
            ("version", "version", 2),
        ]
    )
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    def test_skips_recalculation_only_save(self, _name, field, value, mock_task):
        cohort = Cohort.objects.create(team=self.team, name="test")
        mock_task.reset_mock()
        setattr(cohort, field, value)
        cohort.save(update_fields=[field])
        mock_task.delay.assert_not_called()

    @patch("django.db.transaction.on_commit", lambda fn: fn())
    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    def test_skips_cohort_type_only_save(self, mock_task):
        cohort = Cohort.objects.create(team=self.team, name="test")
        mock_task.reset_mock()
        cohort.cohort_type = "behavioral"
        cohort.save(update_fields=["cohort_type"])
        mock_task.delay.assert_not_called()

    @patch("django.db.transaction.on_commit", lambda fn: fn())
    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    def test_fires_on_mixed_recalculation_and_definition_fields(self, mock_task):
        cohort = Cohort.objects.create(team=self.team, name="test")
        mock_task.reset_mock()
        cohort.name = "updated"
        cohort.count = 50
        cohort.save(update_fields=["name", "count"])
        mock_task.delay.assert_called_with(self.team.id)

    @patch("django.db.transaction.on_commit", lambda fn: fn())
    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    def test_fires_on_cohort_delete(self, mock_task):
        cohort = Cohort.objects.create(team=self.team, name="test")
        mock_task.reset_mock()
        cohort.delete()
        mock_task.delay.assert_called_with(self.team.id)

    @override_settings(FLAGS_REDIS_URL=None)
    @patch("django.db.transaction.on_commit", lambda fn: fn())
    @patch("posthog.tasks.feature_flags.update_team_service_flags_cache")
    def test_skips_when_no_flags_redis_url(self, mock_task):
        cohort = Cohort.objects.create(team=self.team, name="test")
        mock_task.reset_mock()
        cohort.name = "updated"
        cohort.save()
        mock_task.delay.assert_not_called()
