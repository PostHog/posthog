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
        "property_name,property_type,expected_fragments",
        [
            ("custom_prop", "String", ["replaceRegexpAll(JSONExtractRaw(properties, 'custom_prop')"]),
            ("revenue", "Numeric", ["toFloat64OrNull("]),
            ("is_active", "Boolean", ["transform(toString(", "['true', 'false'], [1, 0], NULL)"]),
            ("last_login", "DateTime", ["coalesce(", "parseDateTimeBestEffortOrNull("]),
        ],
    )
    def test_property_extraction_sql_generation(
        self,
        property_name,
        property_type,
        expected_fragments,
    ):
        sql = _generate_property_extraction_sql(property_name, property_type)
        for fragment in expected_fragments:
            assert fragment in sql, f"Expected '{fragment}' in SQL: {sql}"

    def test_property_extraction_unsupported_type(self):
        """Test that unsupported property types raise error."""
        with pytest.raises(ValueError, match="Unsupported property type"):
            _generate_property_extraction_sql("prop", "UnsupportedType")


@pytest.mark.django_db(transaction=True)
class TestBackfillMaterializedColumn:
    """Test backfill_materialized_column activity."""

    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_backfill_executes_alter_table(self, mock_sync_execute, activity_environment):
        """Test that backfill executes ALTER TABLE UPDATE."""
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
        assert "ALTER TABLE sharded_events" in query
        assert "UPDATE dmat_string_0" in query
        assert "WHERE team_id = %(team_id)s" in query

    @patch("posthog.temporal.backfill_materialized_property.activities.sync_execute")
    def test_backfill_with_partition_id(self, mock_sync_execute, activity_environment):
        """Test backfilling a specific partition."""
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
        assert "IN PARTITION '202401'" in query

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
        # Should NOT have partition clause
        assert "IN PARTITION" not in query

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
