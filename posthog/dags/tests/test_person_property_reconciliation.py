"""Tests for the person property reconciliation job."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.person_property_reconciliation import (
    PersonPropertyUpdates,
    PropertyUpdate,
    get_person_property_updates_from_clickhouse,
    reconcile_person_properties,
    update_person_with_version_check,
)


class TestClickHouseResultParsing:
    """Test that ClickHouse query results are correctly parsed into PropertyUpdate objects."""

    def test_parses_set_diff_tuples(self):
        """Test that set_diff array of tuples is correctly parsed."""
        # Simulate ClickHouse returning: (person_id, set_diff, set_once_diff)
        # set_diff is an array of (key, value, timestamp) tuples
        # Values are raw JSON strings from JSONExtractKeysAndValuesRaw (strings are double-quoted)
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",  # person_id (UUID as string)
                [  # set_diff - array of tuples (values are raw JSON)
                    ("email", '"new@example.com"', datetime(2024, 1, 15, 12, 0, 0)),
                    ("name", '"John Doe"', datetime(2024, 1, 15, 12, 30, 0)),
                ],
                [],  # set_once_diff - empty
                [],  # unset_diff - empty
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 1
        person_updates = results[0]
        assert person_updates.person_id == "018d1234-5678-0000-0000-000000000001"
        assert len(person_updates.updates) == 2

        # Verify first update - quotes should be stripped
        assert person_updates.updates[0].key == "email"
        assert person_updates.updates[0].value == "new@example.com"
        assert person_updates.updates[0].timestamp == datetime(2024, 1, 15, 12, 0, 0)
        assert person_updates.updates[0].operation == "set"

        # Verify second update - quotes should be stripped
        assert person_updates.updates[1].key == "name"
        assert person_updates.updates[1].value == "John Doe"
        assert person_updates.updates[1].operation == "set"

    def test_parses_set_once_diff_tuples(self):
        """Test that set_once_diff array of tuples is correctly parsed."""
        # Values are raw JSON strings from JSONExtractKeysAndValuesRaw
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000002",
                [],  # set_diff - empty
                [  # set_once_diff - array of tuples (values are raw JSON)
                    ("initial_referrer", '"google.com"', datetime(2024, 1, 10, 8, 0, 0)),
                    ("first_seen", '"2024-01-10"', datetime(2024, 1, 10, 8, 0, 0)),
                ],
                [],  # unset_diff - empty
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 1
        person_updates = results[0]
        assert len(person_updates.updates) == 2

        # Verify set_once updates - quotes should be stripped
        assert person_updates.updates[0].key == "initial_referrer"
        assert person_updates.updates[0].value == "google.com"
        assert person_updates.updates[0].operation == "set_once"

        assert person_updates.updates[1].key == "first_seen"
        assert person_updates.updates[1].value == "2024-01-10"
        assert person_updates.updates[1].operation == "set_once"

    def test_parses_mixed_set_and_set_once(self):
        """Test parsing when both set_diff and set_once_diff have values."""
        # Values are raw JSON strings from JSONExtractKeysAndValuesRaw
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000003",
                [("email", '"updated@example.com"', datetime(2024, 1, 15, 12, 0, 0))],  # set_diff
                [("initial_source", '"organic"', datetime(2024, 1, 10, 8, 0, 0))],  # set_once_diff
                [],  # unset_diff - empty
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 1
        updates = results[0].updates
        assert len(updates) == 2

        # set updates come first
        set_updates = [u for u in updates if u.operation == "set"]
        set_once_updates = [u for u in updates if u.operation == "set_once"]

        assert len(set_updates) == 1
        assert len(set_once_updates) == 1
        assert set_updates[0].key == "email"
        assert set_updates[0].value == "updated@example.com"  # quotes stripped
        assert set_once_updates[0].key == "initial_source"
        assert set_once_updates[0].value == "organic"  # quotes stripped

    def test_handles_multiple_persons(self):
        """Test parsing results for multiple persons."""
        # Values are raw JSON strings from JSONExtractKeysAndValuesRaw
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-0000-0000-0000-000000000001",
                [("prop1", '"val1"', datetime(2024, 1, 15, 12, 0, 0))],
                [],
                [],  # unset_diff
            ),
            (
                "018d1234-0000-0000-0000-000000000002",
                [("prop2", '"val2"', datetime(2024, 1, 15, 13, 0, 0))],
                [],
                [],  # unset_diff
            ),
            (
                "018d1234-0000-0000-0000-000000000003",
                [],
                [("prop3", '"val3"', datetime(2024, 1, 10, 8, 0, 0))],
                [],  # unset_diff
            ),
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 3
        assert results[0].person_id == "018d1234-0000-0000-0000-000000000001"
        assert results[0].updates[0].value == "val1"  # quotes stripped
        assert results[1].person_id == "018d1234-0000-0000-0000-000000000002"
        assert results[1].updates[0].value == "val2"  # quotes stripped
        assert results[2].person_id == "018d1234-0000-0000-0000-000000000003"
        assert results[2].updates[0].value == "val3"  # quotes stripped

    def test_skips_persons_with_no_updates(self):
        """Test that persons with empty set_diff, set_once_diff, and unset_diff are skipped."""
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-0000-0000-0000-000000000001",
                [],  # empty set_diff
                [],  # empty set_once_diff
                [],  # empty unset_diff
            ),
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        # Person with no updates should be filtered out
        assert len(results) == 0

    def test_handles_empty_results(self):
        """Test handling when ClickHouse returns no rows."""
        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=[]):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert results == []

    def test_parses_raw_json_value_types(self):
        """Test that raw JSON values from CH are correctly parsed to Python types."""
        # JSONExtractKeysAndValuesRaw returns raw JSON representations:
        # - strings are double-quoted: "hello"
        # - numbers are unquoted: 123, 3.14
        # - booleans are lowercase: true, false
        # - null is literal: null
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",
                [
                    ("string_prop", '"hello"', datetime(2024, 1, 15, 12, 0, 0)),
                    ("int_prop", "123", datetime(2024, 1, 15, 12, 0, 0)),
                    ("float_prop", "3.14", datetime(2024, 1, 15, 12, 0, 0)),
                    ("bool_true_prop", "true", datetime(2024, 1, 15, 12, 0, 0)),
                    ("bool_false_prop", "false", datetime(2024, 1, 15, 12, 0, 0)),
                    ("null_prop", "null", datetime(2024, 1, 15, 12, 0, 0)),
                ],
                [],  # set_once_diff
                [],  # unset_diff
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 1
        updates = results[0].updates
        assert len(updates) == 6

        # String - quotes stripped
        assert updates[0].key == "string_prop"
        assert updates[0].value == "hello"
        assert isinstance(updates[0].value, str)

        # Integer
        assert updates[1].key == "int_prop"
        assert updates[1].value == 123
        assert isinstance(updates[1].value, int)

        # Float
        assert updates[2].key == "float_prop"
        assert updates[2].value == 3.14
        assert isinstance(updates[2].value, float)

        # Boolean true
        assert updates[3].key == "bool_true_prop"
        assert updates[3].value is True

        # Boolean false
        assert updates[4].key == "bool_false_prop"
        assert updates[4].value is False

        # Null
        assert updates[5].key == "null_prop"
        assert updates[5].value is None

    def test_parses_unset_diff_tuples(self):
        """Test that unset_diff array of tuples is correctly parsed."""
        # unset_diff is an array of (key, timestamp) tuples
        # Keys are already parsed in the query with JSON_VALUE (consistent with $set/$set_once)
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",
                [],  # set_diff - empty
                [],  # set_once_diff - empty
                [  # unset_diff - array of (key, timestamp) tuples
                    ("email", datetime(2024, 1, 15, 12, 0, 0)),
                    ("old_property", datetime(2024, 1, 15, 12, 30, 0)),
                ],
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 1
        person_updates = results[0]
        assert len(person_updates.updates) == 2

        # Verify first unset
        assert person_updates.updates[0].key == "email"
        assert person_updates.updates[0].value is None
        assert person_updates.updates[0].timestamp == datetime(2024, 1, 15, 12, 0, 0)
        assert person_updates.updates[0].operation == "unset"

        # Verify second unset
        assert person_updates.updates[1].key == "old_property"
        assert person_updates.updates[1].value is None
        assert person_updates.updates[1].operation == "unset"

    def test_parses_mixed_set_set_once_and_unset(self):
        """Test parsing when all three operation types have values."""
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000004",
                [("email", '"updated@example.com"', datetime(2024, 1, 15, 12, 0, 0))],  # set_diff
                [("initial_source", '"organic"', datetime(2024, 1, 10, 8, 0, 0))],  # set_once_diff
                [("old_field", datetime(2024, 1, 14, 10, 0, 0))],  # unset_diff - keys are already parsed
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
                bug_window_end="2024-01-31T00:00:00Z",
            )

        assert len(results) == 1
        updates = results[0].updates
        assert len(updates) == 3

        set_updates = [u for u in updates if u.operation == "set"]
        set_once_updates = [u for u in updates if u.operation == "set_once"]
        unset_updates = [u for u in updates if u.operation == "unset"]

        assert len(set_updates) == 1
        assert len(set_once_updates) == 1
        assert len(unset_updates) == 1

        assert set_updates[0].key == "email"
        assert set_updates[0].value == "updated@example.com"
        assert set_once_updates[0].key == "initial_source"
        assert set_once_updates[0].value == "organic"
        assert unset_updates[0].key == "old_field"
        assert unset_updates[0].value is None


class TestReconcilePersonProperties:
    """Test the reconcile_person_properties function."""

    def test_set_creates_new_property(self):
        """Test that $set creates a property that doesn't exist in PG."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        updates = [
            PropertyUpdate(
                key="email",
                value="test@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0),
                operation="set",
            )
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert result["properties"]["email"] == "test@example.com"
        assert "email" in result["properties_last_updated_at"]
        assert result["properties_last_operation"]["email"] == "set"

    def test_set_updates_existing_property_when_newer(self):
        """Test that $set updates an existing property when CH timestamp is newer."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "old@example.com"},
            "properties_last_updated_at": {"email": "2024-01-10T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        updates = [
            PropertyUpdate(
                key="email",
                value="new@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            )
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert result["properties"]["email"] == "new@example.com"

    def test_set_skips_when_pg_is_newer(self):
        """Test that $set is skipped when PG timestamp is newer than CH."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        updates = [
            PropertyUpdate(
                key="email",
                value="older@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            )
        ]

        result = reconcile_person_properties(person, updates)

        # No changes needed
        assert result is None

    def test_set_once_creates_missing_property(self):
        """Test that $set_once creates a property that doesn't exist in PG."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"other_prop": "value"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        updates = [
            PropertyUpdate(
                key="initial_referrer",
                value="google.com",
                timestamp=datetime(2024, 1, 10, 8, 0, 0),
                operation="set_once",
            )
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert result["properties"]["initial_referrer"] == "google.com"
        assert result["properties_last_operation"]["initial_referrer"] == "set_once"

    def test_set_once_skips_existing_property(self):
        """Test that $set_once doesn't overwrite an existing property."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"initial_referrer": "facebook.com"},
            "properties_last_updated_at": {"initial_referrer": "2024-01-05T00:00:00+00:00"},
            "properties_last_operation": {"initial_referrer": "set_once"},
        }
        updates = [
            PropertyUpdate(
                key="initial_referrer",
                value="google.com",
                timestamp=datetime(2024, 1, 10, 8, 0, 0),
                operation="set_once",
            )
        ]

        result = reconcile_person_properties(person, updates)

        # No changes - property already exists
        assert result is None

    def test_handles_multiple_updates(self):
        """Test processing multiple updates for different properties."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"existing": "value"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        updates = [
            PropertyUpdate(key="prop1", value="val1", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"),
            PropertyUpdate(key="prop2", value="val2", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"),
            PropertyUpdate(key="prop3", value="val3", timestamp=datetime(2024, 1, 10, 8, 0, 0), operation="set_once"),
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert result["properties"]["prop1"] == "val1"
        assert result["properties"]["prop2"] == "val2"
        assert result["properties"]["prop3"] == "val3"
        # Original property preserved
        assert result["properties"]["existing"] == "value"

    def test_handles_null_properties(self):
        """Test handling when person has None for properties fields."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": None,
            "properties_last_updated_at": None,
            "properties_last_operation": None,
        }
        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert result["properties"]["email"] == "test@example.com"

    def test_returns_none_when_no_changes(self):
        """Test that None is returned when no updates are applicable."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        updates = [
            # This update is older than PG, should be skipped
            PropertyUpdate(
                key="email",
                value="older@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            )
        ]

        result = reconcile_person_properties(person, updates)
        assert result is None

    def test_unset_removes_existing_property(self):
        """Test that $unset removes a property when timestamp is newer."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "test@example.com", "name": "Test User"},
            "properties_last_updated_at": {"email": "2024-01-10T00:00:00+00:00", "name": "2024-01-10T00:00:00+00:00"},
            "properties_last_operation": {"email": "set", "name": "set"},
        }
        updates = [
            PropertyUpdate(
                key="email",
                value=None,
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="unset",
            )
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert "email" not in result["properties"]
        assert "email" not in result["properties_last_updated_at"]
        assert "email" not in result["properties_last_operation"]
        # Other properties should remain unchanged
        assert result["properties"]["name"] == "Test User"

    def test_unset_ignored_when_property_not_exists(self):
        """Test that $unset is a no-op when property doesn't exist."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"name": "Test User"},
            "properties_last_updated_at": {"name": "2024-01-10T00:00:00+00:00"},
            "properties_last_operation": {"name": "set"},
        }
        updates = [
            PropertyUpdate(
                key="email",  # Property doesn't exist
                value=None,
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="unset",
            )
        ]

        result = reconcile_person_properties(person, updates)

        # No changes needed since property doesn't exist
        assert result is None

    def test_unset_ignored_when_timestamp_older(self):
        """Test that $unset is ignored when existing property has newer timestamp."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "test@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        updates = [
            PropertyUpdate(
                key="email",
                value=None,
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),  # Older than existing
                operation="unset",
            )
        ]

        result = reconcile_person_properties(person, updates)

        # No changes since unset timestamp is older
        assert result is None

    def test_set_after_unset_restores_property(self):
        """Test that $set after $unset restores the property (in same batch)."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "old@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        updates = [
            # First unset the property
            PropertyUpdate(
                key="email",
                value=None,
                timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC),
                operation="unset",
            ),
            # Then set it again (later timestamp)
            PropertyUpdate(
                key="email",
                value="new@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            ),
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        # Property should exist with new value
        assert result["properties"]["email"] == "new@example.com"
        assert result["properties_last_operation"]["email"] == "set"

    def test_set_once_after_unset_sets_property(self):
        """Test that $set_once after $unset sets the property (was unset, so it's 'new')."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "old@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        updates = [
            # First unset the property
            PropertyUpdate(
                key="email",
                value=None,
                timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC),
                operation="unset",
            ),
            # Then set_once (should apply since property is now "new")
            PropertyUpdate(
                key="email",
                value="set_once@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set_once",
            ),
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        # set_once should apply after unset removes the property
        assert result["properties"]["email"] == "set_once@example.com"
        assert result["properties_last_operation"]["email"] == "set_once"

    def test_unset_removes_property_with_no_timestamp(self):
        """Test that $unset removes property when there's no existing timestamp."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "test@example.com"},
            "properties_last_updated_at": {},  # No timestamp for email
            "properties_last_operation": {},
        }
        updates = [
            PropertyUpdate(
                key="email",
                value=None,
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="unset",
            )
        ]

        result = reconcile_person_properties(person, updates)

        assert result is not None
        assert "email" not in result["properties"]


class TestUpdatePersonWithVersionCheck:
    """Test the update_person_with_version_check function."""

    def create_mock_cursor(self, person_data=None, update_success=True):
        """Create a mock cursor with configurable behavior."""
        cursor = MagicMock()

        # Mock fetchone to return person data
        cursor.fetchone.return_value = person_data

        # Mock rowcount for UPDATE success/failure
        cursor.rowcount = 1 if update_success else 0

        return cursor

    def test_successful_update(self):
        """Test successful update with version check."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"existing": "value"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 5,
            "is_identified": True,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        cursor = self.create_mock_cursor(person_data=person_data, update_success=True)

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            dry_run=False,
        )

        assert success is True
        assert result_data is not None
        assert result_data["version"] == 6  # version incremented
        assert result_data["properties"]["email"] == "test@example.com"
        assert result_data["properties"]["existing"] == "value"

        # Verify UPDATE was executed
        update_calls = [call for call in cursor.execute.call_args_list if "UPDATE posthog_person" in str(call)]
        assert len(update_calls) == 1

        # Verify backup INSERT was executed
        backup_calls = [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO posthog_person_reconciliation_backup" in str(call)
        ]
        assert len(backup_calls) == 1

        # Verify backup contains correct data
        backup_call_args = backup_calls[0][0]  # (query, params)
        backup_params = backup_call_args[1]
        assert backup_params[0] == "test-job-id"  # job_id
        assert backup_params[1] == 1  # team_id
        assert backup_params[2] == 123  # person_id
        assert backup_params[3] == "018d1234-5678-0000-0000-000000000001"  # uuid
        # Before state
        assert '"existing": "value"' in backup_params[4]  # properties (before)
        assert backup_params[7] == 5  # version (before)
        # After state
        assert '"email": "test@example.com"' in backup_params[12]  # properties_after
        assert backup_params[15] == 6  # version_after

    def test_dry_run_does_not_write(self):
        """Test that dry_run=True doesn't execute UPDATE."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        cursor = self.create_mock_cursor(person_data=person_data)

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            dry_run=True,
        )

        assert success is True
        assert result_data is None  # No data returned for Kafka in dry run

        # Verify UPDATE was NOT executed
        update_calls = [call for call in cursor.execute.call_args_list if "UPDATE posthog_person" in str(call)]
        assert len(update_calls) == 0

        # Verify backup INSERT was STILL executed (for audit trail)
        backup_calls = [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO posthog_person_reconciliation_backup" in str(call)
        ]
        assert len(backup_calls) == 1

    def test_person_not_found(self):
        """Test handling when person doesn't exist in PG."""
        cursor = self.create_mock_cursor(person_data=None)

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-nonexistent",
            property_updates=updates,
        )

        assert success is False
        assert result_data is None

    def test_no_changes_needed(self):
        """Test when reconciliation determines no changes are needed."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
            "version": 5,
            "is_identified": True,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        cursor = self.create_mock_cursor(person_data=person_data)

        # This update is older than what's in PG
        updates = [
            PropertyUpdate(
                key="email",
                value="older@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
        )

        assert success is True
        assert result_data is None  # No changes, no Kafka publish needed

    def test_version_mismatch_retry(self):
        """Test retry on version mismatch (concurrent modification)."""
        person_data_v1 = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        person_data_v2 = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 2,  # Version changed by concurrent update
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        # First fetch returns v1, second fetch returns v2
        cursor.fetchone.side_effect = [person_data_v1, person_data_v2]
        # First update fails (version mismatch), second succeeds
        cursor.rowcount = 0  # Will be set by side_effect

        update_attempt = [0]

        def execute_side_effect(query, *args):
            if "UPDATE posthog_person" in query:
                update_attempt[0] += 1
                # First attempt fails, second succeeds
                cursor.rowcount = 1 if update_attempt[0] > 1 else 0

        cursor.execute.side_effect = execute_side_effect

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            max_retries=3,
        )

        assert success is True
        assert result_data is not None
        assert result_data["version"] == 3  # v2 + 1

    def test_exhausted_retries(self):
        """Test failure after exhausting all retries."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data
        cursor.rowcount = 0  # Always fail version check

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            max_retries=3,
        )

        assert success is False
        assert result_data is None


