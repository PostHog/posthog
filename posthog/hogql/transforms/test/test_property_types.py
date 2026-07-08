import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import pytest
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    get_indexes_from_explain,
    materialized,
)
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property_planner import (
    PropertyComparisonPlan,
    PropertyLiteralConversion,
    PropertyMinmaxBlocker,
    PropertySourceKind,
    plan_property_comparison,
)
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.resolver import resolve_types
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.transforms.property_types import PropertySwapper, build_property_swapper
from posthog.hogql.type_system import ComparisonCompatibility

from posthog.models import PropertyDefinition, Team
from posthog.models.group.util import create_group
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable


@dataclass
class FakeMaterializedColumn:
    name: str
    is_nullable: bool
    type: str
    has_minmax_index: bool = False
    has_bloom_filter_index: bool = False
    has_ngram_lower_index: bool = False
    has_bloom_filter_lower_index: bool = False


def _normalize_snapshot_sql(sql: str) -> str:
    return "\n".join(line.rstrip() for line in sql.splitlines())


class TestNewEventsSchemaArraySubcolumns(SimpleTestCase):
    def _context(self) -> HogQLContext:
        team = Team(id=1, project_id=1)
        context = HogQLContext(team_id=team.id, team=team, enable_select_queries=True)
        context.database = Database()
        context.restricted_properties = set()
        context.property_swapper = PropertySwapper("UTC", {}, {}, {}, context, True)
        return context

    def _print_select(self, select: str) -> str:
        expr = parse_select(select)
        context = self._context()
        with patch("posthog.hogql.printer.utils.build_property_swapper"):
            query, _ = prepare_and_print_ast(
                expr,
                context,
                "clickhouse",
            )
        return pretty_print_in_tests(query, 1)

    def _plan_where_comparison(self, select: str) -> PropertyComparisonPlan:
        expr = parse_select(select)
        context = self._context()
        resolved = cast(ast.SelectQuery, resolve_types(expr, context, dialect="clickhouse"))
        comparison = cast(ast.CompareOperation, resolved.where)
        plan = plan_property_comparison(comparison, context)
        assert plan is not None
        return plan

    @parameterized.expand(
        [
            ("$active_feature_flags", "beta-feature", True),
            ("$exception_types", "TypeError", False),
        ]
    )
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_property_comparison_planner_uses_json_array_subcolumn_type(
        self, property_name: str, value: str, has_bloom_filter_index: bool
    ) -> None:
        plan = self._plan_where_comparison(f"select count() from events where properties.{property_name} = '{value}'")

        assert plan.access.source.kind == PropertySourceKind.JSON
        assert plan.access.source.is_nullable is False
        assert isinstance(plan.access.source.physical_type, ast.ArrayType)
        assert isinstance(plan.access.source.physical_type.item_type, ast.StringType)
        assert plan.access.source.has_bloom_filter_index is has_bloom_filter_index

    @parameterized.expand(
        [
            ("json_has", "select count() from events where JSONHas(properties, '$active_feature_flags')", "notEmpty"),
            (
                "is_set",
                "select count() from events where properties.$active_feature_flags != null",
                "notEmpty",
            ),
            (
                "is_not_set",
                "select count() from events where properties.$active_feature_flags = null",
                "empty",
            ),
            (
                "exact",
                "select count() from events where properties.$active_feature_flags = 'beta-feature'",
                "has",
            ),
            (
                "in",
                "select count() from events where properties.$active_feature_flags in ('alpha', 'beta')",
                "hasAny",
            ),
            (
                "icontains",
                "select count() from events where toString(properties.$active_feature_flags) ILIKE '%beta%'",
                "arrayExists",
            ),
            (
                "icontains_multi",
                "select count() from events where multiSearchAnyCaseInsensitive(toString(properties.$active_feature_flags), ['alpha', 'beta']) > 0",
                "arrayExists",
            ),
        ]
    )
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_active_feature_flags_use_array_subcolumn(self, _name: str, query: str, expected_function: str) -> None:
        printed = self._print_select(query)

        assert expected_function in printed, printed
        assert "events.properties.`$active_feature_flags`" in printed, printed
        assert "toString(events.properties.`$active_feature_flags`)" not in printed, printed
        assert "JSONHas(events.properties" not in printed, printed

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_exception_types_use_array_subcolumn(self) -> None:
        printed = self._print_select("select count() from events where properties.$exception_types = 'TypeError'")

        assert "has(" in printed, printed
        assert "events.properties.`$exception_types`" in printed, printed
        assert "toString(events.properties.`$exception_types`)" not in printed, printed
        assert "JSONExtract" not in printed, printed

    @parameterized.expand(
        [
            ("$active_feature_flags", "[]"),
            ("$exception_types", ""),
        ]
    )
    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_jsonextract_string_arrays_read_array_subcolumn(self, property_name: str, default_value: str) -> None:
        printed = self._print_select(
            f"select JSONExtract(ifNull(properties.{property_name}, '{default_value}'), 'Array(String)') from events"
        )

        assert f"events.properties.`{property_name}`" in printed, printed
        assert "JSONExtract" not in printed, printed
        assert f"toJSONString(events.properties.`{property_name}`)" not in printed, printed


