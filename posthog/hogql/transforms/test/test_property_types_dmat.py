"""Tests for dmat (dynamic materialized columns) integration in property type resolution."""

import json
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.temporal.backfill_materialized_property.activities import _generate_property_extraction_sql

from products.event_definitions.backend.models.property_definition import PropertyType


class TestDmatIntegration(BaseTest):
    """Test that HogQL queries use dmat columns when available."""

    def test_uses_dmat_string_column_when_slot_ready_for_numeric_property(self):
        """Test that property access uses dmat column when slot is READY."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name="revenue",
            property_type=PropertyType.Numeric,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=3,
            state=MaterializedColumnSlotState.READY,
        )

        expr = parse_select("SELECT properties.revenue FROM events")
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True),
            "clickhouse",
        )

        # Should use dmat column
        assert "dmat_string_3" in query, f"Expected dmat_string_3 in query but got: {query}"
        assert "JSONExtractRaw" not in query
        assert "accurateCastOrNull(events.dmat_string_3" in query, (
            f"Expected accurateCastOrNull wrapper around dmat_string_3 but got: {query}"
        )

    def test_falls_back_to_json_when_no_slot(self):
        """Test that property access falls back to JSON extraction when no slot exists."""
        PropertyDefinition.objects.create(
            team=self.team,
            name="custom_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        expr = parse_select("SELECT properties.custom_prop FROM events")
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True),
            "clickhouse",
        )

        # Should use JSON extraction (no dmat)
        assert "properties" in query or "JSONExtractRaw" in query
        assert "dmat_" not in query

    def test_ignores_slot_in_backfill_state(self):
        """Test that slots in BACKFILL state are not used."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="user_score",
            property_type=PropertyType.Numeric,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.BACKFILL,
        )

        expr = parse_select("SELECT properties.user_score FROM events")
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True),
            "clickhouse",
        )

        # Should NOT use dmat (slot is in BACKFILL state)
        assert "dmat_string_0" not in query
        # Should use JSON extraction or properties access
        assert "properties" in query or "JSONExtractRaw" in query


@dataclass
class PropertyTestCase:
    """Single property edge case test."""

    name: str  # Property name (unique identifier)
    type: PropertyType  # Property type
    input_value: Any  # Value stored in JSON properties


# Capped at 10 to fit the dmat slot pool (slot_index range 0..9 per the
# valid_slot_index check constraint). Picked to cover one representative case
# per type plus the trickier coercion paths for each.
TEST_CASES = [
    # String edge cases
    PropertyTestCase(name="str_normal", type=PropertyType.String, input_value="hello world"),
    PropertyTestCase(name="str_empty", type=PropertyType.String, input_value=""),
    # Numeric edge cases
    PropertyTestCase(name="num_int", type=PropertyType.Numeric, input_value=42),
    PropertyTestCase(name="num_negative", type=PropertyType.Numeric, input_value=-100),
    PropertyTestCase(name="num_invalid", type=PropertyType.Numeric, input_value="not a number"),
    # Boolean edge cases
    PropertyTestCase(name="bool_true_str", type=PropertyType.Boolean, input_value="true"),
    PropertyTestCase(name="bool_false_int", type=PropertyType.Boolean, input_value="0"),
    PropertyTestCase(name="bool_invalid", type=PropertyType.Boolean, input_value="maybe"),
    # DateTime edge cases
    PropertyTestCase(name="dt_iso_full", type=PropertyType.Datetime, input_value="2024-01-15T10:30:00Z"),
    PropertyTestCase(name="dt_invalid", type=PropertyType.Datetime, input_value="not a date"),
]


