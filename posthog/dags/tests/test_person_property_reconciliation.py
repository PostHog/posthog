"""Tests for the person property reconciliation job."""

import os
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
    RawPersonPropertyUpdates,
    SkipReason,
    compare_raw_updates_with_person_state,
    fetch_person_properties_from_clickhouse,
    filter_event_person_properties,
    format_ch_timestamp,
    get_person_property_updates_from_clickhouse,
    get_person_property_updates_windowed,
    merge_raw_person_property_updates,
    parse_ch_timestamp,
    query_team_ids_from_clickhouse,
    reconcile_person_properties,
    reconcile_with_concurrent_changes,
    update_person_with_version_check,
)


class TestClickHouseResultParsing:
    """Test that ClickHouse query results are correctly parsed into PersonPropertyDiffs objects."""

    def test_parses_set_diff_tuples(self):
        """Test that set_diff array of tuples is correctly parsed."""
        # Simulate ClickHouse returning: (person_id, person_version, set_diff, set_once_diff, unset_diff)
        # set_diff is an array of (key, value, timestamp) tuples
        # Values are raw JSON strings that get parsed via json.loads()
        mock_rows: list[
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",  # person_id (UUID as string)
                1,  # person_version
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
            )

        assert len(results) == 1
        person_diffs = results[0]
        assert person_diffs.person_id == "018d1234-5678-0000-0000-000000000001"
        assert person_diffs.person_version == 1
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000002",
                1,  # person_version
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000003",
                1,  # person_version
                [("email", '"updated@example.com"', datetime(2024, 1, 15, 12, 0, 0))],  # set_diff
                [("initial_source", '"organic"', datetime(2024, 1, 10, 8, 0, 0))],  # set_once_diff
                [],  # unset_diff - empty
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-0000-0000-0000-000000000001",
                1,  # person_version
                [("prop1", '"val1"', datetime(2024, 1, 15, 12, 0, 0))],
                [],
                [],  # unset_diff
            ),
            (
                "018d1234-0000-0000-0000-000000000002",
                2,  # person_version
                [("prop2", '"val2"', datetime(2024, 1, 15, 13, 0, 0))],
                [],
                [],  # unset_diff
            ),
            (
                "018d1234-0000-0000-0000-000000000003",
                3,  # person_version
                [],
                [("prop3", '"val3"', datetime(2024, 1, 10, 8, 0, 0))],
                [],  # unset_diff
            ),
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-0000-0000-0000-000000000001",
                1,  # person_version
                [],  # empty set_diff
                [],  # empty set_once_diff
                [],  # empty unset_diff
            ),
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
            )

        # Person with no updates should be filtered out
        assert len(results) == 0

    def test_handles_empty_results(self):
        """Test handling when ClickHouse returns no rows."""
        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=[]):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",
                1,  # person_version
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000001",
                1,  # person_version
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
            tuple[
                str, int, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]], list[tuple[str, datetime]]
            ]
        ] = [
            (
                "018d1234-5678-0000-0000-000000000004",
                1,  # person_version
                [("email", '"updated@example.com"', datetime(2024, 1, 15, 12, 0, 0))],  # set_diff
                [("initial_source", '"organic"', datetime(2024, 1, 10, 8, 0, 0))],  # set_once_diff
                [("old_field", datetime(2024, 1, 14, 10, 0, 0))],  # unset_diff - keys are already parsed
            )
        ]

        with patch("posthog.dags.person_property_reconciliation.sync_execute", return_value=mock_rows):
            results = get_person_property_updates_from_clickhouse(
                team_id=1,
                bug_window_start="2024-01-01T00:00:00Z",
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

    def test_no_bug_window_end_parameter_regression(self):
        """Regression test: get_person_property_updates_from_clickhouse should NOT accept bug_window_end.

        The function uses ClickHouse's now() for the upper bound, ensuring all events
        from bug_window_start until the current time are included. This is intentional:
        - bug_window_start/end is used to FIND teams with affected events
        - When processing a team, we read ALL events from bug_window_start to now()

        This prevents missing events that occurred after the initial bug window discovery.
        """
        import inspect

        sig = inspect.signature(get_person_property_updates_from_clickhouse)
        param_names = list(sig.parameters.keys())

        assert "bug_window_end" not in param_names, (
            "bug_window_end should not be a parameter. The function should use ClickHouse's now() for the upper bound."
        )
        assert "team_id" in param_names
        assert "bug_window_start" in param_names


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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=1,
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
            person_version=5,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created, _skip_reason = update_person_with_version_check(
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
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created, _skip_reason = update_person_with_version_check(
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
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created, skip_reason = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-nonexistent",
            person_property_diffs=person_diffs,
        )

        assert success is False
        assert result_data is None
        assert skip_reason == SkipReason.NOT_FOUND

    @patch("posthog.dags.person_property_reconciliation.fetch_person_properties_from_clickhouse")
    def test_version_mismatch_retry(self, mock_fetch_ch_properties):
        """Test retry on version mismatch (concurrent modification).

        When the first UPDATE fails due to version mismatch:
        1. On retry, if Postgres version differs from CH version (person_version in diffs)
        2. We fetch CH properties for 3-way merge
        3. Apply changes and retry UPDATE with new target version
        """
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
            "properties": {"other": "concurrent_change"},  # Concurrent change to Postgres
            "properties_last_updated_at": {"other": "2024-01-14T00:00:00"},
            "properties_last_operation": {"other": "set"},
            "version": 2,  # Version changed by concurrent update
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }

        # CH properties at version 1 (baseline for 3-way merge)
        mock_fetch_ch_properties.return_value = {}

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
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created, _skip_reason = update_person_with_version_check(
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
        # Concurrent change should be preserved, our change should be applied
        assert result_data["properties"]["other"] == "concurrent_change"
        assert result_data["properties"]["email"] == "test@example.com"

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
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, _backup_created, skip_reason = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
            max_retries=3,
        )

        assert success is False
        assert result_data is None
        assert skip_reason == SkipReason.VERSION_CONFLICT


class TestBatchCommits:
    """Test that batch commits work correctly with different batch sizes.

    These tests use the process_persons_in_batches helper function directly,
    which is separated from the Dagster op for testability.
    """

    @pytest.mark.parametrize(
        "num_persons,batch_size,expected_commits",
        [
            # 5 persons, batch_size=2: batches of [2, 2, 1] = 3 commits
            (5, 2, 3),
            # 4 persons, batch_size=2: batches of [2, 2] = 2 commits (no partial)
            (4, 2, 2),
            # 3 persons, batch_size=5: batches of [3] = 1 commit (all in one partial batch)
            (3, 5, 1),
            # 1 person, batch_size=100: batches of [1] = 1 commit
            (1, 100, 1),
            # 6 persons, batch_size=0 (disabled): single commit at end
            (6, 0, 1),
        ],
    )
    def test_batch_commits_correct_number_of_times(self, num_persons: int, batch_size: int, expected_commits: int):
        """
        Test that commits happen the correct number of times based on batch_size.

        With batch_size=2 and 5 persons:
        - Batch 1: persons 0,1 → commit
        - Batch 2: persons 2,3 → commit
        - Batch 3: person 4 → commit (partial final batch)
        Total: 3 commits
        """
        from posthog.dags.person_property_reconciliation import process_persons_in_batches

        # Create mock persons with updates (timestamps must be timezone-aware)
        person_diffs_list = []
        for i in range(num_persons):
            person_diffs_list.append(
                PersonPropertyDiffs(
                    person_id=f"person-uuid-{i}",
                    person_version=1,
                    set_updates={
                        "prop": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=f"value_{i}")
                    },
                    set_once_updates={},
                    unset_updates={},
                )
            )

        # Mock cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": 123,
            "uuid": "test-uuid",
            "properties": {"prop": "old_value"},
            "properties_last_updated_at": {"prop": "2024-01-01T00:00:00+00:00"},
            "properties_last_operation": {"prop": "set"},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        mock_cursor.rowcount = 1  # UPDATE succeeds

        # Track commits
        commit_count = [0]

        def mock_commit():
            commit_count[0] += 1

        # Track batch callbacks
        batch_callbacks = []

        def on_batch_committed(batch_num, batch_persons):
            batch_callbacks.append((batch_num, len(batch_persons)))

        # Call the helper function directly
        result = process_persons_in_batches(
            person_property_diffs=person_diffs_list,
            cursor=mock_cursor,
            job_id="test-job-id",
            team_id=1,
            batch_size=batch_size,
            dry_run=False,
            backup_enabled=False,
            commit_fn=mock_commit,
            on_batch_committed=on_batch_committed,
        )

        # Verify commit was called the expected number of times
        assert result.total_commits == expected_commits, (
            f"Expected {expected_commits} commits for {num_persons} persons with batch_size={batch_size}, "
            f"got {result.total_commits}"
        )

        # Verify all persons were processed
        assert result.total_processed == num_persons
        assert result.total_updated == num_persons

        # Verify batch callback was called for each batch
        assert len(batch_callbacks) == expected_commits

    def test_batch_commits_partial_final_batch_all_persons_updated(self):
        """
        Specifically test that the partial final batch commits correctly
        and all persons are updated (not just full batches).

        5 persons with batch_size=2:
        - Batch 1: persons 0,1 → commit ✓
        - Batch 2: persons 2,3 → commit ✓
        - Batch 3: person 4 → commit ✓ (THIS is the partial batch we're testing)
        """
        from posthog.dags.person_property_reconciliation import process_persons_in_batches

        num_persons = 5
        batch_size = 2

        person_uuids = [f"uuid-{i}" for i in range(num_persons)]
        person_diffs_list = [
            PersonPropertyDiffs(
                person_id=uuid,
                person_version=1,
                set_updates={
                    "email": PropertyValue(
                        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value=f"user{i}@example.com"
                    )
                },
                set_once_updates={},
                unset_updates={},
            )
            for i, uuid in enumerate(person_uuids)
        ]

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": 123,
            "uuid": "test-uuid",
            "properties": {"email": "old@example.com"},
            "properties_last_updated_at": {"email": "2024-01-01T00:00:00+00:00"},
            "properties_last_operation": {"email": "set"},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        mock_cursor.rowcount = 1

        commit_count = [0]

        def mock_commit():
            commit_count[0] += 1

        # Track batch sizes to verify partial final batch
        batch_sizes = []

        def on_batch_committed(batch_num, batch_persons):
            batch_sizes.append(len(batch_persons))

        result = process_persons_in_batches(
            person_property_diffs=person_diffs_list,
            cursor=mock_cursor,
            job_id="test-job-id",
            team_id=1,
            batch_size=batch_size,
            dry_run=False,
            backup_enabled=False,
            commit_fn=mock_commit,
            on_batch_committed=on_batch_committed,
        )

        # All 5 persons should be processed and updated
        assert result.total_processed == 5
        assert result.total_updated == 5
        assert result.total_skipped == 0

        # 3 commits: batch 1 (2), batch 2 (2), batch 3 (1)
        assert result.total_commits == 3

        # Verify batch sizes: [2, 2, 1]
        assert batch_sizes == [2, 2, 1], f"Expected batches [2, 2, 1], got {batch_sizes}"

    def test_empty_person_list_no_commits(self):
        """Test that empty person list results in zero commits."""
        from posthog.dags.person_property_reconciliation import process_persons_in_batches

        mock_cursor = MagicMock()
        commit_count = [0]

        def mock_commit():
            commit_count[0] += 1

        result = process_persons_in_batches(
            person_property_diffs=[],
            cursor=mock_cursor,
            job_id="test-job-id",
            team_id=1,
            batch_size=10,
            dry_run=False,
            backup_enabled=False,
            commit_fn=mock_commit,
        )

        assert result.total_processed == 0
        assert result.total_commits == 0
        assert commit_count[0] == 0

    def test_dry_run_no_commits(self):
        """Test that dry_run=True doesn't commit when there are no backups."""
        from posthog.dags.person_property_reconciliation import process_persons_in_batches

        person_diffs_list = [
            PersonPropertyDiffs(
                person_id="person-uuid-0",
                person_version=1,
                set_updates={
                    "prop": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), value="value_0")
                },
                set_once_updates={},
                unset_updates={},
            )
        ]

        mock_cursor = MagicMock()
        # Return None from fetchone to simulate person not found (no backup, no update)
        mock_cursor.fetchone.return_value = None

        commit_count = [0]

        def mock_commit():
            commit_count[0] += 1

        result = process_persons_in_batches(
            person_property_diffs=person_diffs_list,
            cursor=mock_cursor,
            job_id="test-job-id",
            team_id=1,
            batch_size=10,
            dry_run=True,
            backup_enabled=False,
            commit_fn=mock_commit,
        )

        # Person not found, so skipped
        assert result.total_processed == 1
        assert result.total_skipped == 1
        assert result.total_commits == 0


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
            person_version=5,
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
            person_version=3,
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
            person_version=5,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, result_data, backup_created, _skip_reason = update_person_with_version_check(
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
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, _result_data, backup_created, _skip_reason = update_person_with_version_check(
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

    def test_backup_created_false_when_conflict(self):
        """
        Regression test: backup_created should be False when ON CONFLICT DO NOTHING
        means no row was actually inserted (duplicate backup for same person/job).
        """
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

        # Track which query is being executed to return different rowcounts
        call_count = [0]
        original_execute = cursor.execute

        def execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            query = args[0] if args else ""
            if "INSERT INTO posthog_person_reconciliation_backup" in query:
                # Simulate ON CONFLICT DO NOTHING - no row inserted
                cursor.rowcount = 0
            else:
                # Person SELECT/UPDATE succeeds
                cursor.rowcount = 1
            return original_execute(*args, **kwargs)

        cursor.execute = MagicMock(side_effect=execute_side_effect)

        person_diffs = PersonPropertyDiffs(
            person_id="018d1234-5678-0000-0000-000000000001",
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="test@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        success, _result_data, backup_created, _skip_reason = update_person_with_version_check(
            cursor=cursor,
            job_id="test-job-id",
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            person_property_diffs=person_diffs,
            dry_run=False,
            backup_enabled=True,
        )

        assert success is True
        # Key assertion: backup_created should be False because rowcount was 0
        assert backup_created is False


class TestFilterEventPersonProperties:
    """Test the filter_event_person_properties function for conflict resolution."""

    def test_set_wins_when_newer_than_unset(self):
        """Test that $set wins over $unset when set timestamp is newer."""
        person_diffs = [
            PersonPropertyDiffs(
                person_id="018d1234-5678-0000-0000-000000000001",
                person_version=1,
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
                person_version=1,
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
                person_version=1,
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
                person_version=1,
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
                person_version=1,
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
                person_version=1,
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
                person_version=1,
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


class TestMergeRawPersonPropertyUpdates:
    """Test the merge_raw_person_property_updates function for windowed query accumulation."""

    def test_first_person_added_to_empty_accumulator(self):
        """Test that first person updates are added directly to empty accumulator."""
        accumulated: dict[str, RawPersonPropertyUpdates] = {}
        new_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        merge_raw_person_property_updates(accumulated, new_updates)

        assert "person-1" in accumulated
        assert accumulated["person-1"].set_updates["email"].value == "test@example.com"

    def test_set_newer_timestamp_replaces_older(self):
        """Test that $set with newer timestamp replaces older value."""
        accumulated: dict[str, RawPersonPropertyUpdates] = {
            "person-1": RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "old@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        }
        new_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC), "new@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        merge_raw_person_property_updates(accumulated, new_updates)

        assert accumulated["person-1"].set_updates["email"].value == "new@example.com"

    def test_set_once_earlier_timestamp_wins(self):
        """Test that $set_once with earlier timestamp wins (first-writer-wins)."""
        accumulated: dict[str, RawPersonPropertyUpdates] = {
            "person-1": RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={
                    "signup_source": PropertyValue(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC), "late-source")
                },
                unset_updates={},
            )
        }
        new_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={
                    "signup_source": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "early-source")
                },
                unset_updates={},
            )
        ]

        merge_raw_person_property_updates(accumulated, new_updates)

        assert accumulated["person-1"].set_once_updates["signup_source"].value == "early-source"

    def test_set_and_unset_both_retained_for_downstream_filtering(self):
        """Test that both $set and $unset are retained for downstream conflict resolution."""
        accumulated: dict[str, RawPersonPropertyUpdates] = {
            "person-1": RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        }
        new_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={},
                unset_updates={"email": PropertyValue(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC), None)},
            )
        ]

        merge_raw_person_property_updates(accumulated, new_updates)

        assert "email" in accumulated["person-1"].set_updates
        assert "email" in accumulated["person-1"].unset_updates

    def test_unset_and_set_both_retained_for_downstream_filtering(self):
        """Test that both $unset and $set are retained for downstream conflict resolution."""
        accumulated: dict[str, RawPersonPropertyUpdates] = {
            "person-1": RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={},
                unset_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), None)},
            )
        }
        new_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        merge_raw_person_property_updates(accumulated, new_updates)

        assert "email" in accumulated["person-1"].set_updates
        assert "email" in accumulated["person-1"].unset_updates

    def test_multiple_persons_merged_independently(self):
        """Test that multiple persons are merged independently."""
        accumulated: dict[str, RawPersonPropertyUpdates] = {
            "person-1": RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"key1": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "value1")},
                set_once_updates={},
                unset_updates={},
            )
        }
        new_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"key1": PropertyValue(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC), "value1-updated")},
                set_once_updates={},
                unset_updates={},
            ),
            RawPersonPropertyUpdates(
                person_id="person-2",
                set_updates={"key2": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "value2")},
                set_once_updates={},
                unset_updates={},
            ),
        ]

        merge_raw_person_property_updates(accumulated, new_updates)

        assert len(accumulated) == 2
        assert accumulated["person-1"].set_updates["key1"].value == "value1-updated"
        assert accumulated["person-2"].set_updates["key2"].value == "value2"

    def test_cross_operation_conflict_resolved_by_downstream_filter(self):
        """Verify set/unset conflicts from different windows are correctly resolved downstream.

        This test documents the intentional design: merge_raw_person_property_updates
        retains both operations, and filter_event_person_properties resolves conflicts.
        This matches the non-windowed CH query path behavior.
        """
        accumulated: dict[str, RawPersonPropertyUpdates] = {}

        # Simulate window 1: set(email) at t=12:00
        window1 = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]
        merge_raw_person_property_updates(accumulated, window1)

        # Simulate window 2: unset(email) at t=13:00
        window2 = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={},
                unset_updates={"email": PropertyValue(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC), None)},
            )
        ]
        merge_raw_person_property_updates(accumulated, window2)

        # After merge: both operations retained (no cross-map resolution in merge)
        assert "email" in accumulated["person-1"].set_updates
        assert "email" in accumulated["person-1"].unset_updates

        # Convert to PersonPropertyDiffs (simulating what compare_raw_updates_with_person_state returns)
        diffs = [
            PersonPropertyDiffs(
                person_id="person-1",
                person_version=1,
                set_updates=accumulated["person-1"].set_updates,
                set_once_updates=accumulated["person-1"].set_once_updates,
                unset_updates=accumulated["person-1"].unset_updates,
            )
        ]

        # After filter_event_person_properties: unset wins (newer timestamp)
        result = filter_event_person_properties(diffs)
        assert len(result) == 1
        assert "email" not in result[0].set_updates
        assert "email" in result[0].unset_updates


