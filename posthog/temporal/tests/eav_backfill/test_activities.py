"""End-to-end tests for EAV backfill with edge case property values."""

from datetime import UTC, datetime

import pytest
from posthog.test.base import _create_event, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.models.property_definition import PropertyType
from posthog.temporal.eav_backfill.activities import (
    BackfillEAVPropertyInputs,
    GetBackfillMonthsInputs,
    backfill_eav_property,
    get_backfill_months,
)


@pytest.mark.django_db(transaction=True)
class TestEAVBackfillEndToEnd:
    """
    Comprehensive end-to-end test for EAV backfill.

    Creates events with various edge case property values, runs backfill,
    and verifies the values in the event_properties table.
    """

    # Fixed month for all test events (January 2024)
    TEST_MONTH = 202401
    TEST_TIMESTAMP = datetime(2024, 1, 15, tzinfo=UTC)

    @pytest.fixture
    def create_events_with_properties(self, team):
        """Create events with various property values and return expected results."""
        # Define test cases: (property_name, property_type, input_value, expected_eav_value)
        # expected_eav_value of None means the row should NOT be inserted (filtered out)
        test_cases = [
            # Boolean edge cases (case-sensitive matching, consistent with HogQL)
            ("bool_true_lowercase", PropertyType.Boolean, True, 1),
            ("bool_false_lowercase", PropertyType.Boolean, False, 0),
            ("bool_true_string", PropertyType.Boolean, "true", 1),
            ("bool_false_string", PropertyType.Boolean, "false", 0),
            ("bool_TRUE_uppercase", PropertyType.Boolean, "TRUE", None),  # Case-sensitive: not recognized
            ("bool_FALSE_uppercase", PropertyType.Boolean, "FALSE", None),  # Case-sensitive: not recognized
            ("bool_1_int", PropertyType.Boolean, 1, None),  # Int 1 is not "true"
            ("bool_0_int", PropertyType.Boolean, 0, None),  # Int 0 is not "false"
            ("bool_1_string", PropertyType.Boolean, "1", None),  # String "1" is not "true"
            ("bool_0_string", PropertyType.Boolean, "0", None),  # String "0" is not "false"
            ("bool_yes", PropertyType.Boolean, "yes", None),  # Not recognized
            ("bool_no", PropertyType.Boolean, "no", None),  # Not recognized
            # Numeric edge cases
            ("num_int", PropertyType.Numeric, 42, 42.0),
            ("num_float", PropertyType.Numeric, 42.5, 42.5),
            ("num_negative", PropertyType.Numeric, -123.45, -123.45),
            ("num_zero", PropertyType.Numeric, 0, 0.0),
            ("num_string_int", PropertyType.Numeric, "100", 100.0),
            ("num_string_float", PropertyType.Numeric, "3.14159", 3.14159),
            ("num_string_negative", PropertyType.Numeric, "-50", -50.0),
            ("num_invalid_string", PropertyType.Numeric, "not_a_number", None),
            ("num_empty_string", PropertyType.Numeric, "", None),
            ("num_scientific", PropertyType.Numeric, "1.5e10", 1.5e10),
            # String edge cases
            # Note: JSONExtractRaw + replaceRegexpAll only strips outer quotes,
            # inner escaped characters remain escaped (consistent with HogQL printer)
            ("str_normal", PropertyType.String, "hello world", "hello world"),
            ("str_empty", PropertyType.String, "", ""),
            ("str_with_quotes", PropertyType.String, 'say "hello"', r"say \"hello\""),
            ("str_with_newline", PropertyType.String, "line1\nline2", r"line1\nline2"),
            ("str_unicode", PropertyType.String, "emoji 🎉 test", "emoji 🎉 test"),
            (
                "str_special_chars",
                PropertyType.String,
                "a'b\"c\\d",
                "a'b\\\"c\\\\d",
            ),  # single quotes not escaped in JSON
            ("str_number_as_string", PropertyType.String, "12345", "12345"),
            ("str_bool_as_string", PropertyType.String, "true", "true"),
            # DateTime edge cases
            # DateTime is stored as raw string (like traditional mat_* columns) to avoid
            # timezone interpretation issues. Conversion happens at query time.
            ("dt_iso_utc", PropertyType.Datetime, "2024-01-15T10:30:00Z", "2024-01-15T10:30:00Z"),
            ("dt_iso_offset", PropertyType.Datetime, "2024-01-15T10:30:00+05:00", "2024-01-15T10:30:00+05:00"),
            ("dt_date_only", PropertyType.Datetime, "2024-01-15", "2024-01-15"),
            ("dt_with_millis", PropertyType.Datetime, "2024-01-15T10:30:00.123Z", "2024-01-15T10:30:00.123Z"),
            ("dt_with_micros", PropertyType.Datetime, "2024-01-15T10:30:00.123456Z", "2024-01-15T10:30:00.123456Z"),
            ("dt_invalid", PropertyType.Datetime, "not a date", "not a date"),  # Stored as-is, validated at query time
            ("dt_unix_timestamp", PropertyType.Datetime, "1705315800", "1705315800"),  # Stored as-is
        ]

        # Create an event for each test case with a fixed timestamp
        created = []
        for prop_name, prop_type, input_value, expected in test_cases:
            event_uuid = _create_event(
                team=team,
                event="$test_event",
                distinct_id="test_user",
                properties={prop_name: input_value},
                timestamp=self.TEST_TIMESTAMP,
            )
            created.append((prop_name, prop_type, input_value, expected, event_uuid))

        flush_persons_and_events()
        return created

    def test_backfill_edge_cases(self, team, create_events_with_properties):
        """Test that backfill correctly handles all edge case values."""
        test_cases = create_events_with_properties

        # Run backfill for each property
        for prop_name, prop_type, _, _, _ in test_cases:
            backfill_eav_property(
                BackfillEAVPropertyInputs(
                    team_id=team.id,
                    property_name=prop_name,
                    property_type=str(prop_type),
                    month=self.TEST_MONTH,
                )
            )

        # Verify each property value in event_properties
        # Note: DateTime uses value_string (not a separate column) to match traditional mat_* column behavior
        value_column_map = {
            str(PropertyType.String): "value_string",
            str(PropertyType.Numeric): "value_numeric",
            str(PropertyType.Boolean): "value_bool",
            str(PropertyType.Datetime): "value_string",
        }

        for prop_name, prop_type, input_value, expected, event_uuid in test_cases:
            value_column = value_column_map[str(prop_type)]

            result = sync_execute(
                f"""
                SELECT {value_column} FROM event_properties
                WHERE team_id = %(team_id)s
                  AND key = %(prop_name)s
                  AND uuid = %(uuid)s
                """,
                {"team_id": team.id, "prop_name": prop_name, "uuid": event_uuid},
            )

            if expected is None:
                assert len(result) == 0, (
                    f"Property {prop_name} with value {input_value!r} should NOT have been inserted, but got {result}"
                )
            else:
                assert len(result) == 1, (
                    f"Property {prop_name} with value {input_value!r} should have been inserted, "
                    f"but got {len(result)} rows"
                )
                actual = result[0][0]

                # Handle datetime comparison (convert to string for comparison)
                if prop_type == PropertyType.Datetime:
                    actual_str = str(actual)[: len(expected)]
                    assert actual_str == expected, (
                        f"Property {prop_name}: expected {expected!r}, got {actual_str!r} (input was {input_value!r})"
                    )
                else:
                    assert actual == expected, (
                        f"Property {prop_name}: expected {expected!r}, got {actual!r} (input was {input_value!r})"
                    )