class TestPropertyTypes(BaseTest):
    snapshot: Any
    maxDiff = None

    def setUp(self):
        super().setUp()
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:1",
            properties={"name": "org1", "inty": 1},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_height",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_width",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="bool",
            defaults={"property_type": "Boolean"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="tickets",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="provided_timestamp",
            defaults={"property_type": "DateTime"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="$initial_browser",
            defaults={"property_type": "String"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.GROUP,
            name="inty",
            defaults={"property_type": "Numeric", "group_type_index": 0},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.GROUP,
            name="group_boolean",
            defaults={"property_type": "Boolean", "group_type_index": 0},
        )

    def _events_schema_snapshot(self):
        self.snapshot.session.pytest_session.config.option.warn_unused_snapshots = True
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            return self.snapshot(name="new_events_schema")
        return self.snapshot

    def _plan_where_comparison(
        self,
        select: str,
        restricted_properties: set[tuple[str, int]] | None = None,
    ) -> PropertyComparisonPlan:
        context, resolved = self._resolve_select(select, restricted_properties=restricted_properties)
        comparison = cast(ast.CompareOperation, resolved.where)
        plan = plan_property_comparison(comparison, context)
        assert plan is not None
        return plan

    def _resolve_select(
        self,
        select: str,
        restricted_properties: set[tuple[str, int]] | None = None,
    ) -> tuple[HogQLContext, ast.SelectQuery]:
        """Resolve types and build the property-swapper registry without preparing further.

        The planner is an analysis over the resolved AST; the prepared AST has already been lowered past the point
        where property reads are recognizable (they become bare physical-column expressions), so the planner must be
        fed its actual pipeline-position input.
        """
        expr = parse_select(select)
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        if restricted_properties is not None:
            context.restricted_properties = restricted_properties
        context.database = Database.create_for(context.team_id, modifiers=context.modifiers, team=context.team)
        node = cast(ast.SelectQuery, resolve_types(expr, context, dialect="clickhouse"))
        build_property_swapper(node, context)
        return context, node

    def _prepare_select(
        self,
        select: str,
        restricted_properties: set[tuple[str, int]] | None = None,
    ) -> tuple[HogQLContext, ast.SelectQuery]:
        expr = parse_select(select)
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        if restricted_properties is not None:
            context.restricted_properties = restricted_properties

        _, prepared = prepare_and_print_ast(expr, context, "clickhouse")
        assert isinstance(prepared, ast.SelectQuery)
        return context, prepared

    def test_property_comparison_planner_marks_string_minmax_ready(self) -> None:
        property_name = "$session_id" if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else "$browser"
        with materialized("events", property_name, is_nullable=True, create_minmax_index=True):
            plan = self._plan_where_comparison(f"select count() from events where properties.{property_name} < 'm'")

        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert plan.access.source.kind == PropertySourceKind.JSON
            assert plan.access.semantic_type == ast.StringType(nullable=True)
            assert plan.access.source.physical_type == ast.StringType(nullable=True)
            assert plan.physical_compatibility == ComparisonCompatibility.DEFINITELY_COMPATIBLE
            assert plan.can_compare_physical_source_directly is True
            assert plan.can_use_minmax_index is True
            assert plan.minmax_blocker is None
            return

        assert plan.access.source.kind == PropertySourceKind.MATERIALIZED_COLUMN
        assert plan.access.semantic_type == ast.StringType(nullable=True)
        assert plan.access.source.physical_type == ast.StringType(nullable=True)
        assert plan.physical_compatibility == ComparisonCompatibility.DEFINITELY_COMPATIBLE
        assert plan.can_compare_physical_source_directly is True
        assert plan.can_use_minmax_index is True
        assert plan.minmax_blocker is None

    def test_property_comparison_planner_blocks_numeric_minmax_until_source_type_matches(self) -> None:
        with materialized("events", "$screen_width", is_nullable=True, create_minmax_index=True):
            plan = self._plan_where_comparison("select count() from events where properties.$screen_width < 5")

        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert plan.access.source.kind == PropertySourceKind.JSON
            assert plan.access.semantic_type == ast.FloatType(nullable=True)
            assert plan.access.source.physical_type == ast.StringType(nullable=True)
            assert plan.semantic_compatibility == ComparisonCompatibility.CHEAP_CAST
            assert plan.physical_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
            assert plan.can_compare_physical_source_directly is False
            assert plan.can_use_minmax_index is False
            assert plan.minmax_blocker == PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE
            return

        assert plan.access.source.kind == PropertySourceKind.MATERIALIZED_COLUMN
        assert plan.access.semantic_type == ast.FloatType(nullable=True)
        assert plan.access.source.physical_type == ast.StringType(nullable=True)
        assert plan.semantic_compatibility == ComparisonCompatibility.CHEAP_CAST
        assert plan.physical_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
        assert plan.can_compare_physical_source_directly is False
        assert plan.can_use_minmax_index is False
        assert plan.minmax_blocker == PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE

    def test_property_comparison_planner_allows_numeric_minmax_when_source_type_matches(self) -> None:
        fake_column = FakeMaterializedColumn(
            name="mat_$screen_width",
            is_nullable=True,
            type="Nullable(Float64)",
            has_minmax_index=True,
        )

        with patch("posthog.hogql.property_planner.get_materialized_column_for_property", return_value=fake_column):
            plan = self._plan_where_comparison("select count() from events where properties.$screen_width < 5")

        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert plan.access.source.kind == PropertySourceKind.JSON
            assert plan.access.semantic_type == ast.FloatType(nullable=True)
            assert plan.access.source.physical_type == ast.StringType(nullable=True)
            assert plan.semantic_compatibility == ComparisonCompatibility.CHEAP_CAST
            assert plan.physical_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
            assert plan.literal_conversion == PropertyLiteralConversion.NONE
            assert plan.can_compare_physical_source_directly is False
            assert plan.can_use_minmax_index is False
            assert plan.minmax_blocker == PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE
            return

        assert plan.access.source.kind == PropertySourceKind.MATERIALIZED_COLUMN
        assert plan.access.semantic_type == ast.FloatType(nullable=True)
        assert plan.access.source.physical_type == ast.FloatType(nullable=True)
        assert plan.semantic_compatibility == ComparisonCompatibility.CHEAP_CAST
        assert plan.physical_compatibility == ComparisonCompatibility.CHEAP_CAST
        assert plan.literal_conversion == PropertyLiteralConversion.NONE
        assert plan.can_compare_physical_source_directly is True
        assert plan.can_use_minmax_index is True
        assert plan.minmax_blocker is None

    def test_property_comparison_planner_blocks_datetime_minmax_until_source_type_matches(self) -> None:
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="event_time_prop",
            defaults={"property_type": "DateTime"},
        )
        with materialized("events", "event_time_prop", is_nullable=True, create_minmax_index=True):
            plan = self._plan_where_comparison(
                "select count() from events where properties.event_time_prop < toDateTime('2024-01-01')"
            )

        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert plan.access.source.kind == PropertySourceKind.JSON
            assert plan.access.semantic_type == ast.DateTimeType(nullable=True)
            assert plan.access.source.physical_type == ast.StringType(nullable=True)
            assert plan.semantic_compatibility == ComparisonCompatibility.DEFINITELY_COMPATIBLE
            assert plan.physical_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
            assert plan.can_compare_physical_source_directly is False
            assert plan.can_use_minmax_index is False
            assert plan.minmax_blocker == PropertyMinmaxBlocker.NO_MINMAX_INDEX
            return

        assert plan.access.source.kind == PropertySourceKind.MATERIALIZED_COLUMN
        assert plan.access.semantic_type == ast.DateTimeType(nullable=True)
        assert plan.access.source.physical_type == ast.StringType(nullable=True)
        assert plan.semantic_compatibility == ComparisonCompatibility.DEFINITELY_COMPATIBLE
        assert plan.physical_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
        assert plan.can_compare_physical_source_directly is False
        assert plan.can_use_minmax_index is False
        assert plan.minmax_blocker == PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE

    def test_property_comparison_planner_allows_datetime_minmax_when_literal_can_move_to_value_side(self) -> None:
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="event_time_prop",
            defaults={"property_type": "DateTime"},
        )
        fake_column = FakeMaterializedColumn(
            name="mat_event_time_prop",
            is_nullable=True,
            type="Nullable(DateTime64(6, 'UTC'))",
            has_minmax_index=True,
        )

        with patch("posthog.hogql.property_planner.get_materialized_column_for_property", return_value=fake_column):
            plan = self._plan_where_comparison(
                "select count() from events where properties.event_time_prop < '2024-01-01'"
            )

        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert plan.access.source.kind == PropertySourceKind.JSON
            assert plan.access.semantic_type == ast.DateTimeType(nullable=True)
            assert plan.access.source.physical_type == ast.StringType(nullable=True)
            assert plan.semantic_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
            assert plan.physical_compatibility == ComparisonCompatibility.DEFINITELY_COMPATIBLE
            assert plan.literal_conversion == PropertyLiteralConversion.NONE
            assert plan.can_compare_physical_source_directly is False
            assert plan.can_use_minmax_index is False
            assert plan.minmax_blocker == PropertyMinmaxBlocker.NO_MINMAX_INDEX
            return

        assert plan.access.source.kind == PropertySourceKind.MATERIALIZED_COLUMN
        assert plan.access.semantic_type == ast.DateTimeType(nullable=True)
        assert plan.access.source.physical_type == ast.DateTimeType(nullable=True)
        assert plan.semantic_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
        assert plan.physical_compatibility == ComparisonCompatibility.EXPENSIVE_CAST
        assert plan.literal_conversion == PropertyLiteralConversion.DATETIME
        assert plan.can_compare_physical_source_directly is True
        assert plan.can_use_minmax_index is True
        assert plan.minmax_blocker is None

    def test_property_comparison_planner_respects_restricted_property_materialization(self) -> None:
        with materialized("events", "$browser", is_nullable=True, create_minmax_index=True):
            plan = self._plan_where_comparison(
                "select count() from events where properties.$browser < 'm'",
                restricted_properties={("$browser", PropertyDefinition.Type.EVENT)},
            )

        assert plan.access.source.kind == PropertySourceKind.JSON
        assert plan.access.source.restricted is True
        assert plan.access.source.has_minmax_index is False
        assert plan.can_use_minmax_index is False
        assert plan.minmax_blocker == PropertyMinmaxBlocker.NO_MINMAX_INDEX

    def test_property_type_resolve_constant_type_uses_property_metadata(self) -> None:
        context, resolved = self._resolve_select("select count() from events where properties.$screen_width < 5")
        comparison = cast(ast.CompareOperation, resolved.where)
        plan = plan_property_comparison(comparison, context)
        assert plan is not None

        assert plan.access.property_type.resolve_constant_type(context) == ast.FloatType(nullable=True)

    def test_property_swapper_assigns_call_types_for_float_and_boolean(self) -> None:
        _, prepared = self._prepare_select("select properties.$screen_width, properties.bool from events")

        float_expr = prepared.select[0]
        bool_expr = prepared.select[1]
        if isinstance(float_expr, ast.Alias):
            float_expr = float_expr.expr
        if isinstance(bool_expr, ast.Alias):
            bool_expr = bool_expr.expr

        assert isinstance(float_expr, ast.Call)
        assert isinstance(float_expr.type, ast.CallType)
        assert float_expr.type.return_type == ast.FloatType(nullable=True)

        assert isinstance(bool_expr, ast.Call)
        assert isinstance(bool_expr.type, ast.CallType)
        assert bool_expr.type.return_type == ast.BooleanType(nullable=True)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_event(self):
        printed = self._print_select(
            "select properties.$screen_width * properties.$screen_height, properties.bool from events"
        )
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_person_raw(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_resolve_property_types_person(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_combined(self):
        printed = self._print_select("select properties.$screen_width * person.properties.tickets from events")
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_event_person_poe_off(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_resolve_property_types_event_person_poe_on(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        assert printed == self._events_schema_snapshot()

    def test_resolve_property_types_from_qualified_posthog_events(self):
        # Selecting from the qualified `posthog.events` form must produce the same property-type
        # rewriting as the unqualified `events` form — otherwise queries using the qualified form
        # silently miss numeric/boolean casts and DateTime timezone wrapping.
        unqualified = self._print_select("select properties.$screen_width, properties.bool from events")
        qualified = self._print_select("select properties.$screen_width, properties.bool from posthog.events")
        # Both root-level `events` and `posthog.events` resolve to the same EventsTable and print
        # identically, so property-type resolution output should match exactly.
        assert unqualified == qualified

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_property_types(self):
        printed = self._print_select("select organization.properties.inty from events")
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_boolean_property_types(self):
        printed = self._print_select(
            """select
            organization.properties.group_boolean = true,
            organization.properties.group_boolean = false,
            organization.properties.group_boolean is null
            from events"""
        )
        assert printed == self._events_schema_snapshot()
        assert (
            "SELECT ifNull(equals(accurateCastOrNull(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL), hogvar), 1), 0), ifNull(equals(accurateCastOrNull(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL), hogvar), 0), 0), isNull(accurateCastOrNull(transform(toString(events__group_0.properties___group_boolean), hogvar, hogvar, NULL), hogvar))"
            in re.sub(r"%\(hogql_val_\d+\)s", "hogvar", printed)
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_group_types_are_the_same_in_persons_inlined_subselect(self):
        expr = parse_select(
            """select table_a.id from
                    (select
                        events.timestamp as id,
                        organization.properties.group_boolean = true,
                        organization.properties.group_boolean = false,
                        organization.properties.group_boolean is null
                    from events) as table_a
            join persons on table_a.id = persons.id and persons.id in (select
                        events.timestamp as id,
                        organization.properties.group_boolean = true,
                        organization.properties.group_boolean = false,
                        organization.properties.group_boolean is null
                    from events)"""
        )
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        query = re.sub(r"hogql_val_\d+", "hogql_val", query)
        # We're searching for the two subselects and making sure they are exactly the same
        results = re.findall(
            rf"SELECT toTimeZone\(events\.timestamp.*?WHERE equals\(events\.team_id, {self.team.id}\)\)", query
        )
        assert results[0] == results[1]

    @pytest.mark.usefixtures("unittest_snapshot")
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_data_warehouse_person_property_types(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="extended_properties",
            columns={
                "string_prop": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"},
                "int_prop": {"hogql": "IntegerDatabaseField", "clickhouse": "Nullable(Int64)"},
                "bool_prop": {"hogql": "BooleanDatabaseField", "clickhouse": "Nullable(Bool)"},
            },
            credential=credential,
            url_pattern="",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="extended_properties",
            joining_table_key="string_prop",
            field_name="extended_properties",
        )

        printed = self._print_select(
            "select persons.extended_properties.string_prop, persons.extended_properties.int_prop, persons.extended_properties.bool_prop AS bool_prop from persons WHERE bool_prop = true"
        )

        assert printed == self.snapshot

    @parameterized.expand(
        [
            ("to_float_or_zero", "toFloatOrZero(properties.$screen_width)", "toFloat64OrZero"),
            ("to_int_or_zero", "toIntOrZero(properties.$screen_width)", "toInt64OrZero"),
            ("to_float_or_default", "toFloatOrDefault(properties.$screen_width, 0)", "toFloat64OrDefault"),
        ]
    )
    def test_numeric_property_not_double_cast_inside_string_parser(self, _name: str, expr: str, ch_fn: str):
        # toFloat64OrZero/toInt64OrZero/toFloat64OrDefault require a String first argument.
        # A Numeric property must keep its raw string value here instead of being cast to
        # Float, otherwise ClickHouse raises ILLEGAL_TYPE_OF_ARGUMENT on a Float64 argument.
        printed = self._print_select(f"select {expr} from events")
        assert f"{ch_fn}(accurateCastOrNull" not in printed
        assert f"{ch_fn}(" in printed

    def test_numeric_property_still_cast_outside_string_parser(self):
        # Without an explicit string parser, a Numeric property is still cast to Float.
        printed = self._print_select("select properties.$screen_width from events")
        assert "accurateCastOrNull" in printed

    def test_numeric_property_cast_when_explicitly_stringified_inside_parser(self):
        # toString resets the suppression, so the inner Numeric property is cast again.
        printed = self._print_select("select toFloatOrZero(toString(properties.$screen_width)) from events")
        assert "toFloat64OrZero(toString(accurateCastOrNull" in printed

    def _print_select(self, select: str) -> str:
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return _normalize_snapshot_sql(pretty_print_in_tests(query, self.team.pk))


class TestJSONExtractToMaterializedColumn(ClickhouseTestMixin, BaseTest):
    def _print_select(self, select: str, restricted_properties: set[tuple[str, int]] | None = None):
        expr = parse_select(select)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        if restricted_properties is not None:
            context.restricted_properties = restricted_properties
        query, _ = prepare_and_print_ast(
            expr,
            context,
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

    def _assert_typed_jsonextract_fallback(self, printed: str) -> None:
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "JSONExtract" not in printed, printed
            assert "events.properties." in printed, printed
            assert "accurateCastOrNull" in printed, printed
        else:
            assert "JSONExtract(events.properties" in printed, printed

    @parameterized.expand(
        [
            ("bare_properties", "select JSONExtractString(properties, '$browser') from events"),
            ("table_alias", "select JSONExtractString(e.properties, '$browser') from events e"),
        ]
    )
    def test_jsonextractstring_rewritten_to_mat_column(self, _name: str, query: str):
        with materialized("events", "$browser"):
            printed = self._print_select(query)
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events_json" in printed, printed
                assert "properties.`$browser`" in printed, printed
                assert "mat_$browser" not in printed, printed
                assert "JSONExtractString" not in printed, printed
                return

            assert "mat_$browser" in printed, f"Expected mat_$browser in output, got: {printed}"
            assert "JSONExtractString" not in printed, f"Expected no JSONExtractString, got: {printed}"

    def test_jsonextractstring_rewrites_all_calls_in_same_query(self):
        with materialized("events", "$browser"), materialized("events", "$os"):
            printed = self._print_select(
                "select JSONExtractString(properties, '$browser'), JSONExtractString(properties, '$os') from events"
            )
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events_json" in printed, printed
                assert "properties.`$browser`" in printed, printed
                assert "properties.`$os`" in printed, printed
                assert "mat_" not in printed, printed
                assert "JSONExtractString(events.properties" not in printed, printed
                return

            assert "mat_$browser" in printed, printed
            assert "mat_$os" in printed, printed
            assert "JSONExtractString(events.properties" not in printed, printed

    @parameterized.expand(
        [
            ("no_mat_column", "select JSONExtractString(properties, 'some_random_prop_xyz') from events"),
            ("three_args", "select JSONExtractString(properties, '$browser', 'nested') from events"),
            ("non_json_field", "select JSONExtractString(event, '$browser') from events"),
        ]
    )
    def test_jsonextract_not_rewritten(self, _name: str, query: str):
        printed = self._print_select(query)
        assert "mat_" not in printed, f"Expected no mat_ column in output, got: {printed}"

    def test_typed_jsonextract_rewritten_to_matching_typed_mat_column(self):
        with materialized(
            "events",
            "typed_json_float",
            is_nullable=True,
            column_type="Nullable(Float64)",
        ):
            printed = self._print_select(
                "select JSONExtract(properties, 'typed_json_float', 'Nullable(Float64)') from events"
            )
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events_json" in printed, printed
                assert "events.properties.typed_json_float" in printed, printed
                assert "accurateCastOrNull" in printed, printed
                assert "JSONExtract" not in printed, printed
                assert "mat_typed_json_float" not in printed, printed
                return

            assert "mat_typed_json_float" in printed, printed
            assert "JSONExtract(events.properties" not in printed, printed

    def test_typed_jsonextract_not_rewritten_for_mismatched_mat_column_type(self):
        with materialized("events", "typed_json_float", is_nullable=True):
            printed = self._print_select(
                "select JSONExtract(properties, 'typed_json_float', 'Nullable(Float64)') from events"
            )
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events.properties.typed_json_float" in printed, printed
                assert "accurateCastOrNull" in printed, printed
                assert "JSONExtract" not in printed, printed
                assert "mat_typed_json_float" not in printed, printed
                return

            assert "mat_typed_json_float" not in printed, printed
            self._assert_typed_jsonextract_fallback(printed)

    def test_typed_jsonextract_rewritten_despite_type_spelling_differences(self):
        with materialized("events", "typed_json_dt", column_type="DateTime64(6, 'UTC')"):
            printed = self._print_select(
                "select JSONExtract(properties, 'typed_json_dt', 'DateTime64(6,\\'UTC\\')') from events"
            )
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events.properties.typed_json_dt" in printed, printed
                assert "accurateCastOrNull" in printed, printed
                assert "JSONExtract" not in printed, printed
                assert "mat_typed_json_dt" not in printed, printed
                return

            assert "mat_typed_json_dt" in printed, printed
            assert "JSONExtract(events.properties" not in printed, printed

    def test_typed_jsonextract_not_rewritten_for_nullability_widening(self):
        # JSONExtract(..., 'String') yields '' for missing keys while a Nullable(String)
        # column yields NULL, so this rewrite would change results despite looking lossless.
        with materialized("events", "$browser", is_nullable=True):
            printed = self._print_select("select JSONExtract(properties, '$browser', 'String') from events")
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events.properties.`$browser`" in printed, printed
                assert "accurateCastOrNull" in printed, printed
                assert "JSONExtract" not in printed, printed
                assert "mat_" not in printed, printed
                return

            assert "mat_" not in printed, printed

    def test_jsonextractint_rewritten_only_for_new_events_schema(self):
        with materialized("events", "$browser"):
            printed = self._print_select("select JSONExtractInt(properties, '$browser') from events")
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert "events.properties.`$browser`" in printed, printed
                assert "accurateCastOrNull" in printed, printed
                assert "JSONExtractInt" not in printed, printed
                assert "mat_" not in printed, printed
                return

            assert "mat_" not in printed, f"Expected no mat_ column in output, got: {printed}"

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_new_events_schema_jsonextract_rewrites_use_json_subcolumns(self):
        printed = self._print_select(
            "select JSONExtractInt(properties, 'metric'), "
            "JSONExtract(properties, 'score', 'Nullable(Float64)'), "
            "JSONExtractString(properties, 'email') "
            "from events"
        )

        assert "events_json" in printed, printed
        assert "events.properties.metric" in printed, printed
        assert "events.properties.score" in printed, printed
        assert "events.properties.email" in printed, printed
        assert "accurateCastOrNull" in printed, printed
        assert "JSONExtract" not in printed, printed
        assert "toJSONString(events.properties)" not in printed, printed
        assert "toJSONString(events.properties.^email)" in printed, printed

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_new_events_schema_nested_jsonextractstring_uses_string_default(self):
        printed = self._print_select("select JSONExtractString(properties, 'metadata', 'score') from events")

        assert "ifNull(toString(events.properties.metadata.score), '')" in printed, printed
        assert "JSONExtractString" not in printed, printed

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_new_events_schema_jsonextract_non_nullable_type_uses_default(self):
        printed = self._print_select("select JSONExtract(properties, 'score', 'Float64') from events")

        assert "events.properties.score" in printed, printed
        assert "accurateCastOrNull" in printed, printed
        assert "defaultValueOfTypeName" in printed, printed
        assert "JSONExtract" not in printed, printed

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_new_events_schema_jsonextract_array_uses_json_serialized_subcolumn(self):
        printed = self._print_select(
            "select JSONExtract(ifNull(properties.arr_field, '[]'), 'Array(String)') from events"
        )

        assert "events_json" in printed, printed
        assert "toJSONString(events.properties.arr_field)" in printed, printed
        assert "toJSONString(events.properties.^arr_field)" in printed, printed
        assert "JSONExtract(events.properties" not in printed, printed

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_new_events_schema_jsonextract_respects_restricted_properties(self):
        printed = self._print_select(
            "select JSONExtractInt(properties, 'secret'), "
            "JSONExtract(properties, 'secret', 'Nullable(Float64)'), "
            "JSONExtractString(properties, 'email') "
            "from events",
            restricted_properties={
                ("secret", PropertyDefinition.Type.EVENT),
                ("email", PropertyDefinition.Type.EVENT),
            },
        )

        assert "events.properties.secret" not in printed, printed
        assert "events.properties.email" not in printed, printed
        assert "JSONExtract" not in printed, printed

    @parameterized.expand(
        [
            ("int", "JSONExtractInt(properties, 'metric')", "Int64", "0"),
            ("uint", "JSONExtractUInt(properties, 'metric')", "UInt64", "0"),
            ("float", "JSONExtractFloat(properties, 'metric')", "Float64", "0.0"),
            ("bool", "JSONExtractBool(properties, 'flag')", "Bool", "0"),
        ]
    )
    def test_scalar_jsonextract_rewritten_to_casted_json_subcolumn(
        self, _name: str, expression: str, cast_type: str, default_value: str
    ):
        printed = self._print_select(f"select {expression} from events")
        if not settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "events.properties." not in printed, printed
            return

        property_name = "flag" if "flag" in expression else "metric"
        assert f"events.properties.{property_name}" in printed, printed
        assert "accurateCastOrNull" in printed, printed
        assert cast_type in printed, printed
        assert f", {default_value})" in printed, printed
        assert "JSONExtract" not in printed, printed

    def _seed_edge_case_events(self):
        _create_event(
            team=self.team,
            distinct_id="u_set",
            event="pageview",
            properties={"$browser": "Chrome", "tag": "set"},
        )
        _create_event(
            team=self.team,
            distinct_id="u_empty",
            event="pageview",
            properties={"$browser": "", "tag": "empty"},
        )
        _create_event(
            team=self.team,
            distinct_id="u_null_str",
            event="pageview",
            properties={"$browser": "null", "tag": "null_str"},
        )
        _create_event(
            team=self.team,
            distinct_id="u_json_null",
            event="pageview",
            properties={"$browser": None, "tag": "json_null"},
        )
        _create_event(
            team=self.team,
            distinct_id="u_unset",
            event="pageview",
            properties={"tag": "unset"},
        )
        flush_persons_and_events()

    def _run_and_collect(
        self, extract_expr: str = "JSONExtractString(properties, '$browser')"
    ) -> tuple[dict[str, Any], str]:
        hogql = f"SELECT properties.tag, {extract_expr} FROM events WHERE event = 'pageview' ORDER BY properties.tag"
        response = execute_hogql_query(hogql, team=self.team)
        assert response.results is not None
        values = {row[0]: row[1] for row in response.results}
        return values, response.clickhouse or ""

    def test_rewrite_value_semantics_no_mat_column(self):
        self._seed_edge_case_events()
        values, sql = self._run_and_collect()
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            access_values, _ = self._run_and_collect("properties.$browser")
            assert values == access_values
            assert "events_json" in sql, sql
            assert "events.properties.`$browser`" in sql, sql
            assert "JSONExtractString(events.properties" not in sql, sql
            assert "mat_$browser" not in sql, sql
            return

        assert "JSONExtractString(events.properties" in sql, sql
        assert "mat_$browser" not in sql, sql
        # JSONExtractString returns '' for JSON null (type mismatch), not 'null'.
        # Only JSONExtractRaw returns the literal string 'null' for JSON null.
        assert values == {"set": "Chrome", "empty": "", "null_str": "null", "json_null": "", "unset": ""}

    def test_rewrite_value_semantics_non_nullable_mat_column(self):
        self._seed_edge_case_events()
        with materialized("events", "$browser", is_nullable=False):
            values, sql = self._run_and_collect()
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            access_values, _ = self._run_and_collect("properties.$browser")
            assert values == access_values
            assert "events_json" in sql, sql
            assert "events.properties.`$browser`" in sql, sql
            assert "mat_$browser" not in sql, sql
            return

        assert "JSONExtractString(events.properties" not in sql, sql
        assert "mat_$browser" in sql, sql
        # Rewritten call goes through the standard property-access path, so the mat
        # column is wrapped in nullIf(nullIf(col, ''), 'null') — same as properties.$x.
        assert "nullIf(nullIf(events.`mat_$browser`" in sql, sql
        assert values == {"set": "Chrome", "empty": None, "null_str": None, "json_null": None, "unset": None}

    def test_rewrite_value_semantics_nullable_mat_column(self):
        self._seed_edge_case_events()
        with materialized("events", "$browser", is_nullable=True):
            values, sql = self._run_and_collect()
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            access_values, _ = self._run_and_collect("properties.$browser")
            assert values == access_values
            assert "events_json" in sql, sql
            assert "events.properties.`$browser`" in sql, sql
            assert "mat_$browser" not in sql, sql
            return

        assert "JSONExtractString(events.properties" not in sql, sql
        assert "mat_$browser" in sql, sql
        assert values == {"set": "Chrome", "empty": "", "null_str": "null", "json_null": None, "unset": None}

    @parameterized.expand([("non_nullable", False), ("nullable", True)])
    def test_jsonextractstring_synonym_of_properties_access(self, _name: str, is_nullable: bool):
        self._seed_edge_case_events()
        with materialized("events", "$browser", is_nullable=is_nullable):
            extract_values, _ = self._run_and_collect("JSONExtractString(properties, '$browser')")
            access_values, _ = self._run_and_collect("properties.$browser")
        assert extract_values == access_values


# ── Timezone index pruning tests ──────────────────────────────────────────────
#
# The events table uses:
#     PARTITION BY toYYYYMM(timestamp)
#     ORDER BY (team_id, toDate(timestamp), event, ...)
#
# HogQL wraps timestamp fields with toTimeZone(timestamp, tz) for timezone
# support (see PropertySwapper.visit_field). ClickHouse can't derive partition
# or primary key bounds from toTimeZone() comparisons. Since toTimeZone only
# changes display metadata (not the underlying epoch), we move the timezone
# from the field side to the constant side in top-level WHERE range
# comparisons, letting the planner see bare timestamp for pruning.


def _get_index_by_type(indexes: list[dict], type_name: str) -> dict | None:
    for idx in indexes:
        if idx.get("Type") == type_name:
            return idx
    return None


class TestTimezoneIndexPruning(ClickhouseTestMixin, BaseTest):
    """
    Verify that timezone-aware date filters allow ClickHouse to prune
    partitions and use primary key indexes on the events table.
    """

    def setUp(self):
        super().setUp()
        # Create events across multiple months so ClickHouse produces
        # meaningful EXPLAIN output (otherwise it optimizes to NullSource)
        for month in range(1, 7):
            for day_offset in range(5):
                _create_event(
                    team=self.team,
                    distinct_id=f"user_{day_offset}",
                    event="$pageview",
                    timestamp=datetime(2024, month, 10 + day_offset),
                )
        flush_persons_and_events()

    def _events_table_ref(self) -> str:
        return "events_json" if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else "events"

    def _assert_primary_key_uses_timestamp_range(self, primary_key: dict) -> None:
        pk_keys = primary_key.get("Keys", [])
        expected_timestamp_key = "timestamp" if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else "toDate(timestamp)"
        assert any(expected_timestamp_key in key for key in pk_keys), (
            f"Expected PK to use {expected_timestamp_key}, got Keys={pk_keys}"
        )

    def _compile_hogql(self, hogql: str, timezone: str = "UTC") -> tuple[str, dict]:
        self.team.timezone = timezone
        self.team.save()
        # This class asserts the structural shape of toTimeZone stripping (a PropertySwapper concern).
        # Predicate pushdown is orthogonal: it relocates the (already-stripped) WHERE into an events subquery,
        # changing where these comparisons appear without changing the tz behavior. Disable it here so the
        # assertions stay about tz stripping; pushdown has its own test suite.
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(pushDownPredicates=False),
        )
        node = parse_select(hogql)
        clickhouse_sql, _ = prepare_and_print_ast(node, context=context, dialect="clickhouse")
        return clickhouse_sql, context.values

    def test_bare_timestamp_prunes_partition_and_primary_key(self):
        """Bare timestamp comparisons allow partition and primary key pruning."""
        sql = (
            f"SELECT count() FROM {self._events_table_ref()} "
            f"WHERE team_id = {self.team.pk} "
            f"AND timestamp >= '2024-03-01' AND timestamp < '2024-04-01'"
        )
        indexes = get_indexes_from_explain(sql)

        partition = _get_index_by_type(indexes, "Partition")
        assert partition is not None
        assert partition.get("Condition") != "true", (
            f"Partition pruning should work with bare timestamp, got Condition={partition.get('Condition')!r}"
        )

        primary_key = _get_index_by_type(indexes, "PrimaryKey")
        assert primary_key is not None
        self._assert_primary_key_uses_timestamp_range(primary_key)
        assert primary_key.get("Condition") != "true"

    @parameterized.expand(["UTC", "America/New_York"])
    def test_toTimeZone_breaks_partition_and_pk_pruning(self, tz):
        """toTimeZone(timestamp, tz) breaks partition pruning and PK date usage.

        If this test starts failing, ClickHouse has learned to derive
        toYYYYMM(timestamp) / toDate(timestamp) bounds from toTimeZone()
        comparisons, and we can remove the toTimeZone-stripping workaround
        entirely (PropertySwapper.visit_compare_operation).
        """
        sql = (
            f"SELECT count() FROM {self._events_table_ref()} "
            f"WHERE team_id = {self.team.pk} "
            f"AND toTimeZone(timestamp, '{tz}') >= '2024-03-01' "
            f"AND toTimeZone(timestamp, '{tz}') < '2024-04-01'"
        )
        indexes = get_indexes_from_explain(sql)

        partition = _get_index_by_type(indexes, "Partition")
        assert partition is not None
        assert partition.get("Condition") == "true", (
            f"tz={tz}: ClickHouse is now pruning partitions with toTimeZone — "
            f"the workaround may be removable. "
            f"Partition Condition={partition.get('Condition')!r}"
        )

    def test_hogql_compiled_query_has_partition_pruning(self):
        """The HogQL pipeline strips toTimeZone from WHERE comparisons to restore pruning."""
        sql, values = self._compile_hogql(
            "SELECT count() FROM events WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        indexes = get_indexes_from_explain(sql, values)

        partition = _get_index_by_type(indexes, "Partition")
        assert partition is not None
        assert partition.get("Condition") != "true", (
            f"Expected partition pruning. Partition Condition={partition.get('Condition')!r}"
        )

        primary_key = _get_index_by_type(indexes, "PrimaryKey")
        assert primary_key is not None
        self._assert_primary_key_uses_timestamp_range(primary_key)

    def test_toTimeZone_stripped_from_where_but_kept_in_select(self):
        """toTimeZone should be stripped from top-level WHERE range comparisons
        but preserved in SELECT expressions and inside function calls."""
        sql, _ = self._compile_hogql(
            "SELECT timestamp FROM events WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        where_clause = sql.split("WHERE")[1]
        select_clause = sql.split("WHERE")[0]
        assert "toTimeZone" not in where_clause, f"Expected toTimeZone stripped from WHERE, got:\n{where_clause}"
        assert "toTimeZone" in select_clause, f"Expected toTimeZone in SELECT for display, got:\n{select_clause}"

    def test_toTimeZone_not_stripped_in_join_on(self):
        """toTimeZone should NOT be stripped from JOIN ON comparisons — only WHERE benefits from pruning."""
        sql, _ = self._compile_hogql(
            "SELECT e.timestamp FROM events e LEFT JOIN events e2 "
            "ON e.person_id = e2.person_id AND e2.timestamp >= e.timestamp "
            "WHERE e.timestamp >= '2024-03-01' AND e.timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        # The JOIN ON greaterOrEquals should still have toTimeZone wrapping
        assert re.search(r"greaterOrEquals\(toTimeZone\(", sql), (
            f"Expected toTimeZone preserved in JOIN ON greaterOrEquals, got:\n{sql}"
        )
        # The WHERE comparisons should have toTimeZone stripped (bare e.timestamp)
        assert re.search(r"greaterOrEquals\(e\.timestamp,", sql), (
            f"Expected bare e.timestamp in WHERE greaterOrEquals, got:\n{sql}"
        )
        assert re.search(r"less\(e\.timestamp,", sql), f"Expected bare e.timestamp in WHERE less, got:\n{sql}"

    def test_toTimeZone_not_stripped_inside_function_calls(self):
        """toTimeZone should NOT be stripped from comparisons inside function calls."""
        sql, _ = self._compile_hogql(
            "SELECT if(timestamp >= '2024-03-01', 'yes', 'no') FROM events",
            timezone="America/New_York",
        )
        assert "toTimeZone" in sql, f"Expected toTimeZone preserved inside if(), got:\n{sql}"

        # Mix: WHERE comparison (stripped) + nested in if() in SELECT (preserved)
        sql, _ = self._compile_hogql(
            "SELECT if(timestamp >= '2024-01-01', 'new', 'old') FROM events "
            "WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        where_clause = sql.split("WHERE")[1]
        select_clause = sql.split("WHERE")[0]
        assert "toTimeZone" not in where_clause, f"Expected toTimeZone stripped from WHERE, got:\n{where_clause}"
        assert "toTimeZone" in select_clause, f"Expected toTimeZone preserved in SELECT if(), got:\n{select_clause}"

    def test_subquery_in_where_does_not_inherit_stripping(self):
        """A subquery's SELECT inside a WHERE should NOT inherit stripping from the outer WHERE."""
        sql, _ = self._compile_hogql(
            "SELECT count() FROM events "
            "WHERE timestamp >= (SELECT min(timestamp) FROM events WHERE timestamp >= '2024-01-01')",
            timezone="America/New_York",
        )
        # The outer WHERE >= should strip toTimeZone from events.timestamp
        assert re.search(r"greaterOrEquals\(events\.timestamp,", sql), (
            f"Expected bare events.timestamp in outer WHERE, got:\n{sql}"
        )
        # The inner subquery's SELECT min(timestamp) should still have toTimeZone
        assert re.search(r"min\(toTimeZone\(", sql), f"Expected toTimeZone preserved in subquery SELECT, got:\n{sql}"
        # The inner WHERE should also strip toTimeZone
        assert re.search(r"greaterOrEquals\(events\.timestamp, toDateTime64", sql), (
            f"Expected bare events.timestamp in inner WHERE too, got:\n{sql}"
        )

    def test_toTimeZone_preserved_in_having(self):
        """HAVING should preserve toTimeZone — only WHERE/PREWHERE benefits from pruning."""
        sql, _ = self._compile_hogql(
            "SELECT event, max(timestamp) as max_ts FROM events "
            "WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01' "
            "GROUP BY event HAVING max(timestamp) >= '2024-03-15'",
            timezone="America/New_York",
        )
        # The HAVING max(timestamp) comparison should preserve toTimeZone
        assert re.search(r"HAVING.*toTimeZone", sql), f"Expected toTimeZone preserved in HAVING, got:\n{sql}"

    def _assert_correct_results(self, hogql: str, timezone: str, expected_count: int):
        self.team.timezone = timezone
        self.team.save()
        response = execute_hogql_query(hogql, team=self.team)
        assert response.results is not None
        assert response.results[0][0] == expected_count, (
            f"tz={timezone}: expected {expected_count}, got {response.results[0][0]}"
        )

    def test_dst_boundary_does_not_drop_events(self):
        """America/New_York DST switch: events near midnight must not be missed."""
        _create_event(
            team=self.team, distinct_id="dst_user", event="dst_test", timestamp=datetime(2024, 3, 10, 5, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="dst_user", event="dst_test", timestamp=datetime(2024, 3, 10, 6, 30, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'dst_test' AND timestamp >= '2024-03-10' AND timestamp < '2024-03-11'"
        self._assert_correct_results(hogql, timezone="America/New_York", expected_count=2)

    def test_positive_utc_offset_does_not_drop_events(self):
        """Asia/Tokyo (UTC+9): midnight Tokyo = 15:00 UTC the previous day."""
        _create_event(
            team=self.team, distinct_id="tokyo_user", event="tokyo_test", timestamp=datetime(2024, 2, 29, 15, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="tokyo_user", event="tokyo_test", timestamp=datetime(2024, 3, 1, 14, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'tokyo_test' AND timestamp >= '2024-03-01' AND timestamp < '2024-03-02'"
        self._assert_correct_results(hogql, timezone="Asia/Tokyo", expected_count=2)

    def test_utc_returns_correct_results(self):
        _create_event(
            team=self.team, distinct_id="utc_user", event="utc_test", timestamp=datetime(2024, 3, 1, 0, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="utc_user", event="utc_test", timestamp=datetime(2024, 3, 1, 23, 30, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'utc_test' AND timestamp >= '2024-03-01' AND timestamp < '2024-03-02'"
        self._assert_correct_results(hogql, timezone="UTC", expected_count=2)

    def test_brazil_historical_dst_does_not_drop_events(self):
        """Brazil dropped DST in 2019. Events during the old DST period must still work."""
        _create_event(
            team=self.team, distinct_id="brazil_user", event="brazil_test", timestamp=datetime(2018, 11, 15, 2, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="brazil_user", event="brazil_test", timestamp=datetime(2018, 11, 15, 12, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'brazil_test' AND timestamp >= '2018-11-15' AND timestamp < '2018-11-16'"
        self._assert_correct_results(hogql, timezone="America/Sao_Paulo", expected_count=2)

    def test_half_hour_offset_does_not_drop_events(self):
        """Asia/Kolkata (UTC+5:30): midnight Kolkata = 18:30 UTC the previous day."""
        _create_event(
            team=self.team, distinct_id="kolkata_user", event="kolkata_test", timestamp=datetime(2024, 2, 29, 18, 30, 0)
        )
        _create_event(
            team=self.team, distinct_id="kolkata_user", event="kolkata_test", timestamp=datetime(2024, 3, 1, 17, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'kolkata_test' AND timestamp >= '2024-03-01' AND timestamp < '2024-03-02'"
        self._assert_correct_results(hogql, timezone="Asia/Kolkata", expected_count=2)

    def test_lord_howe_half_hour_dst_does_not_drop_events(self):
        """Australia/Lord_Howe: 30-minute DST shift (UTC+10:30 → UTC+11)."""
        _create_event(
            team=self.team, distinct_id="lhi_user", event="lhi_test", timestamp=datetime(2024, 1, 15, 13, 0, 0)
        )
        _create_event(
            team=self.team, distinct_id="lhi_user", event="lhi_test", timestamp=datetime(2024, 1, 15, 22, 0, 0)
        )
        flush_persons_and_events()

        hogql = "SELECT count() FROM events WHERE event = 'lhi_test' AND timestamp >= '2024-01-16' AND timestamp < '2024-01-17'"
        self._assert_correct_results(hogql, timezone="Australia/Lord_Howe", expected_count=2)

    def test_constant_gets_timezone_annotation(self):
        """Bare string constants get wrapped with toDateTime64(..., 6, tz)."""
        sql, values = self._compile_hogql(
            "SELECT count() FROM events WHERE timestamp >= '2024-03-01' AND timestamp < '2024-04-01'",
            timezone="America/New_York",
        )
        assert "toDateTime64" in sql, f"Expected toDateTime64 wrapping on constants, got:\n{sql}"
        assert "America/New_York" in values.values(), f"Expected timezone in parameterized values, got:\n{values}"

    def test_alias_preserved_when_recursing_into_assumeNotNull(self):
        """Alias wrappers on assumeNotNull(toDateTime(...)) constants must be preserved."""
        from posthog.hogql import ast as ast_module
        from posthog.hogql.transforms.property_types import PropertySwapper

        inner_call = ast_module.Call(name="toDateTime", args=[ast_module.Constant(value="2024-03-01")])
        assume_call = ast_module.Call(name="assumeNotNull", args=[inner_call])
        aliased = ast_module.Alias(alias="date_from", expr=assume_call)

        result = PropertySwapper._ensure_constant_has_timezone(aliased, "America/New_York")

        assert isinstance(result, ast_module.Alias), f"Expected Alias wrapper preserved, got {type(result).__name__}"
        assert result.alias == "date_from"
        assert isinstance(result.expr, ast_module.Call)
        assert result.expr.name == "assumeNotNull"

    def test_alias_not_added_when_not_present(self):
        """When there's no Alias wrapper, the result should not have one either."""
        from posthog.hogql import ast as ast_module
        from posthog.hogql.transforms.property_types import PropertySwapper

        inner_call = ast_module.Call(name="toDateTime", args=[ast_module.Constant(value="2024-03-01")])
        assume_call = ast_module.Call(name="assumeNotNull", args=[inner_call])

        result = PropertySwapper._ensure_constant_has_timezone(assume_call, "America/New_York")

        assert isinstance(result, ast_module.Call), f"Expected Call, got {type(result).__name__}"
        assert result.name == "assumeNotNull"
