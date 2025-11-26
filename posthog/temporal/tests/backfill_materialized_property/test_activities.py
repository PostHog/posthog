"""Tests for backfill materialized property activities."""

import pytest
from unittest.mock import patch

from posthog.models import MaterializedColumnSlotState
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
            ("DateTime", ["coalesce(", "parseDateTimeBestEffortOrNull("]),
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

    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_backfill_executes_alter_table(self, mock_sync_execute, activity_environment):
        """Test that backfill executes ALTER TABLE UPDATE with parameterized property_name."""
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=123,
                property_name="test_prop",
                property_type="String",
                mat_column_name="dmat_string_0",
            ),
        )

        # Verify sync_execute was called with ALTER TABLE UPDATE
        assert mock_sync_execute.called
        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        assert "ALTER TABLE sharded_events" in query
        assert "UPDATE dmat_string_0" in query
        assert "WHERE team_id = %(team_id)s" in query
        # Property name should be parameterized, not interpolated
        assert "%(property_name)s" in query
        assert "test_prop" not in query  # Should NOT be in SQL directly
        assert params["property_name"] == "test_prop"
        assert params["team_id"] == 123

    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_backfill_with_partition_id(self, mock_sync_execute, activity_environment):
        """Test backfilling a specific partition with parameterized partition_id."""
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=123,
                property_name="test_prop",
                property_type="String",
                mat_column_name="dmat_string_0",
                partition_id="202401",
            ),
        )

        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        # Partition ID should be parameterized
        assert "IN PARTITION %(partition_id)s" in query
        assert "'202401'" not in query  # Should NOT be in SQL directly
        assert params["partition_id"] == "202401"

    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_backfill_without_partition_id(self, mock_sync_execute, activity_environment):
        """Test backfilling all partitions (partition_id=None)."""
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=123,
                property_name="test_prop",
                property_type="String",
                mat_column_name="dmat_string_0",
                partition_id=None,
            ),
        )

        query = mock_sync_execute.call_args[0][0]
        params = mock_sync_execute.call_args[0][1]

        # Should NOT have partition clause
        assert "IN PARTITION" not in query
        assert "partition_id" not in params

    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_backfill_clickhouse_error(self, mock_sync_execute, activity_environment):
        """Test error handling when ClickHouse query fails."""
        mock_sync_execute.side_effect = Exception("ClickHouse connection failed")

        with pytest.raises(Exception, match="ClickHouse connection failed"):
            activity_environment.run(
                backfill_materialized_column,
                BackfillMaterializedColumnInputs(
                    team_id=123,
                    property_name="test_prop",
                    property_type="String",
                    mat_column_name="dmat_string_0",
                ),
            )

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
    def test_backfill_special_characters_in_property_name_are_parameterized(
        self, mock_sync_execute, activity_environment, property_name
    ):
        """Test that property names with special characters are safely parameterized.

        This ensures SQL injection is not possible through property names.
        The property name should NEVER appear directly in the SQL query - it must
        only be passed through the params dict for safe escaping by ClickHouse.
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
        # It should only be in the params dict
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
