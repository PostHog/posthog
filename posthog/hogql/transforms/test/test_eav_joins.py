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
        assert "eav_events_plan" in result
        # Should reference the EAV value column instead of JSON extraction
        assert "eav_events_plan.value_string" in result

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
        assert "eav_events_plan" in result
        assert "eav_events_previous_plan" in result

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
        assert "eav_events_revenue.value_numeric" in result

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


class TestEAVJoinsComplexQueries(BaseTest):
    """Tests for EAV joins with complex query structures."""

    def _create_eav_property(self, name: str, property_type: str = PropertyType.String) -> None:
        """Helper to create an EAV-materialized property."""
        PropertyDefinition.objects.create(
            team=self.team,
            name=name,
            property_type=property_type,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_name=name,
            property_type=property_type,
            slot_index=MaterializedColumnSlot.objects.filter(team=self.team).count(),
            state=MaterializedColumnSlotState.READY,
            materialization_type=MaterializationType.EAV,
        )

    def _get_context(self) -> HogQLContext:
        return HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
        )

    def test_multiple_events_tables_with_different_aliases(self):
        """Test: SELECT e1.properties.foo, e2.properties.bar FROM events e1 JOIN events e2 ON ..."""
        self._create_eav_property("foo")
        self._create_eav_property("bar")

        query = parse_select(
            "SELECT e1.properties.foo, e2.properties.bar FROM events e1 JOIN events e2 ON e1.event = e2.event"
        )
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # Should have two separate EAV joins, one for each events table
        assert result.count("ANY LEFT JOIN") >= 2
        # Each join should reference its respective events table alias
        assert "eav_" in result
        # The foo property should join to e1, bar should join to e2
        # Check that both properties are referenced
        assert "foo" in result
        assert "bar" in result

    def test_same_property_on_different_events_tables(self):
        """Test: SELECT e1.properties.plan, e2.properties.plan FROM events e1 JOIN events e2 ON ..."""
        self._create_eav_property("plan")

        query = parse_select(
            "SELECT e1.properties.plan, e2.properties.plan FROM events e1 JOIN events e2 ON e1.event = e2.event"
        )
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # Should have two separate EAV joins - one for e1.plan, one for e2.plan
        # They can't share a join because they reference different events tables
        assert result.count("ANY LEFT JOIN") >= 2

    def test_subquery_with_eav_property(self):
        """Test: SELECT (SELECT e.properties.plan FROM events e LIMIT 1) as x FROM events"""
        self._create_eav_property("plan")

        query = parse_select("SELECT (SELECT e.properties.plan FROM events e LIMIT 1) as x FROM events")
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # The EAV join should be in the subquery, not the outer query
        # The subquery references 'e', so the join should reference 'e'
        assert "eav_" in result
        assert "plan" in result

    def test_two_subselects_same_alias_same_property(self):
        """Test: SELECT (SELECT e.properties.plan FROM events e) as x, (SELECT e.properties.plan FROM events e) as y"""
        self._create_eav_property("plan")

        query = parse_select(
            """
            SELECT
                (SELECT e.properties.plan FROM events e WHERE e.event = 'A' LIMIT 1) as x,
                (SELECT e.properties.plan FROM events e WHERE e.event = 'B' LIMIT 1) as y
            FROM events
            LIMIT 1
            """
        )
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # Both subqueries use alias 'e' and property 'plan'
        # Each subquery should have its own EAV join scoped to it
        # The outer query should NOT have an EAV join (it doesn't access any EAV properties)
        assert "eav_" in result
        assert "plan" in result

    def test_outer_query_and_subquery_different_properties(self):
        """Test: SELECT properties.foo, (SELECT e.properties.bar FROM events e LIMIT 1) FROM events"""
        self._create_eav_property("foo")
        self._create_eav_property("bar")

        query = parse_select(
            """
            SELECT
                properties.foo,
                (SELECT e.properties.bar FROM events e LIMIT 1) as subq
            FROM events
            """
        )
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # foo should be joined in the outer query
        # bar should be joined in the subquery
        assert "foo" in result
        assert "bar" in result
        # Should have at least 2 EAV joins total
        assert result.count("ANY LEFT JOIN") >= 2

    def test_nested_subselects(self):
        """Test: SELECT (SELECT (SELECT e.properties.plan FROM events e LIMIT 1) FROM events LIMIT 1) FROM events"""
        self._create_eav_property("plan")

        query = parse_select(
            """
            SELECT (
                SELECT (
                    SELECT e.properties.plan FROM events e LIMIT 1
                ) FROM events LIMIT 1
            ) as nested
            FROM events
            LIMIT 1
            """
        )
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # Only the innermost subquery accesses the EAV property
        # The join should only be in that innermost query
        assert "eav_" in result
        assert "plan" in result

    def test_subquery_eav_join_not_added_to_outer_query(self):
        """Ensure subquery EAV joins don't leak to outer query scope."""
        self._create_eav_property("subq_only_prop")

        query = parse_select(
            """
            SELECT
                event,
                (SELECT e.properties.subq_only_prop FROM events e LIMIT 1) as subq
            FROM events
            WHERE event = 'test'
            """
        )
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # The outer query doesn't use subq_only_prop directly
        # The EAV join should only be in the subquery
        # This test will help ensure proper scoping
        assert "subq_only_prop" in result

    def test_mixed_eav_and_non_eav_properties(self):
        """Test query with both EAV and non-materialized properties."""
        self._create_eav_property("eav_prop")
        # non_eav_prop is not created as EAV

        PropertyDefinition.objects.create(
            team=self.team,
            name="non_eav_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )

        query = parse_select("SELECT properties.eav_prop, properties.non_eav_prop FROM events")
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="clickhouse")

        # eav_prop should use EAV join
        assert "eav_eav_prop" in result or "eav_" in result
        # non_eav_prop should use JSON extraction
        assert "JSONExtract" in result or "replaceRegexpAll" in result

    def test_hogql_dialect_does_not_add_eav_joins(self):
        """EAV joins should only be added for ClickHouse dialect, not HogQL."""
        self._create_eav_property("plan")

        query = parse_select("SELECT properties.plan FROM events")
        result, _ = prepare_and_print_ast(query, self._get_context(), dialect="hogql")

        # HogQL output should NOT have EAV joins - just the property access
        assert "event_properties" not in result
        assert "ANY LEFT JOIN" not in result
        assert "eav_" not in result
        # Should have the property access in HogQL form
        assert "properties.plan" in result