class TestCompareRawUpdatesWithPersonState:
    """Test the compare_raw_updates_with_person_state function for windowed query flow.

    This function compares merged raw event updates against current person state in ClickHouse.
    It filters to only return actual differences that need to be applied.
    """

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_empty_raw_updates_returns_empty(self, mock_sync_execute):
        """Test that empty raw_updates returns empty result without querying CH."""
        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=[])

        assert result == []
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_person_not_found_excluded_from_results(self, mock_sync_execute):
        """Test that persons not found in CH are excluded from results."""
        mock_sync_execute.return_value = []  # No person found

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert result == []

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_set_key_exists_value_differs_included(self, mock_sync_execute):
        """Test that $set is included when key exists in person AND value differs."""
        mock_sync_execute.return_value = [("person-1", '{"email": "old@example.com"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "new@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert len(result) == 1
        assert "email" in result[0].set_updates
        assert result[0].set_updates["email"].value == "new@example.com"

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_set_key_exists_value_same_excluded(self, mock_sync_execute):
        """Test that $set is excluded when key exists but value is the same."""
        mock_sync_execute.return_value = [("person-1", '{"email": "same@example.com"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "same@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert result == []

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_set_key_not_exists_excluded(self, mock_sync_execute):
        """Test that $set is excluded when key does NOT exist in person properties."""
        mock_sync_execute.return_value = [("person-1", '{"other_key": "value"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert result == []

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_set_once_key_not_exists_included(self, mock_sync_execute):
        """Test that $set_once is included when key does NOT exist in person."""
        mock_sync_execute.return_value = [("person-1", '{"other_key": "value"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={"referrer": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "google.com")},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert len(result) == 1
        assert "referrer" in result[0].set_once_updates
        assert result[0].set_once_updates["referrer"].value == "google.com"

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_set_once_key_exists_excluded(self, mock_sync_execute):
        """Test that $set_once is excluded when key already exists in person."""
        mock_sync_execute.return_value = [("person-1", '{"referrer": "existing.com"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={"referrer": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "new.com")},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert result == []

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_unset_key_exists_included(self, mock_sync_execute):
        """Test that $unset is included when key exists in person."""
        mock_sync_execute.return_value = [("person-1", '{"email": "test@example.com"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={},
                unset_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), None)},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert len(result) == 1
        assert "email" in result[0].unset_updates

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_unset_key_not_exists_excluded(self, mock_sync_execute):
        """Test that $unset is excluded when key does NOT exist in person."""
        mock_sync_execute.return_value = [("person-1", '{"other_key": "value"}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={},
                set_once_updates={},
                unset_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), None)},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert result == []

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_multiple_persons_processed_independently(self, mock_sync_execute):
        """Test that multiple persons are processed independently."""
        mock_sync_execute.return_value = [
            ("person-1", '{"email": "old1@example.com"}', 5),
            ("person-2", "{}", 3),  # Empty properties
        ]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "new1@example.com")},
                set_once_updates={},
                unset_updates={},
            ),
            RawPersonPropertyUpdates(
                person_id="person-2",
                set_updates={},
                set_once_updates={"source": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "organic")},
                unset_updates={},
            ),
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert len(result) == 2
        # Person 1: $set included (key exists, value differs)
        p1 = next(r for r in result if r.person_id == "person-1")
        assert "email" in p1.set_updates
        # Person 2: $set_once included (key doesn't exist)
        p2 = next(r for r in result if r.person_id == "person-2")
        assert "source" in p2.set_once_updates

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_person_version_propagated_correctly(self, mock_sync_execute):
        """Test that person_version from CH is propagated to PersonPropertyDiffs."""
        mock_sync_execute.return_value = [
            ("person-1", '{"email": "old@example.com"}', 42)  # version=42
        ]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "new@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        assert len(result) == 1
        assert result[0].person_version == 42

    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_type_coercion_equality(self, mock_sync_execute):
        """Test that Python type coercion treats 123 and 123.0 as equal.

        This documents the semantic comparison behavior: the windowed path uses
        Python object comparison, so numerically equivalent values like 123 (int)
        and 123.0 (float) are considered equal. This differs from the non-windowed
        SQL path which compares raw JSON strings.

        The Python approach is preferable for reconciliation as it avoids
        unnecessary updates when values are semantically equivalent.
        """
        # Person has integer 123, event sets float 123.0
        mock_sync_execute.return_value = [("person-1", '{"count": 123}', 5)]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id="person-1",
                set_updates={"count": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), 123.0)},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        # 123 == 123.0 in Python, so no diff is generated
        assert result == []

    @patch("posthog.dags.person_property_reconciliation.PERSON_STATE_BATCH_SIZE", 2)
    @patch("posthog.dags.person_property_reconciliation.sync_execute")
    def test_batches_large_person_lists(self, mock_sync_execute):
        """Test that large person lists are batched to avoid query size limits.

        When there are more persons than PERSON_STATE_BATCH_SIZE, the function
        should split the queries into multiple batches and aggregate results.
        """
        # With batch size of 2, 5 persons should result in 3 batches
        mock_sync_execute.side_effect = [
            # Batch 1: persons 1-2
            [
                ("person-1", '{"email": "old1@example.com"}', 5),
                ("person-2", '{"email": "old2@example.com"}', 6),
            ],
            # Batch 2: persons 3-4
            [
                ("person-3", '{"email": "old3@example.com"}', 7),
                ("person-4", "{}", 8),  # Empty properties
            ],
            # Batch 3: person 5
            [
                ("person-5", '{"email": "old5@example.com"}', 9),
            ],
        ]

        raw_updates = [
            RawPersonPropertyUpdates(
                person_id=f"person-{i}",
                set_updates={
                    "email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), f"new{i}@example.com")
                },
                set_once_updates={},
                unset_updates={},
            )
            for i in range(1, 6)
        ]

        result = compare_raw_updates_with_person_state(team_id=1, raw_updates=raw_updates)

        # Should have called sync_execute 3 times (one per batch)
        assert mock_sync_execute.call_count == 3

        # Should return 4 results (person-4 has empty properties so $set is excluded)
        assert len(result) == 4
        result_ids = {r.person_id for r in result}
        assert result_ids == {"person-1", "person-2", "person-3", "person-5"}


class TestGetPersonPropertyUpdatesWindowed:
    """Test the get_person_property_updates_windowed function."""

    @patch("posthog.dags.person_property_reconciliation.get_person_property_updates_from_clickhouse")
    def test_window_seconds_zero_calls_original_once(self, mock_get_updates):
        """Test that window_seconds=0 calls original function once."""
        mock_get_updates.return_value = [
            PersonPropertyDiffs(
                person_id="person-1",
                person_version=1,
                set_updates={"email": PropertyValue(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC), "test@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = get_person_property_updates_windowed(
            team_id=1,
            bug_window_start="2024-01-01 00:00:00",
            window_seconds=0,
        )

        mock_get_updates.assert_called_once_with(1, "2024-01-01 00:00:00")
        assert len(result) == 1

    @patch("posthog.dags.person_property_reconciliation.get_person_property_updates_from_clickhouse")
    def test_window_seconds_negative_calls_original_once(self, mock_get_updates):
        """Test that negative window_seconds calls original function once."""
        mock_get_updates.return_value = []

        get_person_property_updates_windowed(
            team_id=1,
            bug_window_start="2024-01-01 00:00:00",
            window_seconds=-100,
        )

        mock_get_updates.assert_called_once_with(1, "2024-01-01 00:00:00")

    @patch("posthog.dags.person_property_reconciliation.compare_raw_updates_with_person_state")
    @patch("posthog.dags.person_property_reconciliation.datetime")
    @patch("posthog.dags.person_property_reconciliation.get_raw_person_property_updates_from_clickhouse")
    def test_window_seconds_positive_creates_windows(self, mock_get_raw, mock_datetime, mock_compare):
        """Test that positive window_seconds creates multiple query windows."""
        mock_now = datetime(2024, 1, 1, 2, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime
        mock_get_raw.return_value = []
        mock_compare.return_value = []

        get_person_property_updates_windowed(
            team_id=1,
            bug_window_start="2024-01-01 00:00:00",
            window_seconds=3600,  # 1 hour windows
        )

        # Should have 2 calls: 00:00-01:00 and 01:00-02:00
        assert mock_get_raw.call_count == 2
        calls = mock_get_raw.call_args_list
        assert calls[0][0] == (1, "2024-01-01 00:00:00", "2024-01-01 01:00:00")
        assert calls[1][0] == (1, "2024-01-01 01:00:00", "2024-01-01 02:00:00")
        # compare_raw_updates_with_person_state should be called once at the end
        mock_compare.assert_called_once()

    @patch("posthog.dags.person_property_reconciliation.compare_raw_updates_with_person_state")
    @patch("posthog.dags.person_property_reconciliation.datetime")
    @patch("posthog.dags.person_property_reconciliation.get_raw_person_property_updates_from_clickhouse")
    def test_window_merges_results_across_windows(self, mock_get_raw, mock_datetime, mock_compare):
        """Test that results are properly merged across windows."""
        mock_now = datetime(2024, 1, 1, 2, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = mock_now
        mock_datetime.strptime = datetime.strptime

        # First window returns one update, second window returns a newer update for same key
        mock_get_raw.side_effect = [
            [
                RawPersonPropertyUpdates(
                    person_id="person-1",
                    set_updates={"email": PropertyValue(datetime(2024, 1, 1, 0, 30, 0, tzinfo=UTC), "old@example.com")},
                    set_once_updates={},
                    unset_updates={},
                )
            ],
            [
                RawPersonPropertyUpdates(
                    person_id="person-1",
                    set_updates={"email": PropertyValue(datetime(2024, 1, 1, 1, 30, 0, tzinfo=UTC), "new@example.com")},
                    set_once_updates={},
                    unset_updates={},
                )
            ],
        ]

        # Mock the comparison to return the expected result
        mock_compare.return_value = [
            PersonPropertyDiffs(
                person_id="person-1",
                person_version=1,
                set_updates={"email": PropertyValue(datetime(2024, 1, 1, 1, 30, 0, tzinfo=UTC), "new@example.com")},
                set_once_updates={},
                unset_updates={},
            )
        ]

        result = get_person_property_updates_windowed(
            team_id=1,
            bug_window_start="2024-01-01 00:00:00",
            window_seconds=3600,
        )

        assert len(result) == 1
        assert result[0].set_updates["email"].value == "new@example.com"

        # Verify compare was called with merged raw updates (newer email value)
        compare_call_args = mock_compare.call_args[0]
        assert compare_call_args[0] == 1  # team_id
        raw_updates_list = compare_call_args[1]
        assert len(raw_updates_list) == 1
        assert raw_updates_list[0].set_updates["email"].value == "new@example.com"


class TestParseFormatChTimestamp:
    """Test the parse_ch_timestamp and format_ch_timestamp helper functions."""

    def test_parse_ch_timestamp(self):
        """Test parsing ClickHouse timestamp string to datetime."""
        result = parse_ch_timestamp("2024-01-15 12:30:45")
        assert result == datetime(2024, 1, 15, 12, 30, 45, tzinfo=UTC)
        assert result.tzinfo == UTC

    def test_format_ch_timestamp(self):
        """Test formatting datetime to ClickHouse timestamp string."""
        dt = datetime(2024, 1, 15, 12, 30, 45, tzinfo=UTC)
        result = format_ch_timestamp(dt)
        assert result == "2024-01-15 12:30:45"

    def test_roundtrip(self):
        """Test that parse and format are inverse operations."""
        original = "2024-06-20 08:15:30"
        parsed = parse_ch_timestamp(original)
        formatted = format_ch_timestamp(parsed)
        assert formatted == original

    def test_format_ch_timestamp_converts_to_utc(self):
        """Test that non-UTC datetime is converted to UTC before formatting."""
        from datetime import timedelta, timezone

        est = timezone(timedelta(hours=-5))
        dt_est = datetime(2024, 1, 15, 12, 30, 45, tzinfo=est)  # 12:30 EST = 17:30 UTC
        result = format_ch_timestamp(dt_est)
        assert result == "2024-01-15 17:30:45"


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
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime.now(), value="test@example.com")},
            set_once_updates={"referrer": PropertyValue(timestamp=datetime.now(), value="google.com")},
            unset_updates={"old_field": PropertyValue(timestamp=datetime.now(), value=None)},
        )

        assert person_diffs.person_id == "018d1234-5678-0000-0000-000000000001"
        assert person_diffs.person_version == 1
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

    def test_set_with_various_json_types(self, cluster: ClickhouseCluster):
        """Test $set with various JSON value types: string, number, boolean, null, array, object."""
        team_id = 99906
        person_id = UUID("66666666-6666-6666-6666-000000000006")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        # Event with various JSON types in $set
        # Note: null values are filtered out in the query (use $unset for removal)
        events = [
            (
                team_id,
                "distinct_id_6",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set": {
                            "string_prop": "hello world",
                            "int_prop": 42,
                            "float_prop": 3.14159,
                            "bool_true_prop": True,
                            "bool_false_prop": False,
                            "array_prop": [1, "two", True],
                            "object_prop": {"nested": "value", "count": 123},
                        }
                    }
                ),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with different values for all properties (so set_diff includes them)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps(
                    {
                        "string_prop": "old",
                        "int_prop": 0,
                        "float_prop": 0.0,
                        "bool_true_prop": False,
                        "bool_false_prop": True,
                        "array_prop": [],
                        "object_prop": {},
                    }
                ),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}

        # String
        assert updates["string_prop"] == "hello world"
        assert isinstance(updates["string_prop"], str)

        # Integer
        assert updates["int_prop"] == 42
        assert isinstance(updates["int_prop"], int)

        # Float
        assert updates["float_prop"] == 3.14159
        assert isinstance(updates["float_prop"], float)

        # Boolean true
        assert updates["bool_true_prop"] is True
        assert isinstance(updates["bool_true_prop"], bool)

        # Boolean false
        assert updates["bool_false_prop"] is False
        assert isinstance(updates["bool_false_prop"], bool)

        # Array
        assert updates["array_prop"] == [1, "two", True]
        assert isinstance(updates["array_prop"], list)

        # Object
        assert updates["object_prop"] == {"nested": "value", "count": 123}
        assert isinstance(updates["object_prop"], dict)

    def test_set_with_null_value_is_filtered_out(self, cluster: ClickhouseCluster):
        """Test that $set with null value is filtered out (use $unset for removal)."""
        team_id = 99907
        person_id = UUID("77777777-7777-7777-7777-000000000007")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        # Event with null value in $set - should be filtered out
        events = [
            (
                team_id,
                "distinct_id_7",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set": {
                            "keep_prop": "value",
                            "null_prop": None,  # This should be filtered out
                        }
                    }
                ),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with different values (so set_diff includes them)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps(
                    {
                        "keep_prop": "old_value",
                        "null_prop": "existing_value",  # This exists, but $set null should NOT update it
                    }
                ),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}

        # keep_prop should be included
        assert "keep_prop" in updates
        assert updates["keep_prop"] == "value"

        # null_prop should NOT be included (filtered out because value is null)
        assert "null_prop" not in updates, (
            "$set with null value should be filtered out. Use $unset to remove properties."
        )

    def test_set_once_with_various_json_types(self, cluster: ClickhouseCluster):
        """Test $set_once with various JSON value types: string, number, boolean, array, object."""
        team_id = 99908
        person_id = UUID("88888888-8888-8888-8888-000000000008")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        # Event with various JSON types in $set_once
        # Note: null values are filtered out in the query
        events = [
            (
                team_id,
                "distinct_id_8",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set_once": {
                            "string_prop": "hello world",
                            "int_prop": 42,
                            "float_prop": 3.14159,
                            "bool_true_prop": True,
                            "bool_false_prop": False,
                            "array_prop": [1, "two", True],
                            "object_prop": {"nested": "value", "count": 123},
                        }
                    }
                ),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person WITHOUT these properties (so set_once_diff includes them)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"other_prop": "value"}),  # None of the $set_once keys exist
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_once_updates.items()}

        # String
        assert updates["string_prop"] == "hello world"
        assert isinstance(updates["string_prop"], str)

        # Integer
        assert updates["int_prop"] == 42
        assert isinstance(updates["int_prop"], int)

        # Float
        assert updates["float_prop"] == 3.14159
        assert isinstance(updates["float_prop"], float)

        # Boolean true
        assert updates["bool_true_prop"] is True
        assert isinstance(updates["bool_true_prop"], bool)

        # Boolean false
        assert updates["bool_false_prop"] is False
        assert isinstance(updates["bool_false_prop"], bool)

        # Array
        assert updates["array_prop"] == [1, "two", True]
        assert isinstance(updates["array_prop"], list)

        # Object
        assert updates["object_prop"] == {"nested": "value", "count": 123}
        assert isinstance(updates["object_prop"], dict)

    def test_set_once_with_null_value_is_filtered_out(self, cluster: ClickhouseCluster):
        """Test that $set_once with null value is filtered out."""
        team_id = 99909
        person_id = UUID("99999999-9999-9999-9999-000000000009")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        # Event with null value in $set_once - should be filtered out
        events = [
            (
                team_id,
                "distinct_id_9",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set_once": {
                            "keep_prop": "value",
                            "null_prop": None,  # This should be filtered out
                        }
                    }
                ),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person without these properties (so set_once_diff would include them if not filtered)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"other_prop": "value"}),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_once_updates.items()}

        # keep_prop should be included
        assert "keep_prop" in updates
        assert updates["keep_prop"] == "value"

        # null_prop should NOT be included (filtered out because value is null)
        assert "null_prop" not in updates, "$set_once with null value should be filtered out."

    # ==================== Person Merge Tests ====================

    def test_person_merge_uses_override_person_id(self, cluster: ClickhouseCluster):
        """
        When a distinct_id has an override in person_distinct_id_overrides,
        events should be attributed to the override person_id, not the original.

        This test verifies that:
        1. Events with an overridden distinct_id are attributed to the merged person
        2. The $set property update is correctly associated with the merged person
        """
        team_id = 99910
        original_person_id = UUID("aaaa0000-0000-0000-0000-000000000001")
        merged_person_id = UUID("aaaa0000-0000-0000-0000-000000000002")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        # Event with original person_id, but distinct_id will be overridden
        # Using $set on a property that EXISTS in the merged person but has DIFFERENT value
        events = [
            (
                team_id,
                "merged_distinct_id",
                original_person_id,  # Original person_id in event
                event_ts,
                json.dumps({"$set": {"existing": "new_value"}}),  # Update existing property
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert override: merged_distinct_id -> merged_person_id
        # Must include _timestamp for the data to be visible
        override_data = [
            (
                team_id,
                "merged_distinct_id",
                merged_person_id,  # Override to this person
                now - timedelta(days=4),  # _timestamp - must be provided
                1,  # version
                0,  # is_deleted = false
            ),
        ]

        def insert_override(client):
            client.execute(
                """INSERT INTO person_distinct_id_overrides
                (team_id, distinct_id, person_id, _timestamp, version, is_deleted)
                VALUES""",
                override_data,
            )

        cluster.any_host(insert_override).result()

        # Insert the MERGED person (not the original)
        # Has "existing" property with old value that event will update
        person_data = [
            (
                team_id,
                merged_person_id,
                json.dumps({"existing": "old_value"}),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should get results for merged_person_id, not original_person_id
        assert len(results) == 1
        assert results[0].person_id == str(merged_person_id)

        updates = {key: pv.value for key, pv in results[0].set_updates.items()}
        assert "existing" in updates
        assert updates["existing"] == "new_value"

    def test_multiple_distinct_ids_same_person(self, cluster: ClickhouseCluster):
        """
        Events from multiple distinct_ids that map to the same person
        should be aggregated together.
        """
        team_id = 99911
        person_id = UUID("bbbb0000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        earlier_ts = now - timedelta(days=5)
        later_ts = now - timedelta(days=2)

        # Two events from different distinct_ids, same person
        events = [
            (team_id, "distinct_id_A", person_id, earlier_ts, json.dumps({"$set": {"name": "First"}})),
            (team_id, "distinct_id_B", person_id, later_ts, json.dumps({"$set": {"name": "Latest"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        person_data = [(team_id, person_id, json.dumps({"name": "Old"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should have one result with the latest value (aggregated from both distinct_ids)
        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}
        assert updates["name"] == "Latest"

    def test_deleted_override_not_used(self, cluster: ClickhouseCluster):
        """
        When an override has is_deleted=1, it should not be used.
        Events should use the original person_id from the event.
        """
        team_id = 99920
        original_person_id = UUID("eeee0000-0000-0000-0000-000000000001")
        merged_person_id = UUID("eeee0000-0000-0000-0000-000000000002")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (
                team_id,
                "deleted_override_distinct",
                original_person_id,
                event_ts,
                json.dumps({"$set": {"prop": "value"}}),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert a DELETED override (is_deleted=1)
        override_data = [
            (
                team_id,
                "deleted_override_distinct",
                merged_person_id,
                now - timedelta(days=4),  # _timestamp
                1,  # version
                1,  # is_deleted = TRUE
            ),
        ]

        def insert_override(client):
            client.execute(
                """INSERT INTO person_distinct_id_overrides
                (team_id, distinct_id, person_id, _timestamp, version, is_deleted)
                VALUES""",
                override_data,
            )

        cluster.any_host(insert_override).result()

        # Insert the ORIGINAL person (not the merged one)
        person_data = [(team_id, original_person_id, json.dumps({"prop": "old"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Since override is deleted, should use original_person_id
        assert len(results) == 1
        assert results[0].person_id == str(original_person_id)

    def test_override_version_ordering(self, cluster: ClickhouseCluster):
        """
        When multiple override versions exist, the highest version should win.
        """
        team_id = 99921
        original_person_id = UUID("ffff0000-0000-0000-0000-000000000001")
        first_merged_person_id = UUID("ffff0000-0000-0000-0000-000000000002")
        final_merged_person_id = UUID("ffff0000-0000-0000-0000-000000000003")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (
                team_id,
                "multi_version_distinct",
                original_person_id,
                event_ts,
                json.dumps({"$set": {"prop": "value"}}),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert multiple override versions - version 2 should win
        override_data = [
            (team_id, "multi_version_distinct", first_merged_person_id, now - timedelta(days=5), 1, 0),
            (team_id, "multi_version_distinct", final_merged_person_id, now - timedelta(days=4), 2, 0),
        ]

        def insert_override(client):
            client.execute(
                """INSERT INTO person_distinct_id_overrides
                (team_id, distinct_id, person_id, _timestamp, version, is_deleted)
                VALUES""",
                override_data,
            )

        cluster.any_host(insert_override).result()

        # Insert the FINAL merged person
        person_data = [(team_id, final_merged_person_id, json.dumps({"prop": "old"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should use final_merged_person_id (version 2)
        assert len(results) == 1
        assert results[0].person_id == str(final_merged_person_id)

    def test_deleted_person_filtered_out(self, cluster: ClickhouseCluster):
        """
        Persons with is_deleted=1 in the person table should be filtered out.
        There's no point updating properties on a deleted person.
        """
        team_id = 99922
        person_id = UUID("11110000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (team_id, "deleted_person_distinct", person_id, event_ts, json.dumps({"$set": {"prop": "new_value"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert a DELETED person (is_deleted=1)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"prop": "old_value"}),
                1,  # version
                1,  # is_deleted = TRUE
                now - timedelta(days=8),  # _timestamp
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, is_deleted, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Deleted persons should NOT be processed
        assert len(results) == 0

    def test_person_multiple_versions_uses_latest(self, cluster: ClickhouseCluster):
        """
        When a person has multiple versions in CH, argMax(properties, version)
        should select the properties from the highest version.
        """
        team_id = 99923
        person_id = UUID("22220000-0000-0000-0000-000000000002")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (
                team_id,
                "multi_version_person_distinct",
                person_id,
                event_ts,
                json.dumps({"$set": {"prop": "event_value"}}),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert multiple versions of the same person
        # Version 2 has different properties than version 1
        person_data = [
            (team_id, person_id, json.dumps({"prop": "v1_value"}), 1, now - timedelta(days=8)),
            (team_id, person_id, json.dumps({"prop": "v2_value"}), 2, now - timedelta(days=7)),
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should compare against v2_value (latest version)
        # Event has "event_value", person v2 has "v2_value" - different, so should be in diff
        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}
        assert updates["prop"] == "event_value"

    # ==================== Same Key Operation Tests ====================

    def test_set_and_set_once_on_same_key(self, cluster: ClickhouseCluster):
        """
        When $set and $set_once both target the same key, both should be returned
        as separate operations (query doesn't merge them, Python logic handles precedence).
        """
        team_id = 99912
        person_id = UUID("cccc0000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        set_once_ts = now - timedelta(days=5)
        set_ts = now - timedelta(days=2)

        events = [
            (team_id, "distinct_1", person_id, set_once_ts, json.dumps({"$set_once": {"email": "first@example.com"}})),
            (team_id, "distinct_1", person_id, set_ts, json.dumps({"$set": {"email": "latest@example.com"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person WITHOUT email (so set_once_diff includes it)
        # Person WITH different email for set_diff
        # Actually, to get both in results, we need person to NOT have email (for set_once)
        # and have a different email (for set). That's contradictory.
        # Let's test with person having a different email - set_diff should include it,
        # set_once_diff should NOT (key exists).
        person_data = [(team_id, person_id, json.dumps({"email": "old@example.com"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1

        # $set should be included (value differs from person)
        assert len(results[0].set_updates) == 1
        assert "email" in results[0].set_updates
        assert results[0].set_updates["email"].value == "latest@example.com"

        # $set_once should NOT be included (key already exists in person)
        assert len(results[0].set_once_updates) == 0

    # ==================== Diff Filtering Tests ====================

    def test_set_with_same_value_not_in_diff(self, cluster: ClickhouseCluster):
        """
        When $set value equals current person property value,
        it should NOT be in set_diff (no change needed).
        """
        team_id = 99913
        person_id = UUID("dddd0000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, event_ts, json.dumps({"$set": {"name": "Same Value"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with SAME value
        person_data = [(team_id, person_id, json.dumps({"name": "Same Value"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should be empty - no diff when values are the same
        assert len(results) == 0

    def test_set_on_missing_property_not_in_diff(self, cluster: ClickhouseCluster):
        """
        When $set targets a property that doesn't exist in person,
        it should NOT be in set_diff (set_diff only updates existing different values).
        """
        team_id = 99914
        person_id = UUID("eeee0000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, event_ts, json.dumps({"$set": {"new_prop": "value"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person WITHOUT new_prop
        person_data = [(team_id, person_id, json.dumps({"other_prop": "value"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should be empty - set_diff doesn't include missing properties
        assert len(results) == 0

    def test_unset_on_missing_property_not_in_diff(self, cluster: ClickhouseCluster):
        """
        When $unset targets a property that doesn't exist in person,
        it should NOT be in unset_diff.
        """
        team_id = 99915
        person_id = UUID("ffff0000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, event_ts, json.dumps({"$unset": ["nonexistent_prop"]})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person WITHOUT nonexistent_prop
        person_data = [(team_id, person_id, json.dumps({"other_prop": "value"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should be empty - unset_diff doesn't include missing properties
        assert len(results) == 0

    # ==================== Empty Value Tests ====================

    def test_empty_set_object_no_results(self, cluster: ClickhouseCluster):
        """Empty $set object should not cause issues or return results."""
        team_id = 99916
        person_id = UUID("11110000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, event_ts, json.dumps({"$set": {}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        person_data = [(team_id, person_id, json.dumps({"prop": "value"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Empty $set should produce no results
        assert len(results) == 0

    def test_empty_string_value_is_valid(self, cluster: ClickhouseCluster):
        """Empty string is a valid value in $set - different from null."""
        team_id = 99917
        person_id = UUID("22220000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (
                team_id,
                "distinct_1",
                person_id,
                event_ts,
                json.dumps({"$set": {"empty_prop": "", "valid_prop": "value"}}),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        person_data = [
            (team_id, person_id, json.dumps({"empty_prop": "old", "valid_prop": "old"}), 1, now - timedelta(days=8))
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}

        # valid_prop should be included (changed from "old" to "value")
        assert "valid_prop" in updates
        assert updates["valid_prop"] == "value"

        # empty_prop should be included - empty string is a valid value, not filtered like null
        # It changes from "old" to "" (empty string)
        assert "empty_prop" in updates
        assert updates["empty_prop"] == ""

    # ==================== Window Filtering Tests ====================

    def test_events_before_bug_window_start_filtered(self, cluster: ClickhouseCluster):
        """Events with timestamp before bug_window_start should be filtered.

        Events after bug_window_start are included (up to now()).
        """
        team_id = 99918
        person_id = UUID("33330000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=5)

        # Event BEFORE bug_window_start - should be filtered
        before_ts = now - timedelta(days=7)
        # Event AFTER bug_window_start - should be included (reads up to now())
        after_start_ts = now - timedelta(days=1)
        # Event IN window (also after bug_window_start)
        in_window_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, before_ts, json.dumps({"$set": {"before": "value"}})),
            (team_id, "distinct_1", person_id, after_start_ts, json.dumps({"$set": {"after_start": "value"}})),
            (team_id, "distinct_1", person_id, in_window_ts, json.dumps({"$set": {"in_window": "value"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"before": "old", "after_start": "old", "in_window": "old"}),
                1,
                now - timedelta(days=4),  # Person _timestamp after bug_window_start
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}

        # Events after bug_window_start should be included
        assert "in_window" in updates
        assert "after_start" in updates
        # Events before bug_window_start should NOT be included
        assert "before" not in updates

    def test_person_created_before_bug_window_with_events_after_is_included(self, cluster: ClickhouseCluster):
        """Regression test: Person created before bug_window_start with events after should be included.

        Scenario:
        - Person was created/last modified BEFORE bug_window_start (their _timestamp is old)
        - After bug_window_start, there are $set events for this person
        - These events SHOULD be included in the reconciliation

        This is important because we want to reconcile ALL persons that have property-setting
        events after bug_window_start, regardless of when the person was originally created.
        The bug window is about when the ingestion bug occurred, not when persons were created.
        """
        team_id = 99920
        person_id = UUID("55550000-0000-0000-0000-000000000002")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=5)

        # Event AFTER bug_window_start - should be included
        event_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, event_ts, json.dumps({"$set": {"email": "new@example.com"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person _timestamp BEFORE bug_window_start (person was created before the bug window)
        # but with a property that differs from the event's $set value
        person_data = [(team_id, person_id, json.dumps({"email": "old@example.com"}), 1, now - timedelta(days=10))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Person SHOULD be included because they have events after bug_window_start
        # The person's _timestamp being before bug_window_start should NOT exclude them
        assert len(results) == 1
        assert str(results[0].person_id) == str(person_id)
        assert "email" in results[0].set_updates
        assert results[0].set_updates["email"].value == "new@example.com"

    def test_timestamp_window_filtering_all_permutations(self, cluster: ClickhouseCluster):
        """Comprehensive test of all permutations of person _timestamp and event timestamp.

        Tests the matrix of:
        - Person _timestamp: BEFORE / DURING / AFTER bug window
        - Event timestamp: BEFORE / DURING / AFTER bug window

        Expected behavior:
        - Person _timestamp does NOT affect filtering (we removed that filter)
        - Events BEFORE bug_window_start are filtered out
        - Events DURING or AFTER bug_window_start are included (query uses now() as upper bound)

        So expected results:
        | Person _timestamp | Event timestamp | Included? |
        |-------------------|-----------------|-----------|
        | BEFORE            | BEFORE          | NO        |
        | BEFORE            | DURING          | YES       |
        | BEFORE            | AFTER           | YES       |
        | DURING            | BEFORE          | NO        |
        | DURING            | DURING          | YES       |
        | DURING            | AFTER           | YES       |
        | AFTER             | BEFORE          | NO        |
        | AFTER             | DURING          | YES       |
        | AFTER             | AFTER           | YES       |
        """
        # Use two teams to ensure isolation
        team_id_1 = 99950
        team_id_2 = 99951

        now = datetime.now().replace(microsecond=0)

        # Define time periods
        # Bug window is conceptually from bug_window_start to bug_window_end (for team discovery)
        # But the CH query reads from bug_window_start to now()
        bug_window_start = now - timedelta(days=10)
        _bug_window_end = now - timedelta(days=5)  # Used conceptually, not in query

        # Timestamps for each period
        ts_before = now - timedelta(days=15)  # Before bug_window_start
        ts_during = now - timedelta(days=7)  # Between bug_window_start and bug_window_end
        ts_after = now - timedelta(days=2)  # After bug_window_end but before now()

        # Create 9 persons for team 1 - all permutations
        # Format: (person_id_suffix, person_ts, event_ts, should_be_included)
        test_cases_team1 = [
            # Person _timestamp BEFORE bug_window_start
            ("001", ts_before, ts_before, False, "person_before_event_before"),
            ("002", ts_before, ts_during, True, "person_before_event_during"),
            ("003", ts_before, ts_after, True, "person_before_event_after"),
            # Person _timestamp DURING bug_window
            ("004", ts_during, ts_before, False, "person_during_event_before"),
            ("005", ts_during, ts_during, True, "person_during_event_during"),
            ("006", ts_during, ts_after, True, "person_during_event_after"),
            # Person _timestamp AFTER bug_window_end
            ("007", ts_after, ts_before, False, "person_after_event_before"),
            ("008", ts_after, ts_during, True, "person_after_event_during"),
            ("009", ts_after, ts_after, True, "person_after_event_after"),
        ]

        # Create 3 persons for team 2 - subset to verify team isolation
        test_cases_team2 = [
            ("101", ts_before, ts_during, True, "team2_person_before_event_during"),
            ("102", ts_during, ts_after, True, "team2_person_during_event_after"),
            ("103", ts_after, ts_before, False, "team2_person_after_event_before"),
        ]

        # Helper to create UUID from suffix
        def make_uuid(suffix: str) -> UUID:
            return UUID(f"99990000-0000-0000-0000-000000000{suffix}")

        # Insert events for team 1
        events_team1 = []
        for suffix, _person_ts, event_ts, _expected, prop_name in test_cases_team1:
            person_id = make_uuid(suffix)
            events_team1.append(
                (
                    team_id_1,
                    f"distinct_{suffix}",
                    person_id,
                    event_ts,
                    json.dumps({"$set": {prop_name: "new_value"}}),
                )
            )

        def insert_events_team1(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events_team1,
            )

        cluster.any_host(insert_events_team1).result()

        # Insert events for team 2
        events_team2 = []
        for suffix, _person_ts, event_ts, _expected, prop_name in test_cases_team2:
            person_id = make_uuid(suffix)
            events_team2.append(
                (
                    team_id_2,
                    f"distinct_{suffix}",
                    person_id,
                    event_ts,
                    json.dumps({"$set": {prop_name: "new_value"}}),
                )
            )

        def insert_events_team2(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events_team2,
            )

        cluster.any_host(insert_events_team2).result()

        # Insert persons for team 1 (with different property values so we get a diff)
        persons_team1 = []
        for suffix, person_ts, _event_ts, _expected, prop_name in test_cases_team1:
            person_id = make_uuid(suffix)
            persons_team1.append(
                (
                    team_id_1,
                    person_id,
                    json.dumps({prop_name: "old_value"}),
                    1,  # version
                    person_ts,  # _timestamp
                )
            )

        def insert_persons_team1(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                persons_team1,
            )

        cluster.any_host(insert_persons_team1).result()

        # Insert persons for team 2
        persons_team2 = []
        for suffix, person_ts, _event_ts, _expected, prop_name in test_cases_team2:
            person_id = make_uuid(suffix)
            persons_team2.append(
                (
                    team_id_2,
                    person_id,
                    json.dumps({prop_name: "old_value"}),
                    1,
                    person_ts,
                )
            )

        def insert_persons_team2(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                persons_team2,
            )

        cluster.any_host(insert_persons_team2).result()

        # Query for team 1
        results_team1 = get_person_property_updates_from_clickhouse(
            team_id=team_id_1,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Query for team 2
        results_team2 = get_person_property_updates_from_clickhouse(
            team_id=team_id_2,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Verify team 1 results
        result_person_ids_team1 = {str(r.person_id) for r in results_team1}
        expected_person_ids_team1 = {
            str(make_uuid(suffix))
            for suffix, _person_ts, _event_ts, expected, _prop_name in test_cases_team1
            if expected
        }

        assert result_person_ids_team1 == expected_person_ids_team1, (
            f"Team 1 mismatch.\n"
            f"Expected: {expected_person_ids_team1}\n"
            f"Got: {result_person_ids_team1}\n"
            f"Missing: {expected_person_ids_team1 - result_person_ids_team1}\n"
            f"Extra: {result_person_ids_team1 - expected_person_ids_team1}"
        )

        # Verify team 2 results
        result_person_ids_team2 = {str(r.person_id) for r in results_team2}
        expected_person_ids_team2 = {
            str(make_uuid(suffix))
            for suffix, _person_ts, _event_ts, expected, _prop_name in test_cases_team2
            if expected
        }

        assert result_person_ids_team2 == expected_person_ids_team2, (
            f"Team 2 mismatch.\nExpected: {expected_person_ids_team2}\nGot: {result_person_ids_team2}"
        )

        # Verify the property values are correct for included persons
        for result in results_team1:
            # Each person should have exactly one set_update with value "new_value"
            assert len(result.set_updates) == 1, f"Person {result.person_id} should have 1 update"
            prop_value = next(iter(result.set_updates.values()))
            assert prop_value.value == "new_value", f"Person {result.person_id} should have new_value"

        # Verify specific cases to make the test more explicit
        # Person 002: _timestamp BEFORE, event DURING → should be included
        assert str(make_uuid("002")) in result_person_ids_team1, (
            "Person with _timestamp BEFORE but event DURING should be included"
        )

        # Person 003: _timestamp BEFORE, event AFTER → should be included
        assert str(make_uuid("003")) in result_person_ids_team1, (
            "Person with _timestamp BEFORE but event AFTER should be included"
        )

        # Person 007: _timestamp AFTER, event BEFORE → should NOT be included
        assert str(make_uuid("007")) not in result_person_ids_team1, (
            "Person with event BEFORE bug_window_start should NOT be included"
        )

        # Person 001: _timestamp BEFORE, event BEFORE → should NOT be included
        assert str(make_uuid("001")) not in result_person_ids_team1, (
            "Person with event BEFORE bug_window_start should NOT be included"
        )

    # ==================== Edge Case Tests ====================

    def test_same_timestamp_deterministic(self, cluster: ClickhouseCluster):
        """
        When multiple events have exact same timestamp,
        argMax/argMin should still produce deterministic results.
        """
        team_id = 99924
        person_id = UUID("55550000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        # Same timestamp for both events
        same_ts = now - timedelta(days=3)

        events = [
            (team_id, "distinct_1", person_id, same_ts, json.dumps({"$set": {"name": "Value A"}})),
            (team_id, "distinct_2", person_id, same_ts, json.dumps({"$set": {"name": "Value B"}})),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        person_data = [(team_id, person_id, json.dumps({"name": "Old"}), 1, now - timedelta(days=8))]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Should get exactly one result with one of the values
        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}
        assert updates["name"] in ["Value A", "Value B"]

    def test_special_characters_in_property_keys(self, cluster: ClickhouseCluster):
        """Property keys with special characters should work correctly."""
        team_id = 99925
        person_id = UUID("66660000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        events = [
            (
                team_id,
                "distinct_1",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set": {
                            "key with spaces": "value1",
                            "key.with.dots": "value2",
                            "key-with-dashes": "value3",
                            "key_with_underscores": "value4",
                            "キー": "unicode value",  # Japanese "key"
                        }
                    }
                ),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with different values for these keys
        person_data = [
            (
                team_id,
                person_id,
                json.dumps(
                    {
                        "key with spaces": "old1",
                        "key.with.dots": "old2",
                        "key-with-dashes": "old3",
                        "key_with_underscores": "old4",
                        "キー": "old unicode",
                    }
                ),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        updates = {key: pv.value for key, pv in results[0].set_updates.items()}

        assert updates["key with spaces"] == "value1"
        assert updates["key.with.dots"] == "value2"
        assert updates["key-with-dashes"] == "value3"
        assert updates["key_with_underscores"] == "value4"
        assert updates["キー"] == "unicode value"

    def test_filtered_properties_are_excluded(self, cluster: ClickhouseCluster):
        """Properties in FILTERED_PERSON_UPDATE_PROPERTIES should be excluded from results.

        These are high-frequency properties like $current_url that change often
        but aren't valuable enough to trigger person updates.
        """
        team_id = 99926
        person_id = UUID("77770000-0000-0000-0000-000000000001")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)

        event_ts = now - timedelta(days=3)

        # Event with both filtered and non-filtered properties
        events = [
            (
                team_id,
                "distinct_1",
                person_id,
                event_ts,
                json.dumps(
                    {
                        "$set": {
                            # Filtered properties - should NOT appear in results
                            "$current_url": "https://example.com/page",
                            "$pathname": "/page",
                            "$browser": "Chrome",
                            "$os": "Mac OS X",
                            # Non-filtered properties - SHOULD appear in results
                            "email": "test@example.com",
                            "name": "Test User",
                        },
                        "$set_once": {
                            # Filtered
                            "$referring_domain": "google.com",
                            # Non-filtered
                            "initial_campaign": "summer_sale",
                        },
                    }
                ),
            ),
        ]

        def insert_events(client):
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person with different values so diffs are detected
        person_data = [
            (
                team_id,
                person_id,
                json.dumps(
                    {
                        "$current_url": "https://example.com/old",
                        "email": "old@example.com",
                        "name": "Old Name",
                    }
                ),
                1,
                now - timedelta(days=8),
            )
        ]

        def insert_person(client):
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(results) == 1
        person_diffs = results[0]

        # Non-filtered properties should be present
        set_keys = set(person_diffs.set_updates.keys())
        set_once_keys = set(person_diffs.set_once_updates.keys())

        assert "email" in set_keys, "Non-filtered property 'email' should be in results"
        assert "name" in set_keys, "Non-filtered property 'name' should be in results"
        assert "initial_campaign" in set_once_keys, "Non-filtered property 'initial_campaign' should be in results"

        # Filtered properties should NOT be present
        assert "$current_url" not in set_keys, "Filtered property '$current_url' should NOT be in results"
        assert "$pathname" not in set_keys, "Filtered property '$pathname' should NOT be in results"
        assert "$browser" not in set_keys, "Filtered property '$browser' should NOT be in results"
        assert "$os" not in set_keys, "Filtered property '$os' should NOT be in results"
        assert "$referring_domain" not in set_once_keys, (
            "Filtered property '$referring_domain' should NOT be in results"
        )

    def test_windowed_query_produces_same_result_as_single_query(self, cluster: ClickhouseCluster):
        """
        Integration test: windowed queries should produce equivalent results to single query.

        This test inserts events spread across multiple time windows with $set, $set_once,
        and $unset operations, then verifies that:
        1. A single query returns the expected merged result
        2. A windowed query (multiple smaller queries merged) returns the same result

        The CH query behavior:
        - $set: only returns keys that EXIST in person AND have different values
        - $set_once: only returns keys that DON'T exist in person
        - $unset: only returns keys that EXIST in person
        """
        team_id = 99930
        person_id = UUID("11111111-1111-1111-1111-000000000030")
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(hours=6)

        # Events spread across 6 hours (will use 2-hour windows = 3 windows)
        # Window 1: hour 0-2
        #   - $set email to "first@example.com" at hour 1
        #   - $set name to "Name1" at hour 1
        #   - $set_once signup_source to "source1" at hour 1
        # Window 2: hour 2-4
        #   - $set email to "second@example.com" at hour 3 (newer, should win)
        #   - $set_once signup_source to "source2" at hour 3 (older should win - source1)
        # Window 3: hour 4-6
        #   - $unset email at hour 5 (newest, should remove email from set)
        #   - $set name to "Name3" at hour 5 (newest, should win)

        events = [
            # Window 1 events (hour 1)
            (
                team_id,
                "distinct_id_1",
                person_id,
                bug_window_start + timedelta(hours=1),
                json.dumps(
                    {
                        "$set": {"email": "first@example.com", "name": "Name1"},
                        "$set_once": {"signup_source": "source1"},
                    }
                ),
            ),
            # Window 2 events (hour 3)
            (
                team_id,
                "distinct_id_1",
                person_id,
                bug_window_start + timedelta(hours=3),
                json.dumps({"$set": {"email": "second@example.com"}, "$set_once": {"signup_source": "source2"}}),
            ),
            # Window 3 events (hour 5)
            (
                team_id,
                "distinct_id_1",
                person_id,
                bug_window_start + timedelta(hours=5),
                json.dumps({"$unset": ["email"], "$set": {"name": "Name3"}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Person has email and name (so $set/$unset can modify them)
        # Person does NOT have signup_source (so $set_once will add it)
        person_data = [
            (
                team_id,
                person_id,
                json.dumps({"email": "old@example.com", "name": "OldName"}),
                1,
                now - timedelta(hours=7),
            )
        ]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        bug_window_start_str = bug_window_start.strftime("%Y-%m-%d %H:%M:%S")

        # Run single query (current behavior)
        single_results = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start_str,
        )

        # Run windowed query with 2-hour windows
        windowed_results = get_person_property_updates_windowed(
            team_id=team_id,
            bug_window_start=bug_window_start_str,
            window_seconds=7200,  # 2 hours
        )

        # Both should return exactly one person
        assert len(single_results) == 1
        assert len(windowed_results) == 1

        single_diff = single_results[0]
        windowed_diff = windowed_results[0]

        # Both should have the same person_id
        assert single_diff.person_id == windowed_diff.person_id == str(person_id)

        # Core assertion: windowed query should produce equivalent results to single query
        # The key properties we expect (based on event data):
        # - name: $set to "Name3" at hour 5 (argMax picks latest)
        # - email: $unset at hour 5 (person has email, events want to unset)

        # Verify both queries return the same keys in each category
        assert set(single_diff.set_updates.keys()) == set(windowed_diff.set_updates.keys()), (
            f"set_updates keys differ: single={set(single_diff.set_updates.keys())}, "
            f"windowed={set(windowed_diff.set_updates.keys())}"
        )
        assert set(single_diff.set_once_updates.keys()) == set(windowed_diff.set_once_updates.keys()), (
            f"set_once_updates keys differ: single={set(single_diff.set_once_updates.keys())}, "
            f"windowed={set(windowed_diff.set_once_updates.keys())}"
        )
        assert set(single_diff.unset_updates.keys()) == set(windowed_diff.unset_updates.keys()), (
            f"unset_updates keys differ: single={set(single_diff.unset_updates.keys())}, "
            f"windowed={set(windowed_diff.unset_updates.keys())}"
        )

        # Verify values match for keys that exist
        for key in single_diff.set_updates:
            assert single_diff.set_updates[key].value == windowed_diff.set_updates[key].value, (
                f"set_updates[{key}] value differs"
            )

        for key in single_diff.set_once_updates:
            assert single_diff.set_once_updates[key].value == windowed_diff.set_once_updates[key].value, (
                f"set_once_updates[{key}] value differs"
            )

        # Verify expected properties based on test data
        assert "name" in single_diff.set_updates, "name should be in set_updates"
        assert single_diff.set_updates["name"].value == "Name3", "name should be Name3"
        assert "email" in single_diff.unset_updates, "email should be in unset_updates"


@pytest.mark.django_db(transaction=True)
class TestBatchCommitsEndToEnd:
    """End-to-end integration tests for batch commit functionality.

    These tests use real ClickHouse and Postgres connections to verify
    that batch commits work correctly in a production-like environment.
    """

    @pytest.fixture
    def organization(self):
        """Create a test organization."""
        from posthog.models import Organization

        return Organization.objects.create(name="Batch Test Organization")

    @pytest.fixture
    def team(self, organization):
        """Create a test team."""
        from posthog.models import Team

        return Team.objects.create(organization=organization, name="Batch Test Team")

    def test_batch_commits_end_to_end(self, cluster: ClickhouseCluster, team):
        """
        End-to-end test that verifies batch commits work with real databases.

        Creates 5 persons in Postgres, inserts events in ClickHouse,
        runs reconciliation with batch_size=2, and verifies:
        1. All persons are updated in Postgres
        2. Commits happen in batches (3 batches: [2, 2, 1])
        """
        from posthog.dags.person_property_reconciliation import (
            get_person_property_updates_from_clickhouse,
            process_persons_in_batches,
        )
        from posthog.models import Person

        num_persons = 5
        batch_size = 2

        # Use a unique team_id to avoid conflicts with other tests
        team_id = team.id

        # Time setup
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        event_ts = now - timedelta(days=5)

        # Create persons in Postgres with old property values
        persons = []
        for i in range(num_persons):
            person = Person.objects.create(
                team_id=team_id,
                properties={"email": f"old_{i}@example.com", "counter": i},
                properties_last_updated_at={
                    "email": "2024-01-01T00:00:00+00:00",
                    "counter": "2024-01-01T00:00:00+00:00",
                },
                properties_last_operation={"email": "set", "counter": "set"},
                version=1,
            )
            persons.append(person)

        # Insert events in ClickHouse with new property values
        events = []
        for i, person in enumerate(persons):
            events.append(
                (
                    team_id,
                    f"distinct_id_{i}",
                    person.uuid,
                    event_ts,
                    json.dumps({"$set": {"email": f"new_{i}@example.com"}}),
                )
            )

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert persons in ClickHouse (required for the query join)
        person_ch_data = []
        for i, person in enumerate(persons):
            person_ch_data.append(
                (
                    team_id,
                    person.uuid,
                    json.dumps({"email": f"old_{i}@example.com", "counter": i}),
                    1,  # version
                    0,  # is_deleted
                    now - timedelta(days=8),  # _timestamp
                )
            )

        def insert_persons_ch(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, is_deleted, _timestamp)
                VALUES""",
                person_ch_data,
            )

        cluster.any_host(insert_persons_ch).result()

        # Get person property updates from ClickHouse
        person_property_updates = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(person_property_updates) == num_persons, (
            f"Expected {num_persons} persons from ClickHouse query, got {len(person_property_updates)}"
        )

        # Track batches
        batch_sizes = []

        def on_batch_committed(batch_num: int, batch_persons: list[dict]) -> None:
            batch_sizes.append(len(batch_persons))

        # Use Django's database connection for persons DB (shares test transaction)
        from django.db import connections

        from posthog.person_db_router import PERSONS_DB_FOR_WRITE

        connection = connections[PERSONS_DB_FOR_WRITE]
        with connection.cursor() as cursor:
            # Set up cursor settings
            cursor.execute("SET application_name = 'test_batch_commits'")

            result = process_persons_in_batches(
                person_property_diffs=person_property_updates,
                cursor=cursor,
                job_id="test-batch-job",
                team_id=team_id,
                batch_size=batch_size,
                dry_run=False,
                backup_enabled=False,
                commit_fn=lambda: None,  # No-op commit in tests (Django manages transaction)
                on_batch_committed=on_batch_committed,
            )

        # Verify all persons were processed
        assert result.total_processed == num_persons, f"Expected {num_persons} processed, got {result.total_processed}"
        assert result.total_updated == num_persons, f"Expected {num_persons} updated, got {result.total_updated}"
        assert result.total_skipped == 0, f"Expected 0 skipped, got {result.total_skipped}"

        # Verify batch sizes: [2, 2, 1] for 5 persons with batch_size=2
        assert result.total_commits == 3, f"Expected 3 commits, got {result.total_commits}"
        assert batch_sizes == [2, 2, 1], f"Expected batch sizes [2, 2, 1], got {batch_sizes}"

        # Verify Postgres was actually updated with correct properties and metadata
        for i, person in enumerate(persons):
            person.refresh_from_db()

            # Property value should be updated
            assert person.properties["email"] == f"new_{i}@example.com", (
                f"Person {i} email not updated. Expected 'new_{i}@example.com', got '{person.properties.get('email')}'"
            )

            # Counter should be unchanged (wasn't in the update)
            assert person.properties["counter"] == i, (
                f"Person {i} counter changed unexpectedly. Expected {i}, got {person.properties.get('counter')}"
            )

            # Version should be incremented
            assert person.version == 2, f"Person {i} version not incremented. Expected 2, got {person.version}"

            # properties_last_updated_at should have new timestamp for email
            assert "email" in person.properties_last_updated_at, (
                f"Person {i} properties_last_updated_at missing 'email' key"
            )
            # The timestamp should be from the event (event_ts), not the old value
            email_updated_at = person.properties_last_updated_at["email"]
            assert email_updated_at != "2024-01-01T00:00:00+00:00", (
                f"Person {i} email timestamp not updated. Still has old value: {email_updated_at}"
            )

            # properties_last_operation should be 'set' for email
            assert person.properties_last_operation.get("email") == "set", (
                f"Person {i} properties_last_operation['email'] should be 'set', "
                f"got '{person.properties_last_operation.get('email')}'"
            )

            # Counter's metadata should be unchanged
            assert person.properties_last_updated_at.get("counter") == "2024-01-01T00:00:00+00:00", (
                f"Person {i} counter timestamp changed unexpectedly"
            )

    def test_batch_commits_with_missing_person(self, cluster: ClickhouseCluster, team):
        """
        Test that missing persons in Postgres are skipped gracefully.

        Creates 4 persons in ClickHouse events but only 3 in Postgres.
        Verifies the missing person is skipped and others are updated.
        """
        from posthog.dags.person_property_reconciliation import (
            get_person_property_updates_from_clickhouse,
            process_persons_in_batches,
        )
        from posthog.models import Person

        team_id = team.id

        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        event_ts = now - timedelta(days=5)

        # Create only 3 persons in Postgres
        persons = []
        for i in range(3):
            person = Person.objects.create(
                team_id=team_id,
                properties={"name": f"old_name_{i}"},
                properties_last_updated_at={"name": "2024-01-01T00:00:00+00:00"},
                properties_last_operation={"name": "set"},
                version=1,
            )
            persons.append(person)

        # Create a 4th UUID that won't exist in Postgres
        missing_uuid = UUID("99999999-9999-9999-9999-999999999999")

        # Insert 4 events in ClickHouse (including one for missing person)
        events = []
        for i, person in enumerate(persons):
            events.append(
                (
                    team_id,
                    f"distinct_id_{i}",
                    person.uuid,
                    event_ts,
                    json.dumps({"$set": {"name": f"new_name_{i}"}}),
                )
            )
        # Add event for missing person
        events.append(
            (
                team_id,
                "distinct_id_missing",
                missing_uuid,
                event_ts,
                json.dumps({"$set": {"name": "new_name_missing"}}),
            )
        )

        def insert_events(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events,
            )

        cluster.any_host(insert_events).result()

        # Insert 4 persons in ClickHouse (including missing one)
        person_ch_data = []
        for i, person in enumerate(persons):
            person_ch_data.append(
                (
                    team_id,
                    person.uuid,
                    json.dumps({"name": f"old_name_{i}"}),
                    1,
                    0,
                    now - timedelta(days=8),
                )
            )
        # Add the missing person to ClickHouse
        person_ch_data.append(
            (
                team_id,
                missing_uuid,
                json.dumps({"name": "old_name_missing"}),
                1,
                0,
                now - timedelta(days=8),
            )
        )

        def insert_persons_ch(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, is_deleted, _timestamp)
                VALUES""",
                person_ch_data,
            )

        cluster.any_host(insert_persons_ch).result()

        # Get updates from ClickHouse - should return 4 persons
        person_property_updates = get_person_property_updates_from_clickhouse(
            team_id=team_id,
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
        )

        assert len(person_property_updates) == 4

        batch_sizes = []

        def on_batch_committed(batch_num: int, batch_persons: list[dict]) -> None:
            batch_sizes.append(len(batch_persons))

        # Use Django's database connection for persons DB (shares test transaction)
        from django.db import connections

        from posthog.person_db_router import PERSONS_DB_FOR_WRITE

        connection = connections[PERSONS_DB_FOR_WRITE]
        with connection.cursor() as cursor:
            result = process_persons_in_batches(
                person_property_diffs=person_property_updates,
                cursor=cursor,
                job_id="test-missing-person-job",
                team_id=team_id,
                batch_size=2,
                dry_run=False,
                backup_enabled=False,
                commit_fn=lambda: None,  # No-op commit in tests (Django manages transaction)
                on_batch_committed=on_batch_committed,
            )

        # 4 persons processed, 1 skipped (missing from Postgres), 3 updated
        assert result.total_processed == 4
        assert result.total_skipped == 1  # The missing person
        assert result.total_updated == 3

        # Verify existing persons were updated with correct properties and metadata
        for i, person in enumerate(persons):
            person.refresh_from_db()

            # Property value should be updated
            assert person.properties["name"] == f"new_name_{i}", (
                f"Person {i} name not updated. Expected 'new_name_{i}', got '{person.properties.get('name')}'"
            )

            # Version should be incremented
            assert person.version == 2, f"Person {i} version not incremented. Expected 2, got {person.version}"

            # properties_last_updated_at should have new timestamp
            assert "name" in person.properties_last_updated_at, (
                f"Person {i} properties_last_updated_at missing 'name' key"
            )
            name_updated_at = person.properties_last_updated_at["name"]
            assert name_updated_at != "2024-01-01T00:00:00+00:00", (
                f"Person {i} name timestamp not updated. Still has old value: {name_updated_at}"
            )

            # properties_last_operation should be 'set'
            assert person.properties_last_operation.get("name") == "set", (
                f"Person {i} properties_last_operation['name'] should be 'set', "
                f"got '{person.properties_last_operation.get('name')}'"
            )


@pytest.mark.django_db(transaction=True)
class TestKafkaClickHouseRoundTrip:
    """Integration tests that verify person updates flow through Kafka to ClickHouse.

    These tests use real Kafka (not mocked) and verify that:
    1. publish_person_to_kafka produces messages in the correct format
    2. ClickHouse's Kafka engine consumes the messages
    3. The person table in ClickHouse has the correct data

    This ensures the reconciliation job's Kafka message format is compatible
    with ClickHouse's expectations (matching Node.js ingestion format).
    """

    @pytest.fixture
    def organization(self):
        """Create a test organization."""
        from posthog.models import Organization

        return Organization.objects.create(name="Kafka Test Organization")

    @pytest.fixture
    def team(self, organization):
        """Create a test team."""
        from posthog.models import Team

        return Team.objects.create(organization=organization, name="Kafka Test Team")

    def _wait_for_clickhouse_person(
        self,
        team_id: int,
        person_uuid: str,
        expected_version: int,
        max_wait_seconds: int = 30,
        poll_interval_seconds: float = 0.5,
    ) -> dict | None:
        """
        Poll ClickHouse until the person appears with the expected version.

        Returns the person row as a dict, or None if not found within timeout.
        """
        import time

        from posthog.clickhouse.client import sync_execute

        start_time = time.time()
        while time.time() - start_time < max_wait_seconds:
            rows = sync_execute(
                """
                SELECT id, team_id, properties, is_identified, version, is_deleted, created_at
                FROM person FINAL
                WHERE team_id = %(team_id)s AND id = %(person_uuid)s
                """,
                {"team_id": team_id, "person_uuid": person_uuid},
            )
            if rows:
                row = rows[0]
                person_data = {
                    "id": str(row[0]),
                    "team_id": row[1],
                    "properties": row[2],
                    "is_identified": row[3],
                    "version": row[4],
                    "is_deleted": row[5],
                    "created_at": row[6],
                }
                if person_data["version"] >= expected_version:
                    return person_data
            time.sleep(poll_interval_seconds)
        return None

    @pytest.mark.skipif(
        os.environ.get("KAFKA_ROUNDTRIP_TESTS") != "1",
        reason="Requires real Kafka infrastructure. Set KAFKA_ROUNDTRIP_TESTS=1 to run.",
    )
    def test_publish_person_to_kafka_updates_clickhouse(self, team):
        """
        Test that publish_person_to_kafka produces messages that ClickHouse consumes correctly.

        This verifies the full round-trip:
        1. Create a person in Postgres
        2. Publish to Kafka using publish_person_to_kafka (with real Kafka, not mocked)
        3. Wait for ClickHouse to consume the message
        4. Verify ClickHouse has the correct person data
        """
        from django.test import override_settings

        from posthog.dags.person_property_reconciliation import publish_person_to_kafka
        from posthog.kafka_client.client import _KafkaProducer
        from posthog.models import Person

        # Create person in Postgres
        person = Person.objects.create(
            team_id=team.id,
            properties={"email": "kafka_test@example.com", "name": "Kafka Test User"},
            version=1,
            is_identified=True,
        )

        # Prepare person data for Kafka (simulating what reconciliation job does)
        person_data = {
            "id": person.uuid,
            "team_id": team.id,
            "properties": {"email": "kafka_test@example.com", "name": "Kafka Test User"},
            "is_identified": True,
            "is_deleted": 0,
            "created_at": person.created_at,
            "version": 1,
        }

        # Create a real Kafka producer (not mocked)
        with override_settings(TEST=False):
            producer = _KafkaProducer(test=False)
            try:
                publish_person_to_kafka(person_data, producer)
                producer.flush(timeout=10)
            finally:
                producer.close()

        # Wait for ClickHouse to consume the message
        ch_person = self._wait_for_clickhouse_person(
            team_id=team.id,
            person_uuid=str(person.uuid),
            expected_version=1,
            max_wait_seconds=30,
        )

        # Verify ClickHouse received the person
        assert ch_person is not None, f"Person {person.uuid} not found in ClickHouse after 30 seconds"
        assert ch_person["team_id"] == team.id
        assert ch_person["version"] == 1
        assert ch_person["is_identified"] == 1  # ClickHouse stores as Int8

        # Parse properties (stored as JSON string in ClickHouse)
        ch_properties = json.loads(ch_person["properties"])
        assert ch_properties["email"] == "kafka_test@example.com"
        assert ch_properties["name"] == "Kafka Test User"

    @pytest.mark.skipif(
        os.environ.get("KAFKA_ROUNDTRIP_TESTS") != "1",
        reason="Requires real Kafka infrastructure. Set KAFKA_ROUNDTRIP_TESTS=1 to run.",
    )
    def test_reconciliation_kafka_message_format_matches_nodejs(self, team, cluster: ClickhouseCluster):
        """
        Test that the reconciliation job's Kafka message format produces the same
        ClickHouse state as Node.js ingestion would.

        This is important because both systems publish to the same Kafka topic,
        and ClickHouse must be able to handle messages from both sources.
        """
        from django.test import override_settings

        from posthog.dags.person_property_reconciliation import publish_person_to_kafka
        from posthog.kafka_client.client import _KafkaProducer
        from posthog.models import Person

        # Create person in Postgres with version 1
        person = Person.objects.create(
            team_id=team.id,
            properties={"email": "original@example.com"},
            version=1,
            is_identified=False,
        )

        # First, publish version 1 to establish baseline
        person_data_v1 = {
            "id": person.uuid,
            "team_id": team.id,
            "properties": {"email": "original@example.com"},
            "is_identified": False,
            "is_deleted": 0,
            "created_at": person.created_at,
            "version": 1,
        }

        with override_settings(TEST=False):
            producer = _KafkaProducer(test=False)
            try:
                publish_person_to_kafka(person_data_v1, producer)
                producer.flush(timeout=10)
            finally:
                producer.close()

        # Wait for version 1 in ClickHouse
        ch_person_v1 = self._wait_for_clickhouse_person(
            team_id=team.id,
            person_uuid=str(person.uuid),
            expected_version=1,
        )
        assert ch_person_v1 is not None, "Version 1 not found in ClickHouse"

        # Now simulate reconciliation updating the person to version 2
        person_data_v2 = {
            "id": person.uuid,
            "team_id": team.id,
            "properties": {"email": "reconciled@example.com", "source": "reconciliation"},
            "is_identified": True,
            "is_deleted": 0,
            "created_at": person.created_at,
            "version": 2,
        }

        with override_settings(TEST=False):
            producer = _KafkaProducer(test=False)
            try:
                publish_person_to_kafka(person_data_v2, producer)
                producer.flush(timeout=10)
            finally:
                producer.close()

        # Wait for version 2 in ClickHouse
        ch_person_v2 = self._wait_for_clickhouse_person(
            team_id=team.id,
            person_uuid=str(person.uuid),
            expected_version=2,
        )

        # Verify ClickHouse received the update
        assert ch_person_v2 is not None, "Version 2 not found in ClickHouse after 30 seconds"
        assert ch_person_v2["version"] == 2
        assert ch_person_v2["is_identified"] == 1

        ch_properties = json.loads(ch_person_v2["properties"])
        assert ch_properties["email"] == "reconciled@example.com"
        assert ch_properties["source"] == "reconciliation"

    @pytest.mark.skipif(
        os.environ.get("KAFKA_ROUNDTRIP_TESTS") != "1",
        reason="Requires real Kafka infrastructure. Set KAFKA_ROUNDTRIP_TESTS=1 to run.",
    )
    def test_full_dagster_job_with_real_kafka(self, team, cluster: ClickhouseCluster):
        """
        Test the full Dagster reconciliation job with real Kafka.

        This is the most comprehensive test - it:
        1. Creates persons in Postgres with outdated properties
        2. Inserts events in ClickHouse with updated properties
        3. Runs the actual Dagster job with real Kafka producer
        4. Waits for ClickHouse to consume the Kafka messages
        5. Verifies both Postgres AND ClickHouse have the correct data
        """
        from django.test import override_settings

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_job
        from posthog.kafka_client.client import _KafkaProducer
        from posthog.models import Person

        # Time setup - create a bug window that includes our test events
        now = datetime.now().replace(microsecond=0)
        bug_window_start = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        bug_window_end = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        event_ts = now - timedelta(days=5)

        # Create person in Postgres with old property value
        person = Person.objects.create(
            team_id=team.id,
            properties={"email": "old@example.com", "unchanged": "value"},
            properties_last_updated_at={
                "email": "2024-01-01T00:00:00+00:00",
                "unchanged": "2024-01-01T00:00:00+00:00",
            },
            properties_last_operation={"email": "set", "unchanged": "set"},
            version=1,
        )

        # Insert event in ClickHouse with new property value
        def insert_event(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                [
                    (
                        team.id,
                        "test_distinct_id",
                        person.uuid,
                        event_ts,
                        json.dumps({"$set": {"email": "new@example.com"}}),
                    )
                ],
            )

        cluster.any_host(insert_event).result()

        # Insert person in ClickHouse (required for the reconciliation query join)
        def insert_person_ch(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, is_deleted, _timestamp)
                VALUES""",
                [
                    (
                        team.id,
                        person.uuid,
                        json.dumps({"email": "old@example.com", "unchanged": "value"}),
                        1,
                        0,
                        now - timedelta(days=8),
                    )
                ],
            )

        cluster.any_host(insert_person_ch).result()

        # Get a Postgres connection for the job
        from django.db import connections

        from posthog.person_db_router import PERSONS_DB_FOR_WRITE

        persons_conn = connections[PERSONS_DB_FOR_WRITE]

        # Create real Kafka producer
        with override_settings(TEST=False):
            kafka_producer = _KafkaProducer(test=False)

            try:
                # Run the actual Dagster job
                result = person_property_reconciliation_job.execute_in_process(
                    run_config={
                        "ops": {
                            "get_team_ids_to_reconcile": {
                                "config": {
                                    "team_ids": [team.id],
                                    "bug_window_start": bug_window_start,
                                    "bug_window_end": bug_window_end,
                                    "dry_run": False,
                                    "backup_enabled": False,
                                    "batch_size": 100,
                                }
                            },
                            "reconcile_team_chunk": {
                                "config": {
                                    "bug_window_start": bug_window_start,
                                    "dry_run": False,
                                    "backup_enabled": False,
                                    "batch_size": 100,
                                }
                            },
                        }
                    },
                    resources={
                        "cluster": cluster,
                        "persons_database": persons_conn,
                        "kafka_producer": kafka_producer,
                    },
                )

                assert result.success, f"Dagster job failed: {result}"

                # Flush kafka to ensure all messages are sent
                kafka_producer.flush(timeout=10)

            finally:
                kafka_producer.close()

        # Verify Postgres was updated
        person.refresh_from_db()
        assert person.properties["email"] == "new@example.com", (
            f"Postgres email not updated. Expected 'new@example.com', got '{person.properties.get('email')}'"
        )
        assert person.properties["unchanged"] == "value", "Unchanged property was modified"
        assert person.version == 2, f"Postgres version not incremented. Expected 2, got {person.version}"

        # Wait for ClickHouse to consume the Kafka message
        ch_person = self._wait_for_clickhouse_person(
            team_id=team.id,
            person_uuid=str(person.uuid),
            expected_version=2,
            max_wait_seconds=30,
        )

        # Verify ClickHouse received the update via Kafka
        assert ch_person is not None, (
            f"Person {person.uuid} version 2 not found in ClickHouse after 30 seconds. "
            "This suggests the Kafka message format may not be compatible with ClickHouse."
        )
        assert ch_person["version"] == 2

        ch_properties = json.loads(ch_person["properties"])
        assert ch_properties["email"] == "new@example.com", (
            f"ClickHouse email not updated. Expected 'new@example.com', got '{ch_properties.get('email')}'"
        )
        assert ch_properties["unchanged"] == "value", "ClickHouse unchanged property was modified"

    @pytest.mark.skipif(
        os.environ.get("KAFKA_ROUNDTRIP_TESTS") != "1",
        reason="Requires real Kafka infrastructure. Set KAFKA_ROUNDTRIP_TESTS=1 to run.",
    )
    def test_full_job_timestamp_window_filtering_all_permutations(self, cluster: ClickhouseCluster):
        """End-to-end test of the full Dagster job with all timestamp permutations.

        Tests the complete pipeline:
        1. Creates persons in Postgres with different _timestamp values
        2. Inserts events in ClickHouse with different timestamps
        3. Runs the full Dagster reconciliation job
        4. Verifies only the correct persons were updated in Postgres

        Test matrix (person _timestamp × event timestamp):
        | Person _timestamp | Event timestamp | Should be reconciled? |
        |-------------------|-----------------|----------------------|
        | BEFORE            | BEFORE          | NO                   |
        | BEFORE            | DURING          | YES                  |
        | BEFORE            | AFTER           | YES                  |
        | DURING            | BEFORE          | NO                   |
        | DURING            | DURING          | YES                  |
        | DURING            | AFTER           | YES                  |
        | AFTER             | BEFORE          | NO                   |
        | AFTER             | DURING          | YES                  |
        | AFTER             | AFTER           | YES                  |

        Key insight: Only EVENT timestamp matters, not person _timestamp.
        Events BEFORE bug_window_start are filtered; events DURING or AFTER are included.
        """
        from django.test import override_settings

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_job
        from posthog.kafka_client.client import _KafkaProducer
        from posthog.models import Organization, Person, Team

        # Create two organizations and teams for isolation
        org1 = Organization.objects.create(name="Test Org 1 for timestamp permutations")
        org2 = Organization.objects.create(name="Test Org 2 for timestamp permutations")
        team1 = Team.objects.create(organization=org1, name="Team 1")
        team2 = Team.objects.create(organization=org2, name="Team 2")

        now = datetime.now().replace(microsecond=0)

        # Define time periods
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now - timedelta(days=5)

        # Timestamps for each period
        ts_before = now - timedelta(days=15)  # Before bug_window_start
        ts_during = now - timedelta(days=7)  # Between bug_window_start and bug_window_end
        ts_after = now - timedelta(days=2)  # After bug_window_end but before now()

        # Test cases for team 1: all 9 permutations
        # Format: (suffix, person_ts, event_ts, should_be_reconciled, prop_name)
        test_cases_team1 = [
            # Person _timestamp BEFORE bug_window_start
            ("t1_001", ts_before, ts_before, False, "prop_before_before"),
            ("t1_002", ts_before, ts_during, True, "prop_before_during"),
            ("t1_003", ts_before, ts_after, True, "prop_before_after"),
            # Person _timestamp DURING bug_window
            ("t1_004", ts_during, ts_before, False, "prop_during_before"),
            ("t1_005", ts_during, ts_during, True, "prop_during_during"),
            ("t1_006", ts_during, ts_after, True, "prop_during_after"),
            # Person _timestamp AFTER bug_window_end
            ("t1_007", ts_after, ts_before, False, "prop_after_before"),
            ("t1_008", ts_after, ts_during, True, "prop_after_during"),
            ("t1_009", ts_after, ts_after, True, "prop_after_after"),
        ]

        # Test cases for team 2: subset to verify team isolation
        test_cases_team2 = [
            ("t2_001", ts_before, ts_during, True, "team2_prop_1"),
            ("t2_002", ts_during, ts_after, True, "team2_prop_2"),
            ("t2_003", ts_after, ts_before, False, "team2_prop_3"),
        ]

        # Create persons in Postgres for team 1
        persons_team1 = {}
        for suffix, _person_ts, _event_ts, _expected, prop_name in test_cases_team1:
            person = Person.objects.create(
                team_id=team1.id,
                properties={prop_name: "old_value"},
                properties_last_updated_at={prop_name: "2020-01-01T00:00:00+00:00"},
                properties_last_operation={prop_name: "set"},
                version=1,
            )
            persons_team1[suffix] = person

        # Create persons in Postgres for team 2
        persons_team2 = {}
        for suffix, _person_ts, _event_ts, _expected, prop_name in test_cases_team2:
            person = Person.objects.create(
                team_id=team2.id,
                properties={prop_name: "old_value"},
                properties_last_updated_at={prop_name: "2020-01-01T00:00:00+00:00"},
                properties_last_operation={prop_name: "set"},
                version=1,
            )
            persons_team2[suffix] = person

        # Insert events in ClickHouse for team 1
        events_team1 = []
        for suffix, _person_ts, event_ts, _expected, prop_name in test_cases_team1:
            person = persons_team1[suffix]
            events_team1.append(
                (
                    team1.id,
                    f"distinct_{suffix}",
                    person.uuid,
                    event_ts,
                    json.dumps({"$set": {prop_name: "new_value"}}),
                )
            )

        def insert_events_team1(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events_team1,
            )

        cluster.any_host(insert_events_team1).result()

        # Insert events in ClickHouse for team 2
        events_team2 = []
        for suffix, _person_ts, event_ts, _expected, prop_name in test_cases_team2:
            person = persons_team2[suffix]
            events_team2.append(
                (
                    team2.id,
                    f"distinct_{suffix}",
                    person.uuid,
                    event_ts,
                    json.dumps({"$set": {prop_name: "new_value"}}),
                )
            )

        def insert_events_team2(client: Client) -> None:
            client.execute(
                """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties)
                VALUES""",
                events_team2,
            )

        cluster.any_host(insert_events_team2).result()

        # Insert persons in ClickHouse for team 1 (required for the query join)
        persons_ch_team1 = []
        for suffix, person_ts, _event_ts, _expected, prop_name in test_cases_team1:
            person = persons_team1[suffix]
            persons_ch_team1.append(
                (
                    team1.id,
                    person.uuid,
                    json.dumps({prop_name: "old_value"}),
                    1,
                    0,  # is_deleted
                    person_ts,  # _timestamp
                )
            )

        def insert_persons_ch_team1(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, is_deleted, _timestamp)
                VALUES""",
                persons_ch_team1,
            )

        cluster.any_host(insert_persons_ch_team1).result()

        # Insert persons in ClickHouse for team 2
        persons_ch_team2 = []
        for suffix, person_ts, _event_ts, _expected, prop_name in test_cases_team2:
            person = persons_team2[suffix]
            persons_ch_team2.append(
                (
                    team2.id,
                    person.uuid,
                    json.dumps({prop_name: "old_value"}),
                    1,
                    0,
                    person_ts,
                )
            )

        def insert_persons_ch_team2(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, is_deleted, _timestamp)
                VALUES""",
                persons_ch_team2,
            )

        cluster.any_host(insert_persons_ch_team2).result()

        # Run the Dagster job
        from django.db import connections

        from posthog.person_db_router import PERSONS_DB_FOR_WRITE

        persons_conn = connections[PERSONS_DB_FOR_WRITE]

        with override_settings(TEST=False):
            kafka_producer = _KafkaProducer(test=False)

            try:
                result = person_property_reconciliation_job.execute_in_process(
                    run_config={
                        "ops": {
                            "get_team_ids_to_reconcile": {
                                "config": {
                                    "team_ids": [team1.id, team2.id],
                                    "bug_window_start": bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
                                    "bug_window_end": bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
                                    "dry_run": False,
                                    "backup_enabled": False,
                                    "batch_size": 100,
                                }
                            },
                            "reconcile_team_chunk": {
                                "config": {
                                    "bug_window_start": bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
                                    "dry_run": False,
                                    "backup_enabled": False,
                                    "batch_size": 100,
                                }
                            },
                        }
                    },
                    resources={
                        "cluster": cluster,
                        "persons_database": persons_conn,
                        "kafka_producer": kafka_producer,
                    },
                )

                assert result.success, f"Dagster job failed: {result}"
                kafka_producer.flush(timeout=10)

            finally:
                kafka_producer.close()

        # Verify team 1 results in Postgres
        for suffix, _person_ts, _event_ts, should_be_reconciled, prop_name in test_cases_team1:
            person = persons_team1[suffix]
            person.refresh_from_db()

            if should_be_reconciled:
                assert person.properties[prop_name] == "new_value", (
                    f"Person {suffix} should have been reconciled. "
                    f"Expected 'new_value', got '{person.properties.get(prop_name)}'"
                )
                assert person.version == 2, f"Person {suffix} version should be 2, got {person.version}"
            else:
                assert person.properties[prop_name] == "old_value", (
                    f"Person {suffix} should NOT have been reconciled. "
                    f"Expected 'old_value', got '{person.properties.get(prop_name)}'"
                )
                assert person.version == 1, f"Person {suffix} version should still be 1, got {person.version}"

        # Verify team 2 results in Postgres
        for suffix, _person_ts, _event_ts, should_be_reconciled, prop_name in test_cases_team2:
            person = persons_team2[suffix]
            person.refresh_from_db()

            if should_be_reconciled:
                assert person.properties[prop_name] == "new_value", (
                    f"Person {suffix} should have been reconciled. "
                    f"Expected 'new_value', got '{person.properties.get(prop_name)}'"
                )
                assert person.version == 2, f"Person {suffix} version should be 2, got {person.version}"
            else:
                assert person.properties[prop_name] == "old_value", (
                    f"Person {suffix} should NOT have been reconciled. "
                    f"Expected 'old_value', got '{person.properties.get(prop_name)}'"
                )
                assert person.version == 1, f"Person {suffix} version should still be 1, got {person.version}"

        # Count reconciled vs not reconciled for summary
        reconciled_team1 = sum(1 for _, _, _, expected, _ in test_cases_team1 if expected)
        not_reconciled_team1 = len(test_cases_team1) - reconciled_team1
        reconciled_team2 = sum(1 for _, _, _, expected, _ in test_cases_team2 if expected)
        not_reconciled_team2 = len(test_cases_team2) - reconciled_team2

        # Verify we tested the expected number of cases
        assert reconciled_team1 == 6, f"Expected 6 reconciled in team 1, got {reconciled_team1}"
        assert not_reconciled_team1 == 3, f"Expected 3 not reconciled in team 1, got {not_reconciled_team1}"
        assert reconciled_team2 == 2, f"Expected 2 reconciled in team 2, got {reconciled_team2}"
        assert not_reconciled_team2 == 1, f"Expected 1 not reconciled in team 2, got {not_reconciled_team2}"


@pytest.mark.django_db
class TestFetchPersonPropertiesFromClickHouse:
    """Integration tests for fetch_person_properties_from_clickhouse against real ClickHouse."""

    def test_fetches_oldest_version_gte_min_version(self, cluster: ClickhouseCluster):
        """Test that we fetch the oldest available version >= min_version.

        The function uses argMin to get the oldest version that's at least as new as
        the requested min_version. This handles cases where the exact version may have
        been merged away by ReplacingMergeTree.
        """
        team_id = 99801
        person_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-000000000001")
        now = datetime.now().replace(microsecond=0)

        # Insert each version in separate INSERT statements to create separate parts
        def insert_v1(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                [(team_id, person_id, json.dumps({"email": "v1@example.com"}), 1, now - timedelta(days=5))],
            )

        def insert_v3(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                [(team_id, person_id, json.dumps({"email": "v3@example.com"}), 3, now - timedelta(days=3))],
            )

        def insert_v5(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                [(team_id, person_id, json.dumps({"email": "v5@example.com"}), 5, now - timedelta(days=1))],
            )

        cluster.any_host(insert_v1).result()
        cluster.any_host(insert_v3).result()
        cluster.any_host(insert_v5).result()

        # min_version=1 should get v1 (oldest >= 1)
        props = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=1)
        assert props is not None
        assert props["email"] == "v1@example.com"

        # min_version=2 should get v3 (oldest >= 2, since v2 doesn't exist)
        props = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=2)
        assert props is not None
        assert props["email"] == "v3@example.com"

        # min_version=3 should get v3 (oldest >= 3)
        props = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=3)
        assert props is not None
        assert props["email"] == "v3@example.com"

        # min_version=4 should get v5 (oldest >= 4, since v4 doesn't exist)
        props = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=4)
        assert props is not None
        assert props["email"] == "v5@example.com"

        # min_version=5 should get v5
        props = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=5)
        assert props is not None
        assert props["email"] == "v5@example.com"

    def test_returns_none_when_no_version_gte_min(self, cluster: ClickhouseCluster):
        """Test that None is returned when no version >= min_version exists."""
        team_id = 99802
        person_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-000000000002")
        now = datetime.now().replace(microsecond=0)

        # Insert person with only version 5
        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                [(team_id, person_id, json.dumps({"email": "test@example.com"}), 5, now)],
            )

        cluster.any_host(insert_person).result()

        # min_version=5 exists
        result = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=5)
        assert result is not None

        # min_version=6 - no version >= 6 exists
        assert fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=6) is None

        # min_version=99 - no version >= 99 exists
        assert fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=99) is None

    def test_returns_none_for_nonexistent_person(self, cluster: ClickhouseCluster):
        """Test that None is returned when the person doesn't exist."""
        team_id = 99803
        nonexistent_person_id = "cccccccc-cccc-cccc-cccc-000000000003"

        result = fetch_person_properties_from_clickhouse(team_id, nonexistent_person_id, min_version=1)
        assert result is None

    def test_returns_empty_dict_for_empty_properties(self, cluster: ClickhouseCluster):
        """Test that empty dict is returned when properties are empty."""
        team_id = 99804
        person_id = UUID("dddddddd-dddd-dddd-dddd-000000000004")
        now = datetime.now().replace(microsecond=0)

        # Insert person with empty properties
        person_data = [(team_id, person_id, json.dumps({}), 1, now)]

        def insert_person(client: Client) -> None:
            client.execute(
                """INSERT INTO person (team_id, id, properties, version, _timestamp)
                VALUES""",
                person_data,
            )

        cluster.any_host(insert_person).result()

        result = fetch_person_properties_from_clickhouse(team_id, str(person_id), min_version=1)
        assert result == {}


class TestReconcileWithConcurrentChanges:
    """Unit tests for reconcile_with_concurrent_changes 3-way merge logic."""

    def test_applies_event_changes_when_no_concurrent_postgres_changes(self):
        """When Postgres hasn't changed from CH baseline, all event changes apply."""
        ch_properties = {"email": "original@example.com", "name": "Original"}
        postgres_person = {
            "properties": {"email": "original@example.com", "name": "Original"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="new@example.com")},
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        assert result is not None
        assert result["properties"]["email"] == "new@example.com"
        assert result["properties"]["name"] == "Original"  # unchanged

    def test_postgres_wins_on_conflict(self):
        """When Postgres has changed a key that events also change, Postgres wins."""
        ch_properties = {"email": "original@example.com"}
        postgres_person = {
            "properties": {"email": "postgres_changed@example.com"},  # Postgres changed this
            "properties_last_updated_at": {"email": "2024-01-16T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={
                "email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="event_changed@example.com")
            },
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        # No changes - Postgres already has a different value, so our change is skipped
        assert result is None

    def test_applies_event_change_to_unconflicted_key(self):
        """Event changes apply to keys that Postgres hasn't concurrently modified."""
        ch_properties = {"email": "original@example.com", "name": "Original"}
        postgres_person = {
            "properties": {"email": "postgres_changed@example.com", "name": "Original"},  # Only email changed
            "properties_last_updated_at": {"email": "2024-01-16T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={
                "email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="event_email@example.com"),
                "name": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="Event Name"),
            },
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        assert result is not None
        # email: Postgres wins (concurrent change)
        assert result["properties"]["email"] == "postgres_changed@example.com"
        # name: event wins (no concurrent change)
        assert result["properties"]["name"] == "Event Name"

    def test_set_once_applies_for_new_key(self):
        """set_once applies when key doesn't exist in Postgres."""
        ch_properties: dict[str, Any] = {}
        postgres_person: dict[str, Any] = {
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={},
            set_once_updates={"referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0), value="google.com")},
            unset_updates={},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        assert result is not None
        assert result["properties"]["referrer"] == "google.com"

    def test_set_once_skipped_when_key_exists_in_postgres(self):
        """set_once is skipped when key already exists in Postgres (even if added concurrently)."""
        ch_properties: dict[str, Any] = {}  # Key didn't exist at CH version
        postgres_person: dict[str, Any] = {
            "properties": {"referrer": "facebook.com"},  # But now exists in Postgres
            "properties_last_updated_at": {"referrer": "2024-01-12T00:00:00"},
            "properties_last_operation": {"referrer": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={},
            set_once_updates={"referrer": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0), value="google.com")},
            unset_updates={},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        # No change - key exists in Postgres
        assert result is None

    def test_unset_applies_when_key_not_concurrently_changed(self):
        """$unset removes key when Postgres hasn't concurrently modified it."""
        ch_properties = {"email": "original@example.com", "name": "Original"}
        postgres_person = {
            "properties": {"email": "original@example.com", "name": "Original"},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={},
            set_once_updates={},
            unset_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value=None)},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        assert result is not None
        assert "email" not in result["properties"]
        assert result["properties"]["name"] == "Original"

    def test_unset_skipped_when_key_concurrently_changed(self):
        """$unset is skipped when Postgres has concurrently modified the key."""
        ch_properties = {"email": "original@example.com"}
        postgres_person = {
            "properties": {"email": "postgres_updated@example.com"},  # Postgres changed this
            "properties_last_updated_at": {"email": "2024-01-16T00:00:00"},
            "properties_last_operation": {"email": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={},
            set_once_updates={},
            unset_updates={"email": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value=None)},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        # No change - Postgres has concurrent modification
        assert result is None

    def test_preserves_postgres_additions(self):
        """Keys added to Postgres concurrently should be preserved."""
        ch_properties = {"email": "original@example.com"}
        postgres_person = {
            "properties": {"email": "original@example.com", "new_key": "postgres_added"},
            "properties_last_updated_at": {"new_key": "2024-01-16T00:00:00"},
            "properties_last_operation": {"new_key": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={"name": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="Event Name")},
            set_once_updates={},
            unset_updates={},
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        assert result is not None
        assert result["properties"]["email"] == "original@example.com"
        assert result["properties"]["new_key"] == "postgres_added"  # Preserved
        assert result["properties"]["name"] == "Event Name"  # Event change applied

    def test_mixed_operations_with_conflicts(self):
        """Test complex scenario with multiple operations and partial conflicts."""
        ch_properties = {"a": "ch_a", "b": "ch_b", "c": "ch_c"}
        postgres_person = {
            "properties": {"a": "pg_a", "b": "ch_b", "c": "ch_c", "d": "pg_d"},  # a changed, d added
            "properties_last_updated_at": {"a": "2024-01-16T00:00:00", "d": "2024-01-16T00:00:00"},
            "properties_last_operation": {"a": "set", "d": "set"},
        }
        person_diffs = PersonPropertyDiffs(
            person_id="test-person",
            person_version=1,
            set_updates={
                "a": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="event_a"),  # Conflict
                "b": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value="event_b"),  # No conflict
            },
            set_once_updates={
                "e": PropertyValue(timestamp=datetime(2024, 1, 10, 8, 0, 0), value="event_e"),  # New key
            },
            unset_updates={
                "c": PropertyValue(timestamp=datetime(2024, 1, 15, 12, 0, 0), value=None),  # No conflict
            },
        )

        result = reconcile_with_concurrent_changes(ch_properties, postgres_person, person_diffs)

        assert result is not None
        assert result["properties"]["a"] == "pg_a"  # Postgres wins (conflict)
        assert result["properties"]["b"] == "event_b"  # Event wins (no conflict)
        assert "c" not in result["properties"]  # Unset applied (no conflict)
        assert result["properties"]["d"] == "pg_d"  # Postgres addition preserved
        assert result["properties"]["e"] == "event_e"  # set_once applied (new key)


@pytest.mark.django_db
class TestQueryTeamIdsFromClickHouse:
    """Integration tests for query_team_ids_from_clickhouse with team_id filters."""

    def test_returns_teams_with_property_events(self, cluster: ClickhouseCluster):
        """Basic test that teams with $set/$set_once/$unset events are returned."""
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        # Use unique team_ids unlikely to conflict with other tests (88001-88005)
        events = [
            (
                88001,
                "d1",
                UUID("11111111-1111-1111-1111-880000000001"),
                now - timedelta(days=5),
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                88002,
                "d2",
                UUID("11111111-1111-1111-1111-880000000002"),
                now - timedelta(days=5),
                json.dumps({"$set_once": {"b": 2}}),
            ),
            (
                88003,
                "d3",
                UUID("11111111-1111-1111-1111-880000000003"),
                now - timedelta(days=5),
                json.dumps({"$unset": ["c"]}),
            ),
            (
                88004,
                "d4",
                UUID("11111111-1111-1111-1111-880000000004"),
                now - timedelta(days=5),
                json.dumps({"$set": {"d": 4}}),
            ),
            (
                88005,
                "d5",
                UUID("11111111-1111-1111-1111-880000000005"),
                now - timedelta(days=5),
                json.dumps({"other": "no_props"}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            min_team_id=88001,
            max_team_id=88005,
        )

        # 88005 has no $set/$set_once/$unset so should not be included
        assert result == [88001, 88002, 88003, 88004]

    def test_min_team_id_filter(self, cluster: ClickhouseCluster):
        """Test that min_team_id filters out teams below the threshold."""
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        events = [
            (
                89001,
                "d1",
                UUID("11111111-1111-1111-1111-890000000001"),
                now - timedelta(days=5),
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                89002,
                "d2",
                UUID("11111111-1111-1111-1111-890000000002"),
                now - timedelta(days=5),
                json.dumps({"$set": {"b": 2}}),
            ),
            (
                89003,
                "d3",
                UUID("11111111-1111-1111-1111-890000000003"),
                now - timedelta(days=5),
                json.dumps({"$set": {"c": 3}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            min_team_id=89002,
            max_team_id=89003,
        )

        assert result == [89002, 89003]

    def test_max_team_id_filter(self, cluster: ClickhouseCluster):
        """Test that max_team_id filters out teams above the threshold."""
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        events = [
            (
                90001,
                "d1",
                UUID("11111111-1111-1111-1111-900000000001"),
                now - timedelta(days=5),
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                90002,
                "d2",
                UUID("11111111-1111-1111-1111-900000000002"),
                now - timedelta(days=5),
                json.dumps({"$set": {"b": 2}}),
            ),
            (
                90003,
                "d3",
                UUID("11111111-1111-1111-1111-900000000003"),
                now - timedelta(days=5),
                json.dumps({"$set": {"c": 3}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            min_team_id=90001,
            max_team_id=90002,
        )

        assert result == [90001, 90002]

    def test_both_min_and_max_team_id_filters(self, cluster: ClickhouseCluster):
        """Test that both min and max filters work together."""
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        events = [
            (
                91001,
                "d1",
                UUID("11111111-1111-1111-1111-910000000001"),
                now - timedelta(days=5),
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                91002,
                "d2",
                UUID("11111111-1111-1111-1111-910000000002"),
                now - timedelta(days=5),
                json.dumps({"$set": {"b": 2}}),
            ),
            (
                91003,
                "d3",
                UUID("11111111-1111-1111-1111-910000000003"),
                now - timedelta(days=5),
                json.dumps({"$set": {"c": 3}}),
            ),
            (
                91004,
                "d4",
                UUID("11111111-1111-1111-1111-910000000004"),
                now - timedelta(days=5),
                json.dumps({"$set": {"d": 4}}),
            ),
            (
                91005,
                "d5",
                UUID("11111111-1111-1111-1111-910000000005"),
                now - timedelta(days=5),
                json.dumps({"$set": {"e": 5}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            min_team_id=91002,
            max_team_id=91004,
        )

        assert result == [91002, 91003, 91004]

    def test_team_range_returns_all_matching_teams(self, cluster: ClickhouseCluster):
        """Test that team range filter returns all teams with property events within range."""
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        events = [
            (
                92001,
                "d1",
                UUID("11111111-1111-1111-1111-920000000001"),
                now - timedelta(days=5),
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                92002,
                "d2",
                UUID("11111111-1111-1111-1111-920000000002"),
                now - timedelta(days=5),
                json.dumps({"$set": {"b": 2}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            min_team_id=92001,
            max_team_id=92002,
        )

        assert 92001 in result
        assert 92002 in result

    def test_exclude_team_ids_filters_out_specified_teams(self, cluster: ClickhouseCluster):
        """Test that exclude_team_ids filters out specified teams from results."""
        now = datetime.now().replace(microsecond=0)
        bug_window_start = now - timedelta(days=10)
        bug_window_end = now + timedelta(days=1)

        events = [
            (
                93001,
                "d1",
                UUID("11111111-1111-1111-1111-930000000001"),
                now - timedelta(days=5),
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                93002,
                "d2",
                UUID("11111111-1111-1111-1111-930000000002"),
                now - timedelta(days=5),
                json.dumps({"$set": {"b": 2}}),
            ),
            (
                93003,
                "d3",
                UUID("11111111-1111-1111-1111-930000000003"),
                now - timedelta(days=5),
                json.dumps({"$set": {"c": 3}}),
            ),
            (
                93004,
                "d4",
                UUID("11111111-1111-1111-1111-930000000004"),
                now - timedelta(days=5),
                json.dumps({"$set": {"d": 4}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            min_team_id=93001,
            max_team_id=93004,
            exclude_team_ids=[93002, 93004],
        )

        assert result == [93001, 93003]

    def test_include_team_ids_filters_to_specified_teams(self, cluster: ClickhouseCluster):
        """Test that include_team_ids only returns teams in the specified list."""
        bug_window_start = datetime.now(UTC) - timedelta(hours=2)
        bug_window_end = datetime.now(UTC) + timedelta(hours=1)
        event_time = datetime.now(UTC) - timedelta(hours=1)

        # Create events for teams 94001-94005
        events = [
            (
                94001,
                "user_a",
                "00000000-0000-0000-0000-000000094001",
                event_time,
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                94002,
                "user_b",
                "00000000-0000-0000-0000-000000094002",
                event_time,
                json.dumps({"$set": {"b": 2}}),
            ),
            (
                94003,
                "user_c",
                "00000000-0000-0000-0000-000000094003",
                event_time,
                json.dumps({"$set": {"c": 3}}),
            ),
            (
                94004,
                "user_d",
                "00000000-0000-0000-0000-000000094004",
                event_time,
                json.dumps({"$set": {"d": 4}}),
            ),
            (
                94005,
                "user_e",
                "00000000-0000-0000-0000-000000094005",
                event_time,
                json.dumps({"$set": {"e": 5}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        # Only include teams 94002 and 94004 - should not return 94001, 94003, 94005
        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            include_team_ids=[94002, 94004],
        )

        assert result == [94002, 94004]

    def test_include_team_ids_combined_with_other_filters(self, cluster: ClickhouseCluster):
        """Test that include_team_ids works as AND with other filters."""
        bug_window_start = datetime.now(UTC) - timedelta(hours=2)
        bug_window_end = datetime.now(UTC) + timedelta(hours=1)
        event_time = datetime.now(UTC) - timedelta(hours=1)

        # Create events for teams 95001-95004
        events = [
            (
                95001,
                "user_a",
                "00000000-0000-0000-0000-000000095001",
                event_time,
                json.dumps({"$set": {"a": 1}}),
            ),
            (
                95002,
                "user_b",
                "00000000-0000-0000-0000-000000095002",
                event_time,
                json.dumps({"$set": {"b": 2}}),
            ),
            (
                95003,
                "user_c",
                "00000000-0000-0000-0000-000000095003",
                event_time,
                json.dumps({"$set": {"c": 3}}),
            ),
            (
                95004,
                "user_d",
                "00000000-0000-0000-0000-000000095004",
                event_time,
                json.dumps({"$set": {"d": 4}}),
            ),
        ]

        def insert_events(client: Client) -> None:
            client.execute(
                "INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp, properties) VALUES",
                events,
            )

        cluster.any_host(insert_events).result()

        # include_team_ids=[95001, 95002, 95003] AND exclude_team_ids=[95002] -> only 95001, 95003
        result = query_team_ids_from_clickhouse(
            bug_window_start=bug_window_start.strftime("%Y-%m-%d %H:%M:%S"),
            bug_window_end=bug_window_end.strftime("%Y-%m-%d %H:%M:%S"),
            include_team_ids=[95001, 95002, 95003],
            exclude_team_ids=[95002],
        )

        assert result == [95001, 95003]

    def test_invalid_range_raises_error(self):
        """Test that min_team_id > max_team_id raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            query_team_ids_from_clickhouse(
                bug_window_start="2024-01-01 00:00:00",
                bug_window_end="2024-01-02 00:00:00",
                min_team_id=100,
                max_team_id=50,
            )

        assert "min_team_id (100) cannot be greater than max_team_id (50)" in str(exc_info.value)


class TestReconcileSingleTeamErrorHandling:
    """Tests for error handling in reconcile_single_team and reconcile_team_chunk."""

    def test_team_failure_does_not_crash_chunk(self):
        """Test that if one team fails, the chunk continues processing other teams."""
        from posthog.dags.person_property_reconciliation import (
            PersonPropertyReconciliationConfig,
            TeamReconciliationResult,
        )

        # Mock reconcile_single_team to fail for team 2 but succeed for teams 1 and 3
        call_count = {"value": 0}
        original_results = {
            1: TeamReconciliationResult(team_id=1, persons_processed=10, persons_updated=5, persons_skipped=5),
            3: TeamReconciliationResult(team_id=3, persons_processed=20, persons_updated=15, persons_skipped=5),
        }

        def mock_reconcile_single_team(team_id, **kwargs):
            call_count["value"] += 1
            if team_id == 2:
                raise Exception("Simulated failure for team 2")
            return original_results[team_id]

        with patch(
            "posthog.dags.person_property_reconciliation.reconcile_single_team",
            side_effect=mock_reconcile_single_team,
        ):
            # Create mock context with run info
            mock_context = MagicMock()
            mock_context.run.job_name = "test_job"
            mock_context.run.run_id = "test_run_123"

            # Create real config
            config = PersonPropertyReconciliationConfig(
                bug_window_start="2024-01-01 00:00:00",
                batch_size=100,
                dry_run=False,
                backup_enabled=False,
            )

            # Create mock resources
            mock_db = MagicMock()
            mock_cluster = MagicMock()
            mock_kafka = MagicMock()

            # Import the underlying function (not the op wrapper)
            from posthog.dags.person_property_reconciliation import reconcile_team_chunk

            # Call the op's underlying function directly via __wrapped__
            result = reconcile_team_chunk.__wrapped__(  # type: ignore[attr-defined]
                context=mock_context,
                config=config,
                chunk=[1, 2, 3],
                persons_database=mock_db,
                cluster=mock_cluster,
                kafka_producer=mock_kafka,
            )

            # All 3 teams should have been attempted
            assert call_count["value"] == 3

            # Check overall results
            assert result["teams_count"] == 3
            assert result["teams_succeeded"] == 2
            assert result["teams_failed"] == 1
            assert result["persons_processed"] == 30  # 10 + 0 + 20
            assert result["persons_updated"] == 20  # 5 + 0 + 15

            # Check individual team results
            teams_results = result["teams_results"]
            assert len(teams_results) == 3

            team1_result = next(r for r in teams_results if r["team_id"] == 1)
            assert team1_result["status"] == "success"
            assert team1_result["persons_processed"] == 10

            team2_result = next(r for r in teams_results if r["team_id"] == 2)
            assert team2_result["status"] == "failed"
            assert "Simulated failure" in team2_result["error"]

            team3_result = next(r for r in teams_results if r["team_id"] == 3)
            assert team3_result["status"] == "success"
            assert team3_result["persons_processed"] == 20


class TestReconciliationSchedulerSensor:
    """Tests for the person_property_reconciliation_scheduler sensor."""

    def test_build_reconciliation_run_config(self):
        """Test that run config is built correctly from scheduler config."""
        from posthog.dags.person_property_reconciliation import (
            ReconciliationSchedulerConfig,
            build_reconciliation_run_config,
        )

        config = ReconciliationSchedulerConfig(
            range_start=1,
            range_end=10000,
            chunk_size=1000,
            max_concurrent_jobs=5,
            max_concurrent_tasks=10,
            bug_window_start="2024-01-06 20:01:00",
            bug_window_end="2024-01-07 14:52:00",
            dry_run=False,
            backup_enabled=True,
            batch_size=100,
        )

        run_config = build_reconciliation_run_config(config, min_team_id=1, max_team_id=1000)

        assert run_config["ops"]["get_team_ids_to_reconcile"]["config"]["min_team_id"] == 1
        assert run_config["ops"]["get_team_ids_to_reconcile"]["config"]["max_team_id"] == 1000
        assert run_config["ops"]["get_team_ids_to_reconcile"]["config"]["bug_window_start"] == "2024-01-06 20:01:00"
        assert run_config["ops"]["get_team_ids_to_reconcile"]["config"]["dry_run"] is False
        assert run_config["ops"]["reconcile_team_chunk"]["config"]["backup_enabled"] is True
        assert run_config["execution"]["config"]["max_concurrent"] == 10  # max_concurrent_tasks

    def test_sensor_no_cursor_returns_skip_reason(self):
        """Test that sensor returns SkipReason when no cursor is set."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        context = build_sensor_context(cursor=None)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "No cursor set" in result.skip_message

    def test_sensor_invalid_cursor_json_returns_skip_reason(self):
        """Test that sensor returns SkipReason for invalid JSON cursor."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        context = build_sensor_context(cursor="not valid json {")
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "Invalid cursor JSON" in result.skip_message

    def test_sensor_completed_range_returns_skip_reason(self):
        """Test that sensor returns SkipReason when range is completed."""
        from dagster import DagsterInstance, SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "next_chunk_start": 1001,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "complete" in result.skip_message.lower()

    def test_sensor_at_max_concurrency_returns_skip_reason(self):
        """Test that sensor returns SkipReason when at max concurrency."""
        from dagster import DagsterInstance, SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 10000,
                "chunk_size": 1000,
                "max_concurrent_jobs": 2,
                "next_chunk_start": 1,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = [MagicMock(), MagicMock()]

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "max concurrency" in result.skip_message.lower()

    def test_sensor_yields_runs_up_to_available_slots(self):
        """Test that sensor yields correct number of runs based on available slots."""
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 5000,
                "chunk_size": 1000,
                "max_concurrent_jobs": 3,
                "next_chunk_start": 1,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = [MagicMock()]

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SensorResult)
        assert result.run_requests is not None
        assert len(result.run_requests) == 2
        assert result.run_requests[0].tags["reconciliation_range"] == "1-1000"
        assert result.run_requests[1].tags["reconciliation_range"] == "1001-2000"

        assert result.cursor is not None
        new_cursor = json.loads(result.cursor)
        assert new_cursor["next_chunk_start"] == 2001

    def test_sensor_handles_partial_final_chunk(self):
        """Test that sensor correctly handles a final chunk smaller than chunk_size."""
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1500,
                "chunk_size": 1000,
                "max_concurrent_jobs": 5,
                "next_chunk_start": 1001,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SensorResult)
        assert result.run_requests is not None
        assert len(result.run_requests) == 1
        assert result.run_requests[0].tags["reconciliation_range"] == "1001-1500"

        assert result.cursor is not None
        new_cursor = json.loads(result.cursor)
        assert new_cursor["next_chunk_start"] == 1501

    def test_sensor_run_request_has_correct_tags(self):
        """Test that run requests include expected tags."""
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 2000,
                "chunk_size": 1000,
                "max_concurrent_jobs": 5,
                "next_chunk_start": 1,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SensorResult)
        assert result.run_requests is not None
        assert len(result.run_requests) == 2
        assert result.run_requests[0].tags["reconciliation_range"] == "1-1000"
        assert result.run_requests[0].tags["owner"] == "team-ingestion"

    def test_sensor_validates_range_start_less_than_range_end(self):
        """Test that sensor rejects range_start > range_end."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1000,
                "range_end": 500,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "range_start" in result.skip_message
        assert "range_end" in result.skip_message

    def test_sensor_validates_chunk_size_positive(self):
        """Test that sensor rejects chunk_size <= 0."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "chunk_size": 0,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "chunk_size" in result.skip_message

    def test_sensor_validates_max_concurrent_jobs_positive(self):
        """Test that sensor rejects max_concurrent_jobs <= 0."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "max_concurrent_jobs": 0,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "max_concurrent_jobs" in result.skip_message

    def test_sensor_validates_max_concurrent_jobs_cap(self):
        """Test that sensor rejects max_concurrent_jobs exceeding the cap."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "max_concurrent_jobs": 100,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "exceeds cap" in result.skip_message.lower()

    def test_sensor_validates_max_concurrent_tasks_positive(self):
        """Test that sensor rejects max_concurrent_tasks <= 0."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "max_concurrent_tasks": 0,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "max_concurrent_tasks" in result.skip_message

    def test_sensor_validates_max_concurrent_tasks_cap(self):
        """Test that sensor rejects max_concurrent_tasks exceeding the cap."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "max_concurrent_tasks": 200,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "exceeds cap" in result.skip_message.lower()

    def test_sensor_validates_bug_window_start_required(self):
        """Test that sensor rejects missing bug_window_start."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "bug_window_start" in result.skip_message

    def test_sensor_validates_bug_window_end_required(self):
        """Test that sensor rejects missing bug_window_end."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "range_start": 1,
                "range_end": 1000,
                "bug_window_start": "2024-01-06 20:01:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "bug_window_end" in result.skip_message

    def test_build_reconciliation_run_config_with_team_ids(self):
        """Test that run config passes team_ids to op config when provided."""
        from posthog.dags.person_property_reconciliation import (
            ReconciliationSchedulerConfig,
            build_reconciliation_run_config,
        )

        config = ReconciliationSchedulerConfig(
            team_ids=[1, 5, 10, 20],
            chunk_size=100,
            max_concurrent_jobs=5,
            max_concurrent_tasks=10,
            bug_window_start="2024-01-06 20:01:00",
            bug_window_end="2024-01-07 14:52:00",
            dry_run=True,
            backup_enabled=False,
            batch_size=50,
        )

        run_config = build_reconciliation_run_config(config, team_ids=[1, 5, 10])

        op_config = run_config["ops"]["get_team_ids_to_reconcile"]["config"]
        assert op_config["team_ids"] == [1, 5, 10]
        assert "min_team_id" not in op_config
        assert "max_team_id" not in op_config
        assert op_config["bug_window_start"] == "2024-01-06 20:01:00"
        assert op_config["dry_run"] is True
        assert run_config["ops"]["reconcile_team_chunk"]["config"]["backup_enabled"] is False

    def test_sensor_with_team_ids_yields_chunked_runs(self):
        """Test that sensor chunks team_ids list correctly."""
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "team_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                "chunk_size": 3,
                "max_concurrent_jobs": 5,
                "next_team_index": 0,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SensorResult)
        assert result.run_requests is not None
        assert len(result.run_requests) == 4  # 10 teams / 3 per chunk = 4 chunks (3+3+3+1)
        assert result.run_requests[0].tags["reconciliation_team_ids_range"] == "0-2"
        assert result.run_requests[1].tags["reconciliation_team_ids_range"] == "3-5"
        assert result.run_requests[2].tags["reconciliation_team_ids_range"] == "6-8"
        assert result.run_requests[3].tags["reconciliation_team_ids_range"] == "9-9"

        # Verify first run config has correct team_ids chunk
        first_run_config = result.run_requests[0].run_config
        assert first_run_config["ops"]["get_team_ids_to_reconcile"]["config"]["team_ids"] == [1, 2, 3]

    def test_sensor_team_ids_mode_updates_cursor(self):
        """Test that sensor updates next_team_index in cursor."""
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "team_ids": [100, 200, 300, 400, 500],
                "chunk_size": 2,
                "max_concurrent_jobs": 2,  # Limit to 2 runs
                "next_team_index": 0,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SensorResult)
        assert result.run_requests is not None
        assert len(result.run_requests) == 2  # Limited by max_concurrent_jobs

        # Cursor should track progress
        assert result.cursor is not None
        new_cursor = json.loads(result.cursor)
        assert new_cursor["next_team_index"] == 4  # Processed 2 chunks of 2 = 4 teams

    def test_sensor_team_ids_completes_when_list_exhausted(self):
        """Test that sensor returns SkipReason when all team_ids are processed."""
        from dagster import DagsterInstance, SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "team_ids": [1, 2, 3],
                "chunk_size": 10,
                "next_team_index": 3,  # Already processed all 3
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "complete" in result.skip_message.lower()
        assert "3" in result.skip_message  # Should mention number of teams

    def test_sensor_validates_either_team_ids_or_range_required(self):
        """Test that sensor rejects cursor with neither team_ids nor range."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "chunk_size": 100,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "team_ids" in result.skip_message
        assert "range_start" in result.skip_message

    def test_sensor_validates_team_ids_and_range_mutually_exclusive(self):
        """Test that sensor rejects cursor with both team_ids and range."""
        from dagster import SkipReason, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "team_ids": [1, 2, 3],
                "range_start": 1,
                "range_end": 100,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )
        context = build_sensor_context(cursor=cursor)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SkipReason)
        assert result.skip_message is not None
        assert "both" in result.skip_message.lower()

    def test_sensor_team_ids_run_request_has_correct_tags(self):
        """Test that team_ids mode run requests include expected tags."""
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        from posthog.dags.person_property_reconciliation import person_property_reconciliation_scheduler

        cursor = json.dumps(
            {
                "team_ids": [10, 20, 30],
                "chunk_size": 2,
                "max_concurrent_jobs": 5,
                "next_team_index": 0,
                "bug_window_start": "2024-01-06 20:01:00",
                "bug_window_end": "2024-01-07 14:52:00",
            }
        )

        mock_instance = MagicMock(spec=DagsterInstance)
        mock_instance.get_run_records.return_value = []

        context = build_sensor_context(cursor=cursor, instance=mock_instance)
        result = person_property_reconciliation_scheduler(context)

        assert isinstance(result, SensorResult)
        assert result.run_requests is not None
        assert len(result.run_requests) == 2
        assert result.run_requests[0].tags["reconciliation_team_ids_range"] == "0-1"
        assert result.run_requests[0].tags["reconciliation_team_count"] == "2"
        assert result.run_requests[0].tags["owner"] == "team-ingestion"
