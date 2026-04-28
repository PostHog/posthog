"""Tests for dmat (dynamic materialized columns) integration in property type resolution.

Per the dmat RFC, every dmat column is `Nullable(String)` (`dmat_string_<index>`); HogQL
applies the per-property-type wrapper (`toFloat` / `toBool` / `toDateTime`) at read time
the same way it does for normal `mat_*` columns. These tests pin both the rewriting
behaviour and the read-time consistency between the dmat path and the JSON-fallback path.
"""

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
from posthog.temporal.backfill_materialized_property.activities import _generate_property_extraction_sql

from products.event_definitions.backend.models.property_definition import PropertyType


class TestDmatIntegration(BaseTest):
    def test_uses_dmat_string_column_when_slot_ready_for_numeric_property(self):
        # Numeric property → still reads from `dmat_string_3` (all dmat cols are String);
        # the toFloat wrapper is what makes it numeric at read time.
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

        assert "dmat_string_3" in query, f"Expected dmat_string_3 in query but got: {query}"
        assert "JSONExtractRaw" not in query
        # The Numeric wrapper is applied at read time, exactly like the JSON-fallback path.
        # The HogQL printer compiles `toFloat(...)` down to `accurateCastOrNull(<col>, 'Float64')`
        # — the type is then parameterized as `%(hogql_val_*)s`. We only check that the cast
        # is wrapped around the dmat column; the type-string parameterization is a printer
        # detail covered elsewhere.
        assert "accurateCastOrNull(events.dmat_string_3" in query, (
            f"Expected accurateCastOrNull wrapper around dmat_string_3 but got: {query}"
        )

    def test_falls_back_to_json_when_no_slot(self):
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

        assert "properties" in query or "JSONExtractRaw" in query
        assert "dmat_" not in query

    def test_ignores_slot_in_backfill_state(self):
        # BACKFILL means ingestion is dual-writing but the historical mutation hasn't
        # finished, so the column has gaps — HogQL must keep reading via JSON until READY.
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

        assert "dmat_string_0" not in query
        assert "properties" in query or "JSONExtractRaw" in query


@dataclass
class PropertyTestCase:
    name: str
    type: PropertyType
    input_value: Any


# Spans every property type because that's the whole point of the consistency test:
# the JSON-fallback path and the dmat path apply the SAME read-time wrapper, so for any
# input the two paths must return the same value.
TEST_CASES = [
    PropertyTestCase(name="str_normal", type=PropertyType.String, input_value="hello world"),
    PropertyTestCase(name="str_empty", type=PropertyType.String, input_value=""),
    PropertyTestCase(name="str_whitespace", type=PropertyType.String, input_value="   "),
    PropertyTestCase(name="num_int", type=PropertyType.Numeric, input_value=42),
    PropertyTestCase(name="num_zero", type=PropertyType.Numeric, input_value=0),
    PropertyTestCase(name="num_negative", type=PropertyType.Numeric, input_value=-100),
    PropertyTestCase(name="num_float", type=PropertyType.Numeric, input_value=3.14159),
    PropertyTestCase(name="num_invalid", type=PropertyType.Numeric, input_value="not a number"),
    PropertyTestCase(name="num_whitespace", type=PropertyType.Numeric, input_value="  123  "),
    PropertyTestCase(name="bool_true_str", type=PropertyType.Boolean, input_value="true"),
    PropertyTestCase(name="bool_false_str", type=PropertyType.Boolean, input_value="false"),
    PropertyTestCase(name="bool_true_int", type=PropertyType.Boolean, input_value="1"),
    PropertyTestCase(name="bool_false_int", type=PropertyType.Boolean, input_value="0"),
    PropertyTestCase(name="bool_invalid", type=PropertyType.Boolean, input_value="maybe"),
    PropertyTestCase(name="dt_iso_full", type=PropertyType.Datetime, input_value="2024-01-15T10:30:00Z"),
    PropertyTestCase(name="dt_date_only", type=PropertyType.Datetime, input_value="2024-01-15"),
    PropertyTestCase(name="dt_invalid", type=PropertyType.Datetime, input_value="not a date"),
]


class TestDmatExtractionConsistency(ClickhouseTestMixin, APIBaseTest):
    @pytest.mark.django_db(transaction=True)
    def test_dmat_string_extraction_matches_json_for_all_property_types(self):
        """Reading via dmat must equal reading via JSON for every property type.

        Insert one row that goes through JSON and one row with `dmat_string_<idx>`
        pre-filled (using the same extraction SQL the backfill mutation uses), then
        SELECT the same column off both. Because dmat columns are now uniformly String
        and HogQL applies the same `_field_type_to_property_call` wrapper to both
        paths, the two SELECTs must return identical Python values.
        """
        from posthog.hogql.query import execute_hogql_query

        event_properties = {tc.name: tc.input_value for tc in TEST_CASES}
        # Each test case gets its own dmat_string_<idx> column. There's no per-type
        # column pool any more — slot indexes are allocated globally.
        slot_indexes = {tc.name: i for i, tc in enumerate(TEST_CASES)}

        prop_defs = {}
        for tc in TEST_CASES:
            prop_defs[tc.name] = PropertyDefinition.objects.create(
                team=self.team,
                name=tc.name,
                property_type=tc.type,
                type=PropertyDefinition.Type.EVENT,
            )

        # ---- Phase 1: JSON-fallback baseline ----
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
        assert result_json.clickhouse is not None and "dmat_" not in result_json.clickhouse, (
            "Phase 1 should use JSON extraction (no slots created yet)"
        )
        json_results = result_json.results[0]

        # ---- Phase 2: row with `dmat_string_<idx>` pre-filled by the extraction SQL ----
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

        # ---- Phase 3: same SELECT, but slots are READY so HogQL routes through dmat ----
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
        assert result_dmat.clickhouse is not None and "dmat_string_" in result_dmat.clickhouse, (
            f"Phase 3 should route through dmat columns. SQL: {result_dmat.clickhouse}"
        )
        dmat_results = result_dmat.results[0]

        if json_results != dmat_results:
            failures = []
            for i, tc in enumerate(TEST_CASES):
                if json_results[i] != dmat_results[i]:
                    failures.append(
                        f"  {tc.name} ({tc.type}):\n"
                        f"    Input:       {tc.input_value!r}\n"
                        f"    JSON result: {json_results[i]!r}\n"
                        f"    dmat result: {dmat_results[i]!r}\n"
                        f"    dmat column: dmat_string_{slot_indexes[tc.name]}"
                    )
            raise AssertionError("dmat extraction differs from JSON extraction!\n\nMismatches:\n" + "\n".join(failures))
