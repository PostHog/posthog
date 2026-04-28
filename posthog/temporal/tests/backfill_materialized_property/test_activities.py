"""Tests for backfill materialized property activities."""

import uuid

import pytest
from posthog.test.base import _create_event, flush_persons_and_events
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState
from posthog.temporal.backfill_materialized_property.activities import (
    BackfillMaterializedColumnInputs,
    UpdateSlotStateInputs,
    _generate_property_extraction_sql,
    backfill_materialized_column,
    update_slot_state,
)


@pytest.mark.django_db(transaction=True)
class TestPropertyExtractionSQL:
    def test_property_extraction_sql_generation(self):
        sql = _generate_property_extraction_sql()
        # SQL must:
        #   - use the same JSONExtractRaw + nullIf-empty + nullIf-'null' shape as the HogQL
        #     printer's `_unsafe_json_extract_trim_quotes` and plugin-server's
        #     `jsonExtractRawAndTrimQuotes` — see the parity fixture for the contract,
        #   - parameterize property_name (we don't allow user-supplied keys to be inlined
        #     because property names contain quotes / slashes / etc).
        assert "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(property_name)s)" in sql
        assert "'null')" in sql
        assert "%(property_name)s" in sql


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
    @patch("posthog.temporal.backfill_materialized_property.activities.get_cluster")
    def test_property_name_is_parameterized_not_interpolated(
        self, mock_get_cluster, activity_environment, property_name
    ):
        """Test that property names are parameterized, preventing SQL injection."""
        from unittest.mock import MagicMock

        mock_cluster = mock_get_cluster.return_value
        mock_cluster.map_one_host_per_shard.return_value.result.return_value = {}

        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=123,
                property_name=property_name,
                mat_column_name="dmat_string_0",
            ),
        )

        # Get the function passed to map_one_host_per_shard and call it with a mock client
        run_mutation_fn = mock_cluster.map_one_host_per_shard.call_args[0][0]
        mock_client = MagicMock()
        run_mutation_fn(mock_client)

        # Check what client.execute was called with
        call_args = mock_client.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]

        # Property name should NEVER be in the SQL query directly
        assert property_name not in query, f"Property name '{property_name}' should not be in SQL: {query}"
        # It should use a parameterized placeholder
        assert "%(property_name)s" in query
        # And the actual value should be in params
        assert params["property_name"] == property_name
        # Should use mutations_sync=1
        assert call_args[1]["settings"]["mutations_sync"] == 1


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
        activity_environment.run(
            update_slot_state,
            UpdateSlotStateInputs(
                slot_id=str(materialized_slot.id),
                state=new_state,
                error_message=error_message,
            ),
        )

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

    def test_update_slot_state_not_found_raises(self, activity_environment):
        # Missing slot at this point means an operator deleted the row mid-backfill;
        # the activity must surface that as an error rather than silently no-op.
        with pytest.raises(MaterializedColumnSlot.DoesNotExist):
            activity_environment.run(
                update_slot_state,
                UpdateSlotStateInputs(
                    slot_id="00000000-0000-0000-0000-000000000000",
                    state="READY",
                ),
            )


@pytest.mark.django_db(transaction=True)
class TestBackfillMaterializedColumnClickHouse:
    """Integration tests that run against real ClickHouse."""

    def test_backfill_populates_materialized_column(self, team, activity_environment):
        """End-to-end: insert event, run backfill, dmat_string column reflects the value verbatim.

        Per the RFC, every dmat column is `Nullable(String)` and the backfill writes the raw
        extracted string. HogQL applies `toFloat`/`toBool`/`parseDateTime64BestEffortOrNull` at
        read time using the same wrapper it uses for normal `mat_*` columns — so type-specific
        values (e.g. '42.5', 'true') are not asserted here; that's covered at the HogQL layer.
        """
        property_name = f"test_prop_{uuid.uuid4().hex[:8]}"
        property_value = "hello_world"
        event_uuid = _create_event(
            team=team,
            event="$test_event",
            distinct_id="test_user",
            properties={property_name: property_value},
        )
        flush_persons_and_events()

        result_before = sync_execute(
            "SELECT dmat_string_0 FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid, "team_id": team.id},
        )
        assert result_before[0][0] in ("", None)

        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
                mat_column_name="dmat_string_0",
            ),
        )

        result_after = sync_execute(
            "SELECT dmat_string_0 FROM sharded_events WHERE uuid = %(uuid)s AND team_id = %(team_id)s",
            {"uuid": event_uuid, "team_id": team.id},
        )
        assert result_after[0][0] == property_value

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
        expected_value = "test_value"
        event_uuid = _create_event(
            team=team,
            event="$test_event",
            distinct_id="test_user",
            properties={property_name: expected_value},
        )
        flush_persons_and_events()

        # Run backfill
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
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

        # Insert event WITHOUT the property
        event_uuid = _create_event(
            team=team,
            event="$test_event",
            distinct_id="test_user",
            properties={"other_prop": "value"},
        )
        flush_persons_and_events()

        # Run backfill for a property that doesn't exist on this event
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
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

        # Insert events for both teams
        event_uuid_team1 = _create_event(
            team=team,
            event="$test_event",
            distinct_id="test_user",
            properties={property_name: "test_value"},
        )
        event_uuid_team2 = _create_event(
            team=other_team,
            event="$test_event",
            distinct_id="test_user",
            properties={property_name: "test_value"},
        )
        flush_persons_and_events()

        # Run backfill only for team1
        activity_environment.run(
            backfill_materialized_column,
            BackfillMaterializedColumnInputs(
                team_id=team.id,
                property_name=property_name,
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
