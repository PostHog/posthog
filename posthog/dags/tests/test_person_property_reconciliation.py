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
    PersonPropertyDiffs,
    PropertyValue,
    filter_event_person_properties,
    get_person_property_updates_from_clickhouse,
    reconcile_person_properties,
    update_person_with_version_check,
)


class TestClickHouseResultParsing:
    """Test that ClickHouse query results are correctly parsed into PersonPropertyDiffs objects."""

    def test_parses_set_diff_tuples(self):
        """Test that set_diff array of tuples is correctly parsed."""
        # Simulate ClickHouse returning: (person_id, set_diff, set_once_diff, unset_diff)
        # set_diff is an array of (key, value, timestamp) tuples
        # Values are raw JSON strings that get parsed via json.loads()
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",  # person_id (UUID as string)
                [  # set_diff - array of (key, raw_json_value, timestamp) tuples
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
        person_diffs = results[0]
        assert person_diffs.person_id == "018d1234-5678-0000-0000-000000000001"
        assert len(person_diffs.set_updates) == 2
        assert len(person_diffs.set_once_updates) == 0
        assert len(person_diffs.unset_updates) == 0

        # Verify set updates - values are parsed from raw JSON to native types
        assert "email" in person_diffs.set_updates
        assert person_diffs.set_updates["email"].value == "new@example.com"
        assert person_diffs.set_updates["email"].timestamp == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert "name" in person_diffs.set_updates
        assert person_diffs.set_updates["name"].value == "John Doe"
        assert person_diffs.set_updates["name"].timestamp == datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)

    def test_parses_set_once_diff_tuples(self):
        """Test that set_once_diff array of tuples is correctly parsed."""
        # Values are raw JSON strings that get parsed via json.loads()
        mock_rows: list[
            tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000002",
                [],  # set_diff - empty
                [  # set_once_diff - array of (key, raw_json_value, timestamp) tuples
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
        person_diffs = results[0]
        assert len(person_diffs.set_updates) == 0
        assert len(person_diffs.set_once_updates) == 2
        assert len(person_diffs.unset_updates) == 0

        # Verify set_once updates - values are parsed from raw JSON to native types
        assert "initial_referrer" in person_diffs.set_once_updates
        assert person_diffs.set_once_updates["initial_referrer"].value == "google.com"
        assert person_diffs.set_once_updates["initial_referrer"].timestamp == datetime(2024, 1, 10, 8, 0, 0, tzinfo=UTC)

        assert "first_seen" in person_diffs.set_once_updates
        assert person_diffs.set_once_updates["first_seen"].value == "2024-01-10"
        assert person_diffs.set_once_updates["first_seen"].timestamp == datetime(2024, 1, 10, 8, 0, 0, tzinfo=UTC)

    def test_parses_mixed_set_and_set_once(self):
        """Test parsing when both set_diff and set_once_diff have values."""
        # Values are raw JSON strings that get parsed via json.loads()
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
        person_diffs = results[0]
        assert len(person_diffs.set_updates) == 1
        assert len(person_diffs.set_once_updates) == 1
        assert len(person_diffs.unset_updates) == 0

        # Verify set update
        assert "email" in person_diffs.set_updates
        assert person_diffs.set_updates["email"].value == "updated@example.com"

        # Verify set_once update
        assert "initial_source" in person_diffs.set_once_updates
        assert person_diffs.set_once_updates["initial_source"].value == "organic"

    def test_handles_multiple_persons(self):
        """Test parsing results for multiple persons."""
        # Values are raw JSON strings that get parsed via json.loads()
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

        # First person has set update
        assert results[0].person_id == "018d1234-0000-0000-0000-000000000001"
        assert results[0].set_updates["prop1"].value == "val1"

        # Second person has set update
        assert results[1].person_id == "018d1234-0000-0000-0000-000000000002"
        assert results[1].set_updates["prop2"].value == "val2"

        # Third person has set_once update
        assert results[2].person_id == "018d1234-0000-0000-0000-000000000003"
        assert results[2].set_once_updates["prop3"].value == "val3"

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
        # Raw JSON representations are parsed via json.loads() to native Python types:
        # - strings: "hello" -> "hello"
        # - numbers: 123, 3.14 -> int, float
        # - booleans: true, false -> True, False
        # - null -> None
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
        person_diffs = results[0]
        assert len(person_diffs.set_updates) == 6

        # String - parsed from JSON string
        assert person_diffs.set_updates["string_prop"].value == "hello"
        assert isinstance(person_diffs.set_updates["string_prop"].value, str)

        # Integer
        assert person_diffs.set_updates["int_prop"].value == 123
        assert isinstance(person_diffs.set_updates["int_prop"].value, int)

        # Float
        assert person_diffs.set_updates["float_prop"].value == 3.14
        assert isinstance(person_diffs.set_updates["float_prop"].value, float)

        # Boolean true
        assert person_diffs.set_updates["bool_true_prop"].value is True

        # Boolean false
        assert person_diffs.set_updates["bool_false_prop"].value is False

        # Null
        assert person_diffs.set_updates["null_prop"].value is None

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
        person_diffs = results[0]
        assert len(person_diffs.set_updates) == 0
        assert len(person_diffs.set_once_updates) == 0
        assert len(person_diffs.unset_updates) == 2

        # Verify first unset
        assert "email" in person_diffs.unset_updates
        assert person_diffs.unset_updates["email"].value is None
        assert person_diffs.unset_updates["email"].timestamp == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

        # Verify second unset
        assert "old_property" in person_diffs.unset_updates
        assert person_diffs.unset_updates["old_property"].value is None
        assert person_diffs.unset_updates["old_property"].timestamp == datetime(2024, 1, 15, 12, 30, 0, tzinfo=UTC)

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
        person_diffs = results[0]
        assert len(person_diffs.set_updates) == 1
        assert len(person_diffs.set_once_updates) == 1
        assert len(person_diffs.unset_updates) == 1

        # Verify set update
        assert "email" in person_diffs.set_updates
        assert person_diffs.set_updates["email"].value == "updated@example.com"

        # Verify set_once update
        assert "initial_source" in person_diffs.set_once_updates
        assert person_diffs.set_once_updates["initial_source"].value == "organic"

        # Verify unset update
        assert "old_field" in person_diffs.unset_updates
        assert person_diffs.unset_updates["old_field"].value is None


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
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)

        assert result is not None
        assert result["properties"]["email"] == "test@example.com"
        assert "email" in result["properties_last_updated_at"]
        assert result["properties_last_operation"]["email"] == "set"

    def test_set_always_applies(self):
        """Test that $set always applies (CH query pre-filters to only return diffs)."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "old@example.com"},
            "properties_last_updated_at": {"email": "2024-01-10T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={
                "email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value="new@example.com")
            },
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)

        assert result is not None
        assert result["properties"]["email"] == "new@example.com"

    def test_set_once_creates_missing_property(self):
        """Test that $set_once creates a property that doesn't exist in PG."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"other_prop": "value"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={},
            set_once_updates={
                "initial_referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0), value="google.com")
            },
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)

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
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={},
            set_once_updates={
                "initial_referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0), value="google.com")
            },
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)

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
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={
                "prop1": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="val1"),
                "prop2": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="val2"),
            },
            set_once_updates={
                "prop3": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0), value="val3"),
            },
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)

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
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)

        assert result is not None
        assert result["properties"]["email"] == "test@example.com"

    def test_returns_none_when_empty_diffs(self):
        """Test that None is returned when diffs are empty."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "current@example.com"},
            "properties_last_updated_at": {"email": "2024-01-20T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={},
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_person_properties(person, person_diffs)
        assert result is None

    def test_unset_removes_existing_property(self):
        """Test that $unset removes a property."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "test@example.com", "name": "Test User"},
            "properties_last_updated_at": {"email": "2024-01-10T00:00:00+00:00", "name": "2024-01-10T00:00:00+00:00"},
            "properties_last_operation": {"email": "set", "name": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={},
            set_once_updates={},
            unset_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=None)},
        )

        result = reconcile_person_properties(person, person_diffs)

        assert result is not None
        assert "email" not in result["properties"]
        assert "email" not in result["properties_last_updated_at"]
        assert "email" not in result["properties_last_operation"]
        # Other properties should remain unchanged
        assert result["properties"]["name"] == "Test User"

    def test_unset_marks_changed_even_when_property_not_exists(self):
        """Test that $unset marks changed even when property doesn't exist in properties map."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"name": "Test User"},
            "properties_last_updated_at": {"name": "2024-01-10T00:00:00+00:00"},
            "properties_last_operation": {"name": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={},
            set_once_updates={},
            unset_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=None)},
        )

        result = reconcile_person_properties(person, person_diffs)

        # Unset always marks changed (even if key wasn't in properties)
        assert result is not None

    def test_unset_removes_property_with_no_timestamp(self):
        """Test that $unset removes property when there's no existing timestamp."""
        person = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {"email": "test@example.com"},
            "properties_last_updated_at": {},  # No timestamp for email
            "properties_last_operation": {},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={},
            set_once_updates={},
            unset_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=None)},
        )

        result = reconcile_person_properties(person, person_diffs)

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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-nonexistent",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-nonexistent",
            person_property_diffs=person_diffs,
        )

        assert success is False
        assert result_data is None

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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={"name": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="Test User")},
            unset_updates={},
        )

        update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
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
        # Find operations by key since dict iteration order may vary
        email_op = next(op for op in pending_operations if op["key"] == "email")
        name_op = next(op for op in pending_operations if op["key"] == "name")
        assert email_op["value"] == "test@example.com"
        assert email_op["operation"] == "set"
        assert name_op["value"] == "Test User"
        assert name_op["operation"] == "set_once"

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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000002",
            set_updates={"name": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="New Name")},
            set_once_updates={},
            unset_updates={},
        )

        update_person_with_version_check(
            cursor=cursor,
            job_id="run-abc-123",
            team_id=42,
            person_uuid="018d1234-5678-0000-0000-000000000002",
            person_property_diffs=person_diffs,
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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
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

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, _result_data, backup_created = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
            dry_run=False,
            backup_enabled=True,
        )

        assert success is True
        assert backup_created is True


