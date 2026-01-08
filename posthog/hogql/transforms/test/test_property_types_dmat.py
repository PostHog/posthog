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

from posthog.clickhouse.client import sync_execute
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.property_definition import PropertyType
from posthog.temporal.backfill_materialized_property.activities import (
    PROPERTY_TYPE_TO_COLUMN_NAME,
    _generate_property_extraction_sql,
)


class TestDmatIntegration(BaseTest):
    """Test that HogQL queries use dmat columns when available."""

    def test_uses_dmat_column_when_slot_ready(self):
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
            property_name=prop_def.name,
            property_type=PropertyType.Numeric,
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
        assert "dmat_numeric_3" in query, f"Expected dmat_numeric_3 in query but got: {query}"
        assert "JSONExtractRaw" not in query

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
            property_name=prop_def.name,
            property_type=PropertyType.Numeric,
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
        assert "dmat_numeric_0" not in query
        # Should use JSON extraction or properties access
        assert "properties" in query or "JSONExtractRaw" in query


@dataclass
class PropertyTestCase:
    """Single property edge case test."""

    name: str  # Property name (unique identifier)
    type: PropertyType  # Property type
    input_value: Any  # Value stored in JSON properties


TEST_CASES = [
    # String edge cases
    PropertyTestCase(name="str_normal", type=PropertyType.String, input_value="hello world"),
    PropertyTestCase(name="str_empty", type=PropertyType.String, input_value=""),
    PropertyTestCase(name="str_whitespace", type=PropertyType.String, input_value="   "),
    # Numeric edge cases
    PropertyTestCase(name="num_int", type=PropertyType.Numeric, input_value=42),
    PropertyTestCase(name="num_zero", type=PropertyType.Numeric, input_value=0),
    PropertyTestCase(name="num_negative", type=PropertyType.Numeric, input_value=-100),
    PropertyTestCase(name="num_float", type=PropertyType.Numeric, input_value=3.14159),
    PropertyTestCase(name="num_invalid", type=PropertyType.Numeric, input_value="not a number"),
    PropertyTestCase(name="num_whitespace", type=PropertyType.Numeric, input_value="  123  "),
    # Boolean edge cases
    PropertyTestCase(name="bool_true_str", type=PropertyType.Boolean, input_value="true"),
    PropertyTestCase(name="bool_false_str", type=PropertyType.Boolean, input_value="false"),
    PropertyTestCase(name="bool_true_int", type=PropertyType.Boolean, input_value="1"),
    PropertyTestCase(name="bool_false_int", type=PropertyType.Boolean, input_value="0"),
    PropertyTestCase(name="bool_invalid", type=PropertyType.Boolean, input_value="maybe"),
    # DateTime edge cases
    PropertyTestCase(name="dt_iso_full", type=PropertyType.Datetime, input_value="2024-01-15T10:30:00Z"),
    PropertyTestCase(name="dt_date_only", type=PropertyType.Datetime, input_value="2024-01-15"),
    PropertyTestCase(name="dt_invalid", type=PropertyType.Datetime, input_value="not a date"),
]


class TestDmatExtractionConsistency(ClickhouseTestMixin, APIBaseTest):
    """Test that dmat column extraction matches JSON extraction behavior."""

    def _build_slot_mapping(self):
        """Build mapping of test cases to dmat column names and slot indices.

        Returns dict: {test_case_name: {"col_name": str, "slot_idx": int}}
        """
        slot_counters = {
            PropertyType.String: 0,
            PropertyType.Numeric: 0,
            PropertyType.Boolean: 0,
            PropertyType.Datetime: 0,
        }

        mapping = {}
        for tc in TEST_CASES:
            slot_idx = slot_counters[tc.type]
            slot_counters[tc.type] += 1

            mapping[tc.name] = {
                "col_name": f"dmat_{PROPERTY_TYPE_TO_COLUMN_NAME[tc.type]}_{slot_idx}",
                "slot_idx": slot_idx,
            }

        return mapping

    @pytest.mark.django_db(transaction=True)
    def test_dmat_extraction_matches_json_for_all_property_types(self):
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
        from posthog.hogql.query import execute_hogql_query

        # Build test data
        event_properties = {tc.name: tc.input_value for tc in TEST_CASES}
        slot_mapping = self._build_slot_mapping()

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
        assert (
            result_json.clickhouse is not None and "dmat_" not in result_json.clickhouse
        ), "Should use JSON extraction, not dmat"
        json_results = result_json.results[0]

        # ============================================================
        # PHASE 2: Insert event with pre-filled dmat columns
        # ============================================================
        # Build INSERT statement with dmat columns computed via extraction SQL
        dmat_columns = []
        dmat_values = []
        for tc in TEST_CASES:
            dmat_columns.append(slot_mapping[tc.name]["col_name"])
            extraction_sql = _generate_property_extraction_sql(tc.type).replace("%(property_name)s", f"'{tc.name}'")
            dmat_values.append(extraction_sql)

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
                property_name=prop_defs[tc.name].name,
                property_type=tc.type,
                slot_index=slot_mapping[tc.name]["slot_idx"],
                state=MaterializedColumnSlotState.READY,
            )

        result_dmat = execute_hogql_query(
            f"SELECT {select_fields} FROM events WHERE event = 'dmat_event'",
            team=self.team,
        )

        # Verify dmat columns ARE used
        assert (
            result_dmat.clickhouse is not None and "dmat_" in result_dmat.clickhouse
        ), f"Should use dmat columns. SQL: {result_dmat.clickhouse}"
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
                        f"    dmat column: {slot_mapping[tc.name]['col_name']}"
                    )

            raise AssertionError(
                f"dmat extraction differs from JSON extraction!\n\n" f"Mismatches:\n" + "\n".join(failures)
            )