class TestBackupFunctionality:
    """Test the backup functionality for person property reconciliation."""

    def test_backup_contains_pending_operations(self):
        """Test that backup stores the pending operations correctly."""
        import json

        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"existing": "value"},
            "properties_last_updated_at": {"existing": "2024-01-01T00:00:00"},
            "properties_last_operation": {"existing": "set"},
            "version": 5,
            "is_identified": True,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data
        cursor.rowcount = 1

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
            PropertyUpdate(
                key="name", value="Test User", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set_once"
            ),
        ]

        update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            dry_run=False,
        )

        # Find the backup INSERT call
        backup_calls = [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO posthog_person_reconciliation_backup" in str(call)
        ]
        assert len(backup_calls) == 1

        backup_params = backup_calls[0][0][1]
        pending_operations_json = backup_params[11]  # pending_operations is at index 11
        pending_operations = json.loads(pending_operations_json)

        assert len(pending_operations) == 2
        assert pending_operations[0]["key"] == "email"
        assert pending_operations[0]["value"] == "test@example.com"
        assert pending_operations[0]["operation"] == "set"
        assert pending_operations[1]["key"] == "name"
        assert pending_operations[1]["value"] == "Test User"
        assert pending_operations[1]["operation"] == "set_once"

    def test_backup_not_created_when_no_changes_needed(self):
        """Test that no backup is created when reconciliation determines no changes are needed."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
            "version": 5,
            "is_identified": True,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data

        # This update is older than what's in PG, so no changes needed
        updates = [
            PropertyUpdate(
                key="email",
                value="older@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
        )

        assert success is True
        assert result_data is None

        # Verify backup INSERT was NOT executed (no changes to backup)
        backup_calls = [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO posthog_person_reconciliation_backup" in str(call)
        ]
        assert len(backup_calls) == 0

    def test_backup_preserves_before_and_after_state(self):
        """Test that backup correctly stores both before and after state."""
        import json

        person_data = {
            "id": 456,
            "uuid": "018d1234-5678-0000-0000-000000000002",
            "properties": {"name": "Old Name", "count": 10},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 3,
            "is_identified": False,
            "is_user_id": None,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data
        cursor.rowcount = 1

        updates = [
            PropertyUpdate(key="name", value="New Name", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"),
        ]

        update_person_with_version_check(
            cursor=cursor,
            job_id="run-abc-123",
            team_id=42,
            person_uuid="018d1234-5678-0000-0000-000000000002",
            property_updates=updates,
            dry_run=False,
        )

        backup_calls = [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO posthog_person_reconciliation_backup" in str(call)
        ]
        assert len(backup_calls) == 1

        backup_params = backup_calls[0][0][1]

        # Verify identifiers
        assert backup_params[0] == "run-abc-123"  # job_id
        assert backup_params[1] == 42  # team_id
        assert backup_params[2] == 456  # person_id

        # Verify before state
        properties_before = json.loads(backup_params[4])
        assert properties_before == {"name": "Old Name", "count": 10}
        assert backup_params[7] == 3  # version before

        # Verify after state
        properties_after = json.loads(backup_params[12])
        assert properties_after["name"] == "New Name"
        assert properties_after["count"] == 10  # unchanged property preserved
        assert backup_params[15] == 4  # version after (3 + 1)

    def test_backup_disabled_does_not_create_backup(self):
        """Test that backup_enabled=False skips backup creation."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"existing": "value"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 5,
            "is_identified": True,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data
        cursor.rowcount = 1

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            dry_run=False,
            backup_enabled=False,
        )

        assert success is True
        assert result_data is not None
        assert backup_created is False

        # Verify backup INSERT was NOT executed
        backup_calls = [
            call
            for call in cursor.execute.call_args_list
            if "INSERT INTO posthog_person_reconciliation_backup" in str(call)
        ]
        assert len(backup_calls) == 0

        # But UPDATE should still happen
        update_calls = [call for call in cursor.execute.call_args_list if "UPDATE posthog_person" in str(call)]
        assert len(update_calls) == 1

    def test_backup_created_return_value_true_when_enabled(self):
        """Test that backup_created=True when backup is enabled and changes made."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data
        cursor.rowcount = 1

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            dry_run=False,
            backup_enabled=True,
        )

        assert success is True
        assert backup_created is True

    def test_backup_created_false_when_no_changes_needed(self):
        """Test that backup_created=False when no changes are needed."""
        person_data = {
            "id": 123,
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
            "version": 5,
            "is_identified": True,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        cursor = MagicMock()
        cursor.fetchone.return_value = person_data

        # This update is older than what's in PG
        updates = [
            PropertyUpdate(
                key="email",
                value="older@example.com",
                timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                operation="set",
            ),
        ]

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            backup_enabled=True,
        )

        assert success is True
        assert result_data is None
        assert backup_created is False


class TestPostBugWindowUpdatePreservation:
    """
    Test that reconciliation does NOT overwrite properties that were legitimately
    updated AFTER the bug window.

    This is a critical edge case: if a property was set during the bug window (and missed
    due to the bug), but then set again AFTER the bug window (correctly applied), the
    reconciliation should NOT revert to the bug-window value.

    The problem: properties_last_updated_at is NOT consistently updated when properties
    change after person creation. This means we can't reliably compare timestamps to
    determine which value is newer.
    """

    def test_post_bug_window_update_should_not_be_overwritten(self):
        """
        Timeline:
        - t1: Person created WITHOUT property P
        - t2: Bug window starts
        - t2.5: Event sets P=V1 (in bug window, missed due to bug)
        - t3: Bug window ends
        - t3.5: Event sets P=V2 (after bug window, correctly applied)
        - t4: Reconciliation runs

        Expected: P should remain V2, NOT be reverted to V1
        """
        # Timestamps with clear spacing (prefixed with _ to indicate documentation-only)
        _t1 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)  # Person creation  # noqa: F841
        _t2 = datetime(2024, 1, 10, 0, 0, 0, tzinfo=UTC)  # Bug window start  # noqa: F841
        t2_5 = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)  # Event in bug window
        _t3 = datetime(2024, 1, 20, 0, 0, 0, tzinfo=UTC)  # Bug window end  # noqa: F841
        _t3_5 = datetime(2024, 1, 25, 12, 0, 0, tzinfo=UTC)  # Event after bug window  # noqa: F841
        # t4 = now (reconciliation time)

        V1 = "value_from_bug_window"
        V2 = "value_after_bug_window"

        # Current state in Postgres:
        # - P was set to V2 at _t3_5 (after bug window)
        # - properties_last_updated_at[P] is NOT SET because it's only set at creation time
        #   and P was added after creation
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"P": V2},  # Current value from _t3_5
            "properties_last_updated_at": {},  # Empty! P was added after creation
            "properties_last_operation": {},
        }

        # ClickHouse returns the bug-window update that was missed
        updates = [
            PropertyUpdate(
                key="P",
                value=V1,
                timestamp=t2_5,  # From the bug window
                operation="set",
            )
        ]

        result = reconcile_person_properties(person, updates)

        # CURRENT BEHAVIOR (buggy): result is not None, P gets set to V1
        # This happens because properties_last_updated_at["P"] is None,
        # so the comparison `existing_ts_str is None` triggers the update
        #
        # EXPECTED BEHAVIOR: result should be None (no changes),
        # P should remain V2 because V2 was set AFTER V1

        # This assertion documents the EXPECTED behavior
        # If this test fails, it means the reconciliation is incorrectly overwriting
        # post-bug-window updates
        assert result is None, (
            f"Reconciliation should NOT overwrite post-bug-window value. "
            f"Expected P to remain '{V2}', but reconciliation wants to set it to '{V1}'. "
            f"This happens because properties_last_updated_at is not maintained on updates."
        )

    def test_extended_window_correctly_preserves_latest_value(self):
        """
        Same timeline as above, but this time the ClickHouse query includes BOTH updates.
        This simulates extending the query window to capture all events.

        Timeline:
        - t1: Person created WITHOUT property P
        - t2: Bug window starts
        - t2.5: Event sets P=V1 (in bug window)
        - t3: Bug window ends
        - t3.5: Event sets P=V2 (after original bug window, but included in extended query)
        - t4: Reconciliation runs

        When both updates are returned by ClickHouse, the reconciliation should
        correctly determine that V2 (from t3.5) is the winning value since it's newer.
        """
        # Timestamps with clear spacing (prefixed with _ to indicate documentation-only)
        _t1 = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)  # Person creation  # noqa: F841
        _t2 = datetime(2024, 1, 10, 0, 0, 0, tzinfo=UTC)  # Bug window start  # noqa: F841
        t2_5 = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)  # Event in bug window
        _t3 = datetime(2024, 1, 20, 0, 0, 0, tzinfo=UTC)  # Bug window end  # noqa: F841
        t3_5 = datetime(2024, 1, 25, 12, 0, 0, tzinfo=UTC)  # Event after bug window
        # t4 = now (reconciliation time)

        V1 = "value_from_bug_window"
        V2 = "value_after_bug_window"

        # Current state in Postgres:
        # - P was set to V2 at t3_5 (after bug window)
        # - properties_last_updated_at[P] is NOT SET because it's only set at creation time
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"P": V2},  # Current value from t3_5
            "properties_last_updated_at": {},  # Empty! P was added after creation
            "properties_last_operation": {},
        }

        # When we extend the query window, ClickHouse returns BOTH updates
        # The reconciliation logic needs to handle multiple updates for the same key
        # and pick the one with the latest timestamp
        #
        # NOTE: Currently reconcile_person_properties processes updates in order
        # and the last one wins (for $set). If we pass them in timestamp order,
        # V2 should win.
        updates = [
            PropertyUpdate(
                key="P",
                value=V1,
                timestamp=t2_5,  # Earlier update
                operation="set",
            ),
            PropertyUpdate(
                key="P",
                value=V2,
                timestamp=t3_5,  # Later update - should win
                operation="set",
            ),
        ]

        result = reconcile_person_properties(person, updates)

        # With both updates present, reconciliation should see that the current
        # value (V2) matches the latest update (V2 from t3.5), so no change needed
        #
        # OR if it does return a result, it should set P to V2 (not V1)
        if result is not None:
            assert result["properties"]["P"] == V2, (
                f"When both updates are present, reconciliation should use the latest value. "
                f"Expected '{V2}', got '{result['properties']['P']}'"
            )


class TestPropertyUpdateDataclass:
    """Test the PropertyUpdate dataclass structure."""

    def test_property_update_fields(self):
        """Test that PropertyUpdate has expected fields."""
        update = PropertyUpdate(
            key="test_key",
            value="test_value",
            timestamp=datetime(2024, 1, 15, 12, 0, 0),
            operation="set",
        )

        assert update.key == "test_key"
        assert update.value == "test_value"
        assert update.timestamp == datetime(2024, 1, 15, 12, 0, 0)
        assert update.operation == "set"

    def test_property_update_accepts_any_value_type(self):
        """Test that value field accepts various types."""
        # String
        update1 = PropertyUpdate(key="k", value="string", timestamp=datetime.now(), operation="set")
        assert update1.value == "string"

        # Number (as string from CH)
        update2 = PropertyUpdate(key="k", value="123", timestamp=datetime.now(), operation="set")
        assert update2.value == "123"

        # Boolean (as string from CH)
        update3 = PropertyUpdate(key="k", value="true", timestamp=datetime.now(), operation="set")
        assert update3.value == "true"


class TestPersonPropertyUpdatesDataclass:
    """Test the PersonPropertyUpdates dataclass structure."""

    def test_person_property_updates_fields(self):
        """Test that PersonPropertyUpdates has expected fields."""
        updates = [
            PropertyUpdate(key="k1", value="v1", timestamp=datetime.now(), operation="set"),
            PropertyUpdate(key="k2", value="v2", timestamp=datetime.now(), operation="set_once"),
        ]
        person_updates = PersonPropertyUpdates(
            person_id="018d1234-5678-0000-0000-000000000001",
            updates=updates,
        )

        assert person_updates.person_id == "018d1234-5678-0000-0000-000000000001"
        assert len(person_updates.updates) == 2
        assert person_updates.updates[0].key == "k1"
        assert person_updates.updates[1].key == "k2"


@pytest.mark.django_db
class TestClickHouseQueryIntegration:
    """Integration tests that insert data into ClickHouse and run the actual query."""

    def test_unset_uses_latest_timestamp_regression(self, cluster: ClickhouseCluster):
        """
        Regression test: $unset should use max(timestamp), not min(timestamp).

        If a person has two $unset operations on the same key at different times,
        the returned timestamp should be the latest one (max), not the earliest (min).
        This was a bug where $unset incorrectly used min(e.timestamp).
        """

        team_id = 99901
        person_id = UUID("11111111-1111-1111-1111-000000000001")
        # Use naive datetimes since ClickHouse returns naive datetimes
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        # Two timestamps for the same $unset operation
        earlier_ts = now - timedelta(days=5)
        later_ts = now - timedelta(days=2)

        # Insert events with $unset at different timestamps
        events = [
            # First $unset at earlier timestamp
            (
                team_id,
                "distinct_id_1",
                person_id,
                earlier_ts,
                json.dumps({"$unset": ["email"]}),
            ),
            # Second $unset at later timestamp (should be the winner)
            (
                team_id,
                "distinct_id_1",
                person_id,
                later_ts,
                json.dumps({"$unset": ["email"]}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert person with the "email" property (so $unset has something to unset)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"email": "test@example.com", "name": "Test User"}),
                1,  # version
                now - timedelta(days=8),  # _timestamp within bug window
            )
        ]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        # Run the actual query
        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        person_updates = results[0]
        assert str(person_updates.person_id) == str(person_id)

        # Find the unset operation
        unset_updates = [u for u in person_updates.updates if u.operation == "unset"]
        assert len(unset_updates) == 1
        unset_update = unset_updates[0]

        assert unset_update.key == "email"
        assert unset_update.value is None

        # Regression check: timestamp should be the LATER one (max), not earlier (min)
        # Allow 1 second tolerance for timestamp comparison
        # Strip timezone for comparison since CH returns tz-aware but we created naive timestamps
        result_ts = unset_update.timestamp.replace(tzinfo=None)
        assert abs((result_ts - later_ts).total_seconds()) < 1, (
            f"$unset should use max(timestamp). "
            f"Expected ~{later_ts}, got {result_ts}. "
            f"Earlier timestamp was {earlier_ts}."
        )

    def test_set_uses_latest_timestamp(self, cluster: ClickhouseCluster):
        """$set should use max(timestamp) - latest value wins."""

        team_id = 99902
        person_id = UUID("22222222-2222-2222-2222-000000000002")
        # Use naive datetimes since ClickHouse returns naive datetimes
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        earlier_ts = now - timedelta(days=5)
        later_ts = now - timedelta(days=2)

        events = [
            (team_id, "distinct_id_2", person_id, earlier_ts, json.dumps({"$set": {"name": "First Name"}})),
            (team_id, "distinct_id_2", person_id, later_ts, json.dumps({"$set": {"name": "Latest Name"}})),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with different value for "name" so set_diff includes it
        person_data = [(team_id, person_id, json.dumps({"name": "Old Name"}), 1, now - timedelta(days=8))]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        set_updates = [u for u in results[0].updates if u.operation == "set"]
        assert len(set_updates) == 1

        # Should have latest value and latest timestamp
        assert set_updates[0].key == "name"
        assert set_updates[0].value == "Latest Name"
        result_ts = set_updates[0].timestamp.replace(tzinfo=None)
        assert abs((result_ts - later_ts).total_seconds()) < 1

    def test_set_once_uses_earliest_timestamp(self, cluster: ClickhouseCluster):
        """$set_once should use min(timestamp) - first value wins."""

        team_id = 99903
        person_id = UUID("33333333-3333-3333-3333-000000000003")
        # Use naive datetimes since ClickHouse returns naive datetimes
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        earlier_ts = now - timedelta(days=5)
        later_ts = now - timedelta(days=2)

        events = [
            (team_id, "distinct_id_3", person_id, earlier_ts, json.dumps({"$set_once": {"referrer": "google.com"}})),
            (team_id, "distinct_id_3", person_id, later_ts, json.dumps({"$set_once": {"referrer": "facebook.com"}})),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person WITHOUT "referrer" so set_once_diff includes it
        person_data = [(team_id, person_id, json.dumps({"other_prop": "value"}), 1, now - timedelta(days=8))]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        set_once_updates = [u for u in results[0].updates if u.operation == "set_once"]
        assert len(set_once_updates) == 1

        # Should have first value and earliest timestamp
        assert set_once_updates[0].key == "referrer"
        assert set_once_updates[0].value == "google.com"
        result_ts = set_once_updates[0].timestamp.replace(tzinfo=None)
        assert abs((result_ts - earlier_ts).total_seconds()) < 1

    def test_multiple_operations_same_key_in_batch(self, cluster: ClickhouseCluster):
        """
        Test multiple operation types on same key: $set then $unset.

        Both operations are for the same key but different operation types.
        Each should be returned separately.
        """

        team_id = 99904
        person_id = UUID("44444444-4444-4444-4444-000000000004")
        # Use naive datetimes since ClickHouse returns naive datetimes
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        set_ts = now - timedelta(days=5)
        unset_ts = now - timedelta(days=2)

        events = [
            # First $set the property
            (team_id, "distinct_id_4", person_id, set_ts, json.dumps({"$set": {"email": "new@example.com"}})),
            # Then $unset the same property (later)
            (team_id, "distinct_id_4", person_id, unset_ts, json.dumps({"$unset": ["email"]})),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with existing email (different value so $set is in diff, and exists so $unset is in diff)
        person_data = [(team_id, person_id, json.dumps({"email": "old@example.com"}), 1, now - timedelta(days=8))]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1

        set_updates = [u for u in results[0].updates if u.operation == "set"]
        unset_updates = [u for u in results[0].updates if u.operation == "unset"]

        # Both should be returned - $set with value, $unset without
        assert len(set_updates) == 1
        assert set_updates[0].key == "email"
        assert set_updates[0].value == "new@example.com"

        assert len(unset_updates) == 1
        assert unset_updates[0].key == "email"
        assert unset_updates[0].value is None

    def test_mixed_operations_different_keys(self, cluster: ClickhouseCluster):
        """Test $set, $set_once, and $unset on different keys in same event."""

        team_id = 99905
        person_id = UUID("55555555-5555-5555-5555-000000000005")
        # Use naive datetimes since ClickHouse returns naive datetimes
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        event_ts = now - timedelta(days=3)

        events = [
            (
                team_id,
                "distinct_id_5",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set": {"name": "New Name"},
                        "$set_once": {"first_visit": "2024-01-01"},
                        "$unset": ["deprecated_field"],
                    }
                ),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with name (different), no first_visit, has deprecated_field
        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"name": "Old Name", "deprecated_field": "to_remove"}),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = results[0].updates

        set_updates = [u for u in updates if u.operation == "set"]
        set_once_updates = [u for u in updates if u.operation == "set_once"]
        unset_updates = [u for u in updates if u.operation == "unset"]

        assert len(set_updates) == 1
        assert set_updates[0].key == "name"
        assert set_updates[0].value == "New Name"

        assert len(set_once_updates) == 1
        assert set_once_updates[0].key == "first_visit"
        assert set_once_updates[0].value == "2024-01-01"

        assert len(unset_updates) == 1
        assert unset_updates[0].key == "deprecated_field"
        assert unset_updates[0].value is None
