"""Tests for backfill materialized property activities."""

import pytest
from unittest.mock import patch

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState
from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    GetSlotDetailsInputs,
    UpdateSlotStateInputs,
    _generate_property_extraction_sql,
    backfill_materialized_column,
    get_slot_details,
    update_slot_state,
)


@pytest.mark.django_db(transaction=True)
class TestGetSlotDetails:
    """Test get_slot_details activity."""

    def test_get_slot_details_success(self, materialized_slot, activity_environment):
        """Test successfully retrieving slot details."""
        result = activity_environment.run(
            get_slot_details,
            GetSlotDetailsInputs(slot_id=str(materialized_slot.id)),
        )

        assert result.team_id == materialized_slot.team_id
        assert result.property_name == materialized_slot.property_definition.name
        assert result.property_type == materialized_slot.property_type
        assert result.slot_index == materialized_slot.slot_index
        assert result.mat_column_name == "dmat_string_0"

    def test_get_slot_details_slot_not_found(self, activity_environment):
        """Test error when slot doesn't exist."""
        with pytest.raises(ValueError, match="MaterializedColumnSlot .* not found"):
            activity_environment.run(
                get_slot_details,
                GetSlotDetailsInputs(slot_id="00000000-0000-0000-0000-000000000000"),
            )

    @pytest.mark.parametrize(
        "property_type,slot_index,expected_column_name",
        [
            ("String", 0, "dmat_string_0"),
            ("String", 5, "dmat_string_5"),
            ("Numeric", 0, "dmat_numeric_0"),
            ("Numeric", 9, "dmat_numeric_9"),
            ("Boolean", 0, "dmat_bool_0"),
            ("Boolean", 3, "dmat_bool_3"),
            ("DateTime", 0, "dmat_datetime_0"),
            ("DateTime", 7, "dmat_datetime_7"),
        ],
    )
    def test_column_name_generation(
        self,
        team,
        activity_environment,
        property_type,
        slot_index,
        expected_column_name,
        string_property_definition,
        numeric_property_definition,
        boolean_property_definition,
        datetime_property_definition,
    ):
        """Test that column names are generated correctly for each property type."""
        # Select the right property definition for this type
        prop_def_map = {
            "String": string_property_definition,
            "Numeric": numeric_property_definition,
            "Boolean": boolean_property_definition,
            "DateTime": datetime_property_definition,
        }
        prop_def = prop_def_map[property_type]
        prop_def.property_type = property_type
        prop_def.save()

        slot = MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            property_type=property_type,
            slot_index=slot_index,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        result = activity_environment.run(
            get_slot_details,
            GetSlotDetailsInputs(slot_id=str(slot.id)),
        )

        assert result.mat_column_name == expected_column_name


@pytest.mark.django_db(transaction=True)
class TestPropertyExtractionSQL:
    """Test SQL generation for extracting properties."""

    @pytest.mark.parametrize(
        "property_name,property_type,expected_sql_fragment",
        [
            # String property - should use trim_quotes_expr
            ("custom_prop", "String", "trim(BOTH '\"' FROM JSONExtractRaw(properties, 'custom_prop'))"),
            # Numeric property - should convert to Float64
            ("revenue", "Numeric", "toFloat64OrNull(replaceRegexpAll("),
            # Boolean property - should use CASE expression
            ("is_active", "Boolean", "CASE"),
            ("is_active", "Boolean", "WHEN JSONExtractRaw(properties, 'is_active') IN ('true', '1') THEN 1"),
            # DateTime property - should use parseDateTimeBestEffortOrNull
            ("last_login", "DateTime", "coalesce("),
            ("last_login", "DateTime", "parseDateTimeBestEffortOrNull("),
        ],
    )
    def test_property_extraction_sql_generation(
        self,
        property_name,
        property_type,
        expected_sql_fragment,
    ):
        """Test that SQL extraction expressions are generated correctly."""
        sql = _generate_property_extraction_sql(property_name, property_type)
        assert expected_sql_fragment in sql

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
        assert "AND partition = '202401'" in query

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
        assert "AND partition" not in query

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
