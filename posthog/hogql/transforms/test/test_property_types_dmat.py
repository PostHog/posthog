"""Tests for dmat (dynamic materialized columns) integration in property type resolution."""

import pytest
from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.property_types import build_property_swapper

from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.property_definition import PropertyType


class TestDmatIntegration(BaseTest):
    """Test that HogQL queries use dmat columns when available."""

    def test_uses_dmat_column_when_slot_ready(self):
        """Test that property access uses dmat column when slot is READY."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
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

        query = parse_select("SELECT properties.revenue FROM events")
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        build_property_swapper(query, context)

        # Apply the property swapper
        swapped_query = context.property_swapper.visit(query)

        # Find the Field node for properties.revenue
        select_field = swapped_query.select[0]
        assert isinstance(select_field, ast.Field)
        assert select_field.chain == ["dmat_float_3"]

    def test_falls_back_to_json_when_no_slot(self):
        """Test that property access falls back to JSON extraction when no slot exists."""
        PropertyDefinition.objects.create(
            team=self.team,
            name="custom_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        query = parse_select("SELECT properties.custom_prop FROM events")
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        build_property_swapper(query, context)

        swapped_query = context.property_swapper.visit(query)

        # Should still access properties.custom_prop (no transformation)
        select_field = swapped_query.select[0]
        assert isinstance(select_field, ast.Field)
        assert select_field.chain == ["properties", "custom_prop"]

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

        query = parse_select("SELECT properties.user_score FROM events")
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        build_property_swapper(query, context)

        swapped_query = context.property_swapper.visit(query)

        # Should fall back to JSON extraction (not use dmat)
        select_field = swapped_query.select[0]
        assert isinstance(select_field, ast.Field)
        # Should be wrapped in toFloat call
        assert isinstance(select_field, ast.Call)
        assert select_field.name == "toFloat"

    @pytest.mark.parametrize(
        "property_type,slot_index,expected_column",
        [
            (PropertyType.String, 0, "dmat_string_0"),
            (PropertyType.String, 7, "dmat_string_7"),
            (PropertyType.Numeric, 2, "dmat_float_2"),
            (PropertyType.Numeric, 9, "dmat_float_9"),
            (PropertyType.Boolean, 1, "dmat_bool_1"),
            (PropertyType.Boolean, 4, "dmat_bool_4"),
            (PropertyType.Datetime, 0, "dmat_datetime_0"),
            (PropertyType.Datetime, 8, "dmat_datetime_8"),
        ],
    )
    def test_all_property_types_use_correct_column_name(self, property_type, slot_index, expected_column):
        """Test that all property types generate correct dmat column names."""
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name=f"test_prop_{property_type}_{slot_index}",
            property_type=property_type,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            property_type=property_type,
            slot_index=slot_index,
            state=MaterializedColumnSlotState.READY,
        )

        query = parse_select(f"SELECT properties.{prop_def.name} FROM events")
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        build_property_swapper(query, context)

        swapped_query = context.property_swapper.visit(query)

        select_field = swapped_query.select[0]
        assert isinstance(select_field, ast.Field)
        assert select_field.chain == [expected_column]