class TestFilterEventPersonProperties:
    """Test the filter_event_person_properties function for conflict resolution."""

    def test_set_wins_when_newer_than_unset(self):
        """Test that $set wins over $unset when set timestamp is newer."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="018d1234-5678-0000-0000-000000000001",
                set_updates={
                    "email": PropertyValue(
                        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value="test@example.com"
                    )
                },
                set_once_updates={},
                unset_updates={
                    "email": PropertyValue(timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC), value=None)
                },
            )
        ]

        result = filter_event_person_properties(person_diffs)

        assert len(result) == 1
        # set should win (newer), unset should be removed
        assert "email" in result[0].set_updates
        assert "email" not in result[0].unset_updates

    def test_unset_wins_when_newer_than_set(self):
        """Test that $unset wins over $set when unset timestamp is newer or equal."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="018d1234-5678-0000-0000-000000000001",
                set_updates={
                    "email": PropertyValue(
                        timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC), value="test@example.com"
                    )
                },
                set_once_updates={},
                unset_updates={
                    "email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=None)
                },
            )
        ]

        result = filter_event_person_properties(person_diffs)

        assert len(result) == 1
        # unset should win (newer), set should be removed
        assert "email" not in result[0].set_updates
        assert "email" in result[0].unset_updates

    def test_set_once_wins_when_newer_than_unset(self):
        """Test that $set_once wins over $unset when set_once timestamp is newer."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="018d1234-5678-0000-0000-000000000001",
                set_updates={},
                set_once_updates={
                    "referrer": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value="google.com")
                },
                unset_updates={
                    "referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC), value=None)
                },
            )
        ]

        result = filter_event_person_properties(person_diffs)

        assert len(result) == 1
        # set_once should win (newer), unset should be removed
        assert "referrer" in result[0].set_once_updates
        assert "referrer" not in result[0].unset_updates

    def test_unset_wins_when_newer_than_set_once(self):
        """Test that $unset wins over $set_once when unset timestamp is newer."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="018d1234-5678-0000-0000-000000000001",
                set_updates={},
                set_once_updates={
                    "referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC), value="google.com")
                },
                unset_updates={
                    "referrer": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=None)
                },
            )
        ]

        result = filter_event_person_properties(person_diffs)

        assert len(result) == 1
        # unset should win (newer), set_once should be removed
        assert "referrer" not in result[0].set_once_updates
        assert "referrer" in result[0].unset_updates

    def test_no_conflict_passes_through(self):
        """Test that operations on different keys pass through unchanged."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="018d1234-5678-0000-0000-000000000001",
                set_updates={
                    "email": PropertyValue(
                        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value="test@example.com"
                    )
                },
                set_once_updates={
                    "referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0, tzinfo=UTC), value="google.com")
                },
                unset_updates={
                    "old_field": PropertyValue(timestamp=datetime(2024, 1, 14, 10, 0, 0, tzinfo=UTC), value=None)
                },
            )
        ]

        result = filter_event_person_properties(person_diffs)

        assert len(result) == 1
        assert "email" in result[0].set_updates
        assert "referrer" in result[0].set_once_updates
        assert "old_field" in result[0].unset_updates

    def test_multiple_persons_filtered_independently(self):
        """Test that multiple persons are filtered independently."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="person1",
                set_updates={
                    "email": PropertyValue(
                        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value="p1@example.com"
                    )
                },
                set_once_updates={},
                unset_updates={
                    "email": PropertyValue(timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC), value=None)
                },
            ),
            PersonPropertyDiffs(
                person_id="person2",
                set_updates={
                    "email": PropertyValue(
                        timestamp=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC), value="p2@example.com"
                    )
                },
                set_once_updates={},
                unset_updates={
                    "email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=None)
                },
            ),
        ]

        result = filter_event_person_properties(person_diffs)

        assert len(result) == 2
        # Person 1: set wins (newer)
        assert "email" in result[0].set_updates
        assert "email" not in result[0].unset_updates
        # Person 2: unset wins (newer)
        assert "email" not in result[1].set_updates
        assert "email" in result[1].unset_updates


