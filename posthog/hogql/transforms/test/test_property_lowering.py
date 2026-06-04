from posthog.test.base import BaseTest, ClickhouseTestMixin, materialized

from posthog.schema import PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.property_lowering import resolve_materialized_property_source


class TestResolveMaterializedPropertySource(ClickhouseTestMixin, BaseTest):
    def _property_type(
        self, query: str, modifiers: HogQLQueryModifiers | None = None
    ) -> tuple[ast.PropertyType, HogQLContext]:
        context = HogQLContext(
            team_id=self.team.pk,
            database=Database.create_for(team=self.team),
            enable_select_queries=True,
            modifiers=modifiers or HogQLQueryModifiers(),
        )
        resolved = resolve_types(parse_select(query), context, dialect="clickhouse")
        assert isinstance(resolved, ast.SelectQuery)
        select_item = resolved.select[0]
        if isinstance(select_item, ast.Alias):
            select_item = select_item.expr
        assert isinstance(select_item, ast.Field)
        assert isinstance(select_item.type, ast.PropertyType)
        return select_item.type, context

    def test_no_materialization_returns_none(self):
        # No physical backing -> None, so the printer falls back to JSONExtract over the blob.
        property_type, context = self._property_type("SELECT properties.tier FROM events")
        assert resolve_materialized_property_source(property_type.field_type, "tier", context) is None

    def test_property_group_source_under_optimized(self):
        property_type, context = self._property_type(
            "SELECT properties.tier FROM events",
            HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED),
        )
        source = resolve_materialized_property_source(property_type.field_type, "tier", context)
        assert source is not None
        assert source.kind == "property_group"
        assert "properties_group" in source.column
        assert source.is_nullable is True

    def test_materialized_column_takes_priority(self):
        with materialized("events", "tier") as mat_col:
            property_type, context = self._property_type(
                "SELECT properties.tier FROM events",
                HogQLQueryModifiers(propertyGroupsMode=PropertyGroupsMode.OPTIMIZED),
            )
            source = resolve_materialized_property_source(property_type.field_type, "tier", context)
            assert source is not None
            assert source.kind == "materialized_column"
            assert source.column == mat_col.name

    def test_disabled_materialization_returns_none(self):
        with materialized("events", "tier"):
            property_type, context = self._property_type(
                "SELECT properties.tier FROM events",
                HogQLQueryModifiers(materializationMode="disabled"),
            )
            assert resolve_materialized_property_source(property_type.field_type, "tier", context) is None