class TestDmatExtractionConsistency(ClickhouseTestMixin, APIBaseTest):
    """Test that dmat column extraction matches JSON extraction behavior."""

    @pytest.mark.django_db(transaction=True)
    def test_dmat_string_extraction_matches_json_for_all_property_types(self):
        """
        Verify dmat columns produce identical results to JSON extraction.

        This test does NOT test the backfill mutation process (for speed).
        Instead it:
        1. Inserts an event with JSON properties and queries it (baseline)
        2. Inserts an event with pre-filled dmat columns using the extraction SQL
        3. Creates MaterializedColumnSlot records so PropertySwapper detects them
        4. Queries the dmat event and verifies results match JSON results

        This ensures _generate_property_extraction_sql() produces the same output
        as HogQL's property type wrappers (toFloat, toBool, toDateTime).
        """
        # Build test data
        event_properties = {tc.name: tc.input_value for tc in TEST_CASES}
        slot_indexes = {tc.name: i for i, tc in enumerate(TEST_CASES)}

        # Create PropertyDefinitions (needed for MaterializedColumnSlot foreign key)
        prop_defs = {}
        for tc in TEST_CASES:
            prop_defs[tc.name] = PropertyDefinition.objects.create(
                team=self.team,
                name=tc.name,
                property_type=tc.type,
                type=PropertyDefinition.Type.EVENT,
            )

        # ============================================================
        # PHASE 1: Establish baseline using JSON extraction
        # ============================================================
        _create_event(
            team=self.team,
            distinct_id="user1",
            event="json_event",
            properties=event_properties,
        )
        flush_persons_and_events()

        select_fields = ", ".join([f"properties.{tc.name}" for tc in TEST_CASES])
        result_json = execute_hogql_query(
            f"SELECT {select_fields} FROM events WHERE event = 'json_event'",
            team=self.team,
        )

        # Verify no dmat columns used (sanity check)
        assert result_json.clickhouse is not None and "dmat_" not in result_json.clickhouse, (
            "Should use JSON extraction, not dmat"
        )
        json_results = result_json.results[0]

        # ============================================================
        # PHASE 2: Insert event with pre-filled dmat columns
        # ============================================================
        # Build INSERT statement with dmat columns computed via extraction SQL
        extraction_sql = _generate_property_extraction_sql()
        dmat_columns = [f"dmat_string_{slot_indexes[tc.name]}" for tc in TEST_CASES]
        dmat_values = [extraction_sql.replace("%(property_name)s", f"'{tc.name}'") for tc in TEST_CASES]

        sync_execute(
            f"""
            INSERT INTO sharded_events (
                uuid, team_id, event, distinct_id, timestamp, properties,
                {", ".join(dmat_columns)}
            )
            SELECT
                %(uuid)s,
                %(team_id)s,
                'dmat_event',
                'user1',
                now(),
                %(properties)s,
                {", ".join(dmat_values)}
            FROM (SELECT %(properties)s as properties)
        """,
            {
                "team_id": self.team.pk,
                "properties": json.dumps(event_properties),
                "uuid": str(uuid.uuid4()),
            },
            flush=False,
        )

        # ============================================================
        # PHASE 3: Create slots and query with dmat columns
        # ============================================================
        # Create MaterializedColumnSlot records so PropertySwapper detects dmat columns
        for tc in TEST_CASES:
            MaterializedColumnSlot.objects.create(
                team=self.team,
                property_definition=prop_defs[tc.name],
                slot_index=slot_indexes[tc.name],
                state=MaterializedColumnSlotState.READY,
            )

        result_dmat = execute_hogql_query(
            f"SELECT {select_fields} FROM events WHERE event = 'dmat_event'",
            team=self.team,
        )

        # Verify dmat columns ARE used
        assert result_dmat.clickhouse is not None and "dmat_" in result_dmat.clickhouse, (
            f"Should use dmat columns. SQL: {result_dmat.clickhouse}"
        )
        dmat_results = result_dmat.results[0]

        # ============================================================
        # VERIFICATION: Results must be identical
        # ============================================================
        if json_results != dmat_results:
            # Provide detailed comparison on failure
            failures = []
            for i, tc in enumerate(TEST_CASES):
                json_val = json_results[i]
                dmat_val = dmat_results[i]
                if json_val != dmat_val:
                    failures.append(
                        f"  {tc.name} ({tc.type}):\n"
                        f"    Input:       {tc.input_value!r}\n"
                        f"    JSON result: {json_val!r}\n"
                        f"    dmat result: {dmat_val!r}\n"
                        f"    dmat column: dmat_string_{slot_indexes[tc.name]}"
                    )

            raise AssertionError(
                f"dmat extraction differs from JSON extraction!\n\nMismatches:\n" + "\n".join(failures)
            )