class TestPropertyValueDataclass:
    """Test the PropertyValue dataclass structure."""

    def test_property_value_fields(self):
        """Test that PropertyValue has expected fields."""
        pv = PropertyValue(
            timestamp=datetime(2024, 1, 15, 12, 0, 0),
            value="test_value",
        )

        assert pv.timestamp == datetime(2024, 1, 15, 12, 0, 0)
        assert pv.value == "test_value"

    def test_property_value_accepts_any_value_type(self):
        """Test that value field accepts various types."""
        # String
        pv1 = PropertyValue(timestamp=datetime.now(), value="string")
        assert pv1.value == "string"

        # Number
        pv2 = PropertyValue(timestamp=datetime.now(), value=123)
        assert pv2.value == 123

        # Boolean
        pv3 = PropertyValue(timestamp=datetime.now(), value=True)
        assert pv3.value is True

        # None (for unset)
        pv4 = PropertyValue(timestamp=datetime.now(), value=None)
        assert pv4.value is None


class TestPersonPropertyDiffsDataclass:
    """Test the PersonPropertyDiffs dataclass structure."""

    def test_person_property_diffs_fields(self):
        """Test that PersonPropertyDiffs has expected fields."""
        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            set_updates={"email": PropertyValue(timestamp=datetime.now(), value="test@example.com")},
            set_once_updates={"referrer": PropertyValue(timestamp=datetime.now(), value="google.com")},
            unset_updates={"old_field": PropertyValue(timestamp=datetime.now(), value=None)},
        )

        assert person_diffs.person_id == "018d1234-5678-0000-0000-000000000001"
        assert len(person_diffs.set_updates) == 1
        assert len(person_diffs.set_once_updates) == 1
        assert len(person_diffs.unset_updates) == 1
        assert person_diffs.set_updates["email"].value == "test@example.com"
        assert person_diffs.set_once_updates["referrer"].value == "google.com"
        assert person_diffs.unset_updates["old_field"].value is None


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
        person_diffs = results[0]
        assert str(person_diffs.person_id) == str(person_id)

        # Find the unset operation
        assert len(person_diffs.unset_updates) == 1
        assert "email" in person_diffs.unset_updates
        unset_update = person_diffs.unset_updates["email"]

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
        person_diffs = results[0]
        assert len(person_diffs.set_updates) == 1
        assert "name" in person_diffs.set_updates

        # Should have latest value and latest timestamp
        assert person_diffs.set_updates["name"].value == "Latest Name"
        result_ts = person_diffs.set_updates["name"].timestamp.replace(tzinfo=None)
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
        person_diffs = results[0]
        assert len(person_diffs.set_once_updates) == 1
        assert "referrer" in person_diffs.set_once_updates

        # Should have first value and earliest timestamp
        assert person_diffs.set_once_updates["referrer"].value == "google.com"
        result_ts = person_diffs.set_once_updates["referrer"].timestamp.replace(tzinfo=None)
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
        person_diffs = results[0]

        # Both should be returned - $set with value, $unset without
        assert len(person_diffs.set_updates) == 1
        assert "email" in person_diffs.set_updates
        assert person_diffs.set_updates["email"].value == "new@example.com"

        assert len(person_diffs.unset_updates) == 1
        assert "email" in person_diffs.unset_updates
        assert person_diffs.unset_updates["email"].value is None

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
        person_diffs = results[0]

        assert len(person_diffs.set_updates) == 1
        assert "name" in person_diffs.set_updates
        assert person_diffs.set_updates["name"].value == "New Name"

        assert len(person_diffs.set_once_updates) == 1
        assert "first_visit" in person_diffs.set_once_updates
        assert person_diffs.set_once_updates["first_visit"].value == "2024-01-01"

        assert len(person_diffs.unset_updates) == 1
        assert "deprecated_field" in person_diffs.unset_updates
        assert person_diffs.unset_updates["deprecated_field"].value is None
