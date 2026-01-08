"""Tests for the person property reconciliation job."""

from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

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
        mock_rows: list[tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]]]] = [
            (
                "018d1234-5678-0000-0000-000000000001",  # person_id (UUID as string)
                [  # set_diff - array of tuples (values are raw JSON)
                    ("email", '"new@example.com"', datetime(2024, 1, 15, 12, 0, 0)),
                    ("name", '"John Doe"', datetime(2024, 1, 15, 12, 30, 0)),
                ],
                [],  # set_once_diff - empty
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
        mock_rows: list[tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]]]] = [
            (
                "018d1234-5678-0000-0000-000000000002",
                [],  # set_diff - empty
                [  # set_once_diff - array of tuples (values are raw JSON)
                    ("initial_referrer", '"google.com"', datetime(2024, 1, 10, 8, 0, 0)),
                    ("first_seen", '"2024-01-10"', datetime(2024, 1, 10, 8, 0, 0)),
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
        mock_rows = [
            (
                "018d1234-5678-0000-0000-000000000003",
                [("email", '"updated@example.com"', datetime(2024, 1, 15, 12, 0, 0))],  # set_diff
                [("initial_source", '"organic"', datetime(2024, 1, 10, 8, 0, 0))],  # set_once_diff
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
        mock_rows = [
            (
                "018d1234-0000-0000-0000-000000000001",
                [("prop1", '"val1"', datetime(2024, 1, 15, 12, 0, 0))],
                [],
            ),
            (
                "018d1234-0000-0000-0000-000000000002",
                [("prop2", '"val2"', datetime(2024, 1, 15, 13, 0, 0))],
                [],
            ),
            (
                "018d1234-0000-0000-0000-000000000003",
                [],
                [("prop3", '"val3"', datetime(2024, 1, 10, 8, 0, 0))],
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
        """Test that persons with empty set_diff and set_once_diff are skipped."""
        mock_rows: list[tuple[str, list[tuple[str, Any, datetime]], list[tuple[str, Any, datetime]]]] = [
            (
                "018d1234-0000-0000-0000-000000000001",
                [],  # empty set_diff
                [],  # empty set_once_diff
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
        mock_rows = [
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
                [],
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

        success, result_data = update_person_with_version_check(
            cursor=cursor,
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

    def test_dry_run_does_not_write(self):
        """Test that dry_run=True doesn't execute UPDATE."""
        person_data = {
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

        success, result_data = update_person_with_version_check(
            cursor=cursor,
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

    def test_person_not_found(self):
        """Test handling when person doesn't exist in PG."""
        cursor = self.create_mock_cursor(person_data=None)

        updates = [
            PropertyUpdate(
                key="email", value="test@example.com", timestamp=datetime(2024, 1, 15, 12, 0, 0), operation="set"
            ),
        ]

        success, result_data = update_person_with_version_check(
            cursor=cursor,
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-nonexistent",
            property_updates=updates,
        )

        assert success is False
        assert result_data is None

    def test_no_changes_needed(self):
        """Test when reconciliation determines no changes are needed."""
        person_data = {
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

        success, result_data = update_person_with_version_check(
            cursor=cursor,
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
        )

        assert success is True
        assert result_data is None  # No changes, no Kafka publish needed

    def test_version_mismatch_retry(self):
        """Test retry on version mismatch (concurrent modification)."""
        person_data_v1 = {
            "uuid": "018d1234-5678-0000-0000-000000000001",
            "properties": {},
            "properties_last_updated_at": {},
            "properties_last_operation": {},
            "version": 1,
            "is_identified": False,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        person_data_v2 = {
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

        success, result_data = update_person_with_version_check(
            cursor=cursor,
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

        success, result_data = update_person_with_version_check(
            cursor=cursor,
            team_id=1,
            person_uuid="018d1234-5678-0000-0000-000000000001",
            property_updates=updates,
            max_retries=3,
        )

        assert success is False
        assert result_data is None


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