@pytest.mark.django_db(transaction=True)
class TestGetBackfillMonths:
    """Test the get_backfill_months activity."""

    def test_returns_distinct_months(self, team):
        """Test that get_backfill_months returns distinct months with property data."""
        # Create events in different months
        _create_event(
            team=team,
            event="$test",
            distinct_id="user1",
            properties={"plan": "free"},
            timestamp=datetime(2024, 1, 15, tzinfo=UTC),
        )
        _create_event(
            team=team,
            event="$test",
            distinct_id="user1",
            properties={"plan": "pro"},
            timestamp=datetime(2024, 1, 20, tzinfo=UTC),
        )
        _create_event(
            team=team,
            event="$test",
            distinct_id="user1",
            properties={"plan": "enterprise"},
            timestamp=datetime(2024, 3, 10, tzinfo=UTC),
        )
        # Event without the property - should not contribute a month
        _create_event(
            team=team,
            event="$test",
            distinct_id="user1",
            properties={"other_prop": "value"},
            timestamp=datetime(2024, 2, 15, tzinfo=UTC),
        )
        flush_persons_and_events()

        months = get_backfill_months(
            GetBackfillMonthsInputs(
                team_id=team.id,
                property_name="plan",
            )
        )

        # Should return Jan and Mar (202401, 202403), not Feb (no "plan" property)
        assert months == [202401, 202403]

    def test_returns_empty_list_when_no_data(self, team):
        """Test that get_backfill_months returns empty list when property has no data."""
        months = get_backfill_months(
            GetBackfillMonthsInputs(
                team_id=team.id,
                property_name="nonexistent_property",
            )
        )

        assert months == []


@pytest.mark.django_db(transaction=True)
class TestBackfillWithMonthFilter:
    """Test the month filtering in backfill_eav_property."""

    def test_backfill_only_specified_month(self, team):
        """Test that backfill with month parameter only processes that month."""
        # Create events in different months
        _create_event(
            team=team,
            event="$test",
            distinct_id="user1",
            properties={"status": "jan_event"},
            timestamp=datetime(2024, 1, 15, tzinfo=UTC),
        )
        _create_event(
            team=team,
            event="$test",
            distinct_id="user1",
            properties={"status": "feb_event"},
            timestamp=datetime(2024, 2, 15, tzinfo=UTC),
        )
        flush_persons_and_events()

        # Only backfill January
        backfill_eav_property(
            BackfillEAVPropertyInputs(
                team_id=team.id,
                property_name="status",
                property_type=str(PropertyType.String),
                month=202401,
            )
        )

        # Check what got inserted
        result = sync_execute(
            """
            SELECT value_string FROM event_properties
            WHERE team_id = %(team_id)s AND key = 'status'
            ORDER BY value_string
            """,
            {"team_id": team.id},
        )

        # Only January event should be backfilled
        assert len(result) == 1
        assert result[0][0] == "jan_event"

        # Now backfill February
        backfill_eav_property(
            BackfillEAVPropertyInputs(
                team_id=team.id,
                property_name="status",
                property_type=str(PropertyType.String),
                month=202402,
            )
        )

        # Check again - both should be present now
        result = sync_execute(
            """
            SELECT value_string FROM event_properties
            WHERE team_id = %(team_id)s AND key = 'status'
            ORDER BY value_string
            """,
            {"team_id": team.id},
        )

        assert len(result) == 2
        assert result[0][0] == "feb_event"
        assert result[1][0] == "jan_event"
