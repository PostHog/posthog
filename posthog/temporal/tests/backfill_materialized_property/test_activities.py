"""Tests for backfill materialized property activities."""

import json
import uuid

import pytest
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.models import MaterializedColumnSlotState
from posthog.models.property_definition import PropertyType
from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    UpdateSlotStateInputs,
    _generate_property_extraction_sql,
    backfill_materialized_column,
    update_slot_state,
)


@pytest.mark.django_db(transaction=True)
class TestPropertyExtractionSQL:
    """Test SQL generation for extracting properties."""

    @pytest.mark.parametrize(
        "property_type,expected_fragments",
        [
            # String type uses base extraction with nullIf handling (HogQL pattern)
            ("String", ["replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(property_name)s)", "'null')"]),
            ("Numeric", ["toFloat64OrNull("]),
            ("Boolean", ["transform(toString(", "['true', 'false'], [1, 0], NULL)"]),
            ("DateTime", ["parseDateTime64BestEffortOrNull(", ", 6)"]),
        ],
    )
    def test_property_extraction_sql_generation(
        self,
        property_type,
        expected_fragments,
    ):
        """Test that SQL uses parameterized placeholder for property_name."""
        sql = _generate_property_extraction_sql(property_type)
        for fragment in expected_fragments:
            assert fragment in sql, f"Expected '{fragment}' in SQL: {sql}"
        # All types should use the parameterized placeholder
        assert "%(property_name)s" in sql, f"Expected parameterized property_name in SQL: {sql}"

    def test_property_extraction_unsupported_type(self):
        """Test that unsupported property types raise error."""
        with pytest.raises(ValueError, match="Unsupported property type"):
            _generate_property_extraction_sql("UnsupportedType")


@pytest.mark.django_db(transaction=True)
class TestBackfillMaterializedColumn:
    """Test backfill_materialized_column activity."""

    @pytest.mark.parametrize(
        "property_name",
        [
            "test'prop",  # Single quote - would break unparameterized SQL
            'test"prop',  # Double quote
            "test\\prop",  # Backslash
            "$feature/my-flag",  # Feature flag format with special chars
            "prop'); DROP TABLE events; --",  # SQL injection attempt
        ],
    )
    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_property_name_is_parameterized_not_interpolated(
        self, mock_sync_execute, activity_environment, property_name
    ):
        """Test that property names are parameterized, preventing SQL injection.

        The property name should NEVER appear directly in the SQL query string.
        This is a security test - we mock sync_execute to inspect the raw SQL.
        """
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=123,
                property_name=property_name,
                property_type="String",
                mat_column_name="dmat_string_0",
            ),
        )

        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        # Property name should NEVER be in the SQL string directly
        assert property_name not in query, f"Property name '{property_name}' should not be in SQL: {query}"
        # It should use a parameterized placeholder
        assert "%(property_name)s" in query
        # And the actual value should be in params
        assert params["property_name"] == property_name


@pytest.mark.django_db(transaction=True)
class TestUpdateSlotState:
    """Test update_slot_state activity."""

    @pytest.mark.parametrize(
        "new_state,error_message",
        [
            ("READY", None),
            ("ERROR", "Something went wrong"),
            ("BACKFILL", None),
        ],
    )
    def test_update_slot_state(
        self,
        materialized_slot,
        activity_environment,
        new_state,
        error_message,
    ):
        """Test updating slot state."""
        result = activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(
                slot_id=str(materialized_slot.id),
                state=new_state,
                error_message=error_message,
            ),
        )

        assert result is True

        # Verify state was updated
        materialized_slot.refresh_from_db()
        assert materialized_slot.state == new_state

        if error_message:
            assert materialized_slot.error_message == error_message

    def test_update_slot_state_clears_error_on_backfill(self, materialized_slot_error, activity_environment):
        """Test that transitioning to BACKFILL clears error_message."""
        assert materialized_slot_error.error_message is not None

        activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(
                slot_id=str(materialized_slot_error.id),
                state="BACKFILL",
            ),
        )

        materialized_slot_error.refresh_from_db()
        assert materialized_slot_error.state == MaterializedColumnSlotState.BACKFILL
        assert materialized_slot_error.error_message is None

    def test_update_slot_state_not_found(self, activity_environment):
        """Test that activity returns False when slot not found."""
        result = activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(
                slot_id="00000000-0000-0000-0000-000000000000",
                state="READY",
            ),
        )

        assert result is False


