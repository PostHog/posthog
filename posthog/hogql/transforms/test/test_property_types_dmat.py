"""Tests for dmat (dynamic materialized columns) integration in property type resolution."""

from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.property_definition import PropertyType


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
            property_definition=prop_def,
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
        assert "dmat_float_3" in query, f"Expected dmat_float_3 in query but got: {query}"
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
            property_definition=prop_def,
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
        assert "dmat_float_0" not in query
        # Should use JSON extraction or properties access
        assert "properties" in query or "JSONExtractRaw" in query
