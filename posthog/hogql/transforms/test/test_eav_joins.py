from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import PropertyDefinition
from posthog.models.materialized_column_slots import (
    MaterializationType,
    MaterializedColumnSlot,
    MaterializedColumnSlotState,
)
from posthog.models.property_definition import PropertyType


class TestEAVJoins(BaseTest):
    def test_eav_property_generates_join(self):
        # Create a property definition with EAV materialization
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="plan",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_name=prop_def.name,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
            materialization_type=MaterializationType.EAV,
        )

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
        )

        query = parse_select("SELECT properties.plan FROM events WHERE event = '$pageview'")
        result, _ = prepare_and_print_ast(query, context, dialect="clickhouse")

        # Should contain a JOIN to event_properties
        assert "ANY LEFT JOIN" in result
        assert "event_properties" in result
        assert "eav_plan" in result
        # Should reference the EAV value column instead of JSON extraction
        assert "eav_plan.value_string" in result

    def test_eav_multiple_properties_generate_multiple_joins(self):
        # Create two property definitions with EAV materialization
        prop_def1 = PropertyDefinition.objects.create(
            team=self.team,
            name="plan",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_name=prop_def1.name,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
            materialization_type=MaterializationType.EAV,
        )

        prop_def2 = PropertyDefinition.objects.create(
            team=self.team,
            name="previous_plan",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_name=prop_def2.name,
            property_type=PropertyType.String,
            slot_index=1,
            state=MaterializedColumnSlotState.READY,
            materialization_type=MaterializationType.EAV,
        )

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
        )

        query = parse_select(
            "SELECT properties.plan, properties.previous_plan FROM events WHERE properties.plan > properties.previous_plan"
        )
        result, _ = prepare_and_print_ast(query, context, dialect="clickhouse")

        # Should contain two JOINs
        assert result.count("ANY LEFT JOIN") == 2
        assert "eav_plan" in result
        assert "eav_previous_plan" in result

    def test_eav_numeric_property_uses_value_numeric(self):
        # Create a numeric property with EAV materialization
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="revenue",
            property_type=PropertyType.Numeric,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_name=prop_def.name,
            property_type=PropertyType.Numeric,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
            materialization_type=MaterializationType.EAV,
        )

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
        )

        query = parse_select("SELECT properties.revenue FROM events")
        result, _ = prepare_and_print_ast(query, context, dialect="clickhouse")

        # Should use value_numeric column
        assert "eav_revenue.value_numeric" in result

    def test_dmat_property_still_works(self):
        # Create a property with DMAT materialization (should still work)
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="browser",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_name=prop_def.name,
            property_type=PropertyType.String,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
            materialization_type=MaterializationType.DMAT,
        )

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
        )

        query = parse_select("SELECT properties.browser FROM events")
        result, _ = prepare_and_print_ast(query, context, dialect="clickhouse")

        # Should use dmat column, not EAV join
        assert "dmat_string_0" in result
        assert "event_properties" not in result

    def test_non_materialized_property_uses_json(self):
        # Create a property without any materialization
        PropertyDefinition.objects.create(
            team=self.team,
            name="custom_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
        )

        query = parse_select("SELECT properties.custom_prop FROM events")
        result, _ = prepare_and_print_ast(query, context, dialect="clickhouse")

        # Should use JSON extraction, not EAV or DMAT
        assert "event_properties" not in result
        assert "dmat_" not in result
        # Should have some form of JSON extraction
        assert "JSONExtract" in result or "replaceRegexpAll" in result