@pytest.mark.django_db(transaction=True)
class TestBackfillMaterializedColumnClickHouse:
    """Integration tests that run against real ClickHouse."""

    @pytest.mark.parametrize(
        "property_type,property_value,mat_column,expected_value",
        [
            (PropertyType.String, "hello_world", "dmat_string_0", "hello_world"),
            (PropertyType.Numeric, "42.5", "dmat_numeric_0", 42.5),
            (PropertyType.Boolean, "true", "dmat_bool_0", 1),
            (PropertyType.Boolean, "false", "dmat_bool_0", 0),
        ],
    )
    def test_backfill_populates_materialized_column(
        self,
        team,
        activity_environment,
        property_type,
        property_value,
        mat_column,
        expected_value,
    ):
        """
        Test that backfill activity actually populates dmat columns in ClickHouse.

        1. Insert event with property (dmat column will be empty)
        2. Run backfill activity
        3. Verify dmat column is now populated
        """
        property_name = f"test_prop_{uuid.uuid4().hex[:8]}"
        event_uuid = str(uuid.uuid4())

        # Insert event with the property
        sync_execute(
            """
            INSERT INTO sharded_events (
                uuid, team_id, event, distinct_id, properties, timestamp, created_at
            ) VALUES (
                %(uuid)s, %(team_id)s, %(event)s, %(distinct_id)s, %(properties)s, now(), now()
            )
            """,
            {
                "uuid": event_uuid,
                "team_id": team.id,
                "event": "$test_event",
                "distinct_id": "test_user",
                "properties": f'{{"{property_name}": "{property_value}"}}',
            },
        )

        # Verify dmat column is empty before backfill
        result_before = sync_execute(
            f"SELECT {mat_column} FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid, "team_id": team.id},
        )
        # Empty string for String, 0 for Numeric, 0 for Bool
        assert result_before[0][0] in ("", 0, None), f"{mat_column} should be empty before backfill"

        # Run backfill
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
                property_type=str(property_type),
                mat_column_name=mat_column,
            ),
        )

        # Verify dmat column is now populated
        result_after = sync_execute(
            f"SELECT {mat_column} FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid, "team_id": team.id},
        )
        assert (
            result_after[0][0] == expected_value
        ), f"{mat_column} should be {expected_value}, got {result_after[0][0]}"

    @pytest.mark.parametrize(
        "property_name",
        [
            "test'prop",  # Single quote
            'test"prop',  # Double quote
            "test\\prop",  # Backslash
            "$feature/my-flag",  # Feature flag format
            "prop with spaces",  # Spaces
            "emoji_🎉_prop",  # Unicode
        ],
    )
    def test_backfill_handles_special_characters_in_property_name(self, team, activity_environment, property_name):
        """Test that property names with special characters work correctly in ClickHouse."""
        event_uuid = str(uuid.uuid4())
        expected_value = "test_value"

        properties_json = json.dumps({property_name: expected_value})

        sync_execute(
            """
            INSERT INTO sharded_events (
                uuid, team_id, event, distinct_id, properties, timestamp, created_at
            ) VALUES (
                %(uuid)s, %(team_id)s, %(event)s, %(distinct_id)s, %(properties)s, now(), now()
            )
            """,
            {
                "uuid": event_uuid,
                "team_id": team.id,
                "event": "$test_event",
                "distinct_id": "test_user",
                "properties": properties_json,
            },
        )

        # Run backfill
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
                property_type=str(PropertyType.String),
                mat_column_name="dmat_string_0",
            ),
        )

        # Verify backfill worked
        result = sync_execute(
            "SELECT dmat_string_0 FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid, "team_id": team.id},
        )
        assert result[0][0] == expected_value, f"Backfill should work for property name: {property_name}"

    def test_backfill_handles_missing_property(self, team, activity_environment):
        """Test that backfill leaves dmat column empty when property doesn't exist on event."""
        property_name = f"nonexistent_prop_{uuid.uuid4().hex[:8]}"
        event_uuid = str(uuid.uuid4())

        # Insert event WITHOUT the property
        sync_execute(
            """
            INSERT INTO sharded_events (
                uuid, team_id, event, distinct_id, properties, timestamp, created_at
            ) VALUES (
                %(uuid)s, %(team_id)s, %(event)s, %(distinct_id)s, %(properties)s, now(), now()
            )
            """,
            {
                "uuid": event_uuid,
                "team_id": team.id,
                "event": "$test_event",
                "distinct_id": "test_user",
                "properties": '{"other_prop": "value"}',
            },
        )

        # Run backfill for a property that doesn't exist on this event
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
                property_type=str(PropertyType.String),
                mat_column_name="dmat_string_0",
            ),
        )

        # Verify dmat column is NULL (extraction SQL returns NULL for missing properties)
        result = sync_execute(
            "SELECT dmat_string_0 FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid, "team_id": team.id},
        )
        assert result[0][0] is None, "dmat_string_0 should be NULL for missing property"

    def test_backfill_only_affects_team_events(self, team, organization, activity_environment):
        """Test that backfill only updates events for the specified team."""
        from posthog.models import Team

        # Create a second team
        other_team = Team.objects.create(organization=organization, name="Other Team")

        property_name = f"test_prop_{uuid.uuid4().hex[:8]}"
        event_uuid_team1 = str(uuid.uuid4())
        event_uuid_team2 = str(uuid.uuid4())

        # Insert events for both teams
        for event_uuid, tid in [(event_uuid_team1, team.id), (event_uuid_team2, other_team.id)]:
            sync_execute(
                """
                INSERT INTO sharded_events (
                    uuid, team_id, event, distinct_id, properties, timestamp, created_at
                ) VALUES (
                    %(uuid)s, %(team_id)s, %(event)s, %(distinct_id)s, %(properties)s, now(), now()
                )
                """,
                {
                    "uuid": event_uuid,
                    "team_id": tid,
                    "event": "$test_event",
                    "distinct_id": "test_user",
                    "properties": f'{{"{property_name}": "test_value"}}',
                },
            )

        # Run backfill only for team1
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
                property_type=str(PropertyType.String),
                mat_column_name="dmat_string_0",
            ),
        )

        # Verify team1's event was backfilled
        result_team1 = sync_execute(
            "SELECT dmat_string_0 FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid_team1, "team_id": team.id},
        )
        assert result_team1[0][0] == "test_value", "team1 event should be backfilled"

        # Verify team2's event was NOT backfilled (column stays at default NULL)
        result_team2 = sync_execute(
            "SELECT dmat_string_0 FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid_team2, "team_id": other_team.id},
        )
        assert result_team2[0][0] is None, "team2 event should NOT be backfilled"

    def test_backfill_invalid_property_type_raises_error(self, team, activity_environment):
        """Test that an invalid property type raises an error."""
        with pytest.raises(ValueError, match="Unsupported property type"):
            activity_environment.run(
                backfill_materialized_column,
                BackfillMaterializedColumnInputs(
                    team_id=team.id,
                    property_name="test_prop",
                    property_type="InvalidType",
                    mat_column_name="dmat_string_0",
                ),
            )
