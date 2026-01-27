from typing import Optional, cast

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import (
    EventsPredicatePushdownExtractor,
    JoinedTableReferenceFinder,
    TableAliasUnwrapper,
    references_joined_table,
    unwrap_table_aliases,
)
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import clone_expr


def make_field(chain: list[str | int], table_type: Optional[ast.TableType] = None) -> ast.Field:
    """Create a field with optional type information."""
    field_type = None
    if table_type is not None and len(chain) > 0:
        last = chain[-1]
        field_type = ast.FieldType(name=str(last), table_type=table_type)
    return ast.Field(chain=chain, type=field_type)


def make_events_table_type() -> ast.TableType:
    """Create a TableType for the events table."""
    return ast.TableType(table=EventsTable())


def make_alias_type(alias: str, table_type: ast.TableType) -> ast.TableAliasType:
    """Create a TableAliasType wrapping a TableType."""
    return ast.TableAliasType(alias=alias, table_type=table_type)


def make_lazy_join_type(field: str) -> ast.LazyJoinType:
    """Create a mock LazyJoinType for testing."""
    from posthog.hogql.database.models import LazyJoin

    return ast.LazyJoinType(
        table_type=make_events_table_type(),
        field=field,
        lazy_join=LazyJoin(from_field=["id"], join_table=EventsTable(), join_function=lambda *args: None),
    )


def make_select_query_alias_type(alias: str) -> ast.SelectQueryAliasType:
    """Create a SelectQueryAliasType for testing."""
    return ast.SelectQueryAliasType(alias=alias, select_query_type=None)  # type: ignore[arg-type]


class TestJoinedTableReferenceFinder:
    @parameterized.expand(
        [
            # (test_name, field_chain, joined_aliases, expected_found)
            ("field_in_joined_aliases", ["session", "duration"], {"session"}, True),
            ("field_not_in_joined_aliases", ["events", "timestamp"], {"session"}, False),
            ("nested_field_in_joined_aliases", ["events__session", "id"], {"events__session"}, True),
            ("empty_joined_aliases", ["session", "duration"], set(), False),
            ("multiple_aliases_match_first", ["person", "id"], {"person", "session"}, True),
            ("multiple_aliases_no_match", ["events", "id"], {"person", "session"}, False),
        ]
    )
    def test_field_chain_detection(self, _name, field_chain, joined_aliases, expected_found):
        field = make_field(field_chain)
        finder = JoinedTableReferenceFinder(joined_aliases)
        finder.visit(field)
        assert finder.found_joined_reference == expected_found

    def test_lazy_join_type_detected_via_type_system(self):
        """Fields typed with LazyJoinType should be detected even if chain doesn't match."""
        lazy_join_type = make_lazy_join_type("session")
        field = ast.Field(
            chain=["custom_alias", "duration"],
            type=ast.FieldType(name="duration", table_type=lazy_join_type),
        )
        finder = JoinedTableReferenceFinder(set())  # Empty set - rely on type system
        finder.visit(field)
        assert finder.found_joined_reference is True

    def test_select_query_alias_type_detected_via_type_system(self):
        """Fields typed with SelectQueryAliasType should be detected."""
        subquery_type = make_select_query_alias_type("subquery")
        field = ast.Field(
            chain=["subquery", "id"],
            type=ast.FieldType(name="id", table_type=subquery_type),
        )
        finder = JoinedTableReferenceFinder(set())
        finder.visit(field)
        assert finder.found_joined_reference is True

    def test_property_type_with_lazy_join_detected(self):
        """PropertyType wrapping a LazyJoinType should be detected."""
        lazy_join_type = make_lazy_join_type("person")
        field_type = ast.FieldType(name="properties", table_type=lazy_join_type)
        property_type = ast.PropertyType(chain=["email"], field_type=field_type)
        field = ast.Field(chain=["person", "properties", "email"], type=property_type)

        finder = JoinedTableReferenceFinder(set())
        finder.visit(field)
        assert finder.found_joined_reference is True

    def test_table_type_not_detected_as_joined(self):
        """Fields typed with plain TableType should not be detected as joined."""
        table_type = make_events_table_type()
        field = ast.Field(
            chain=["events", "timestamp"],
            type=ast.FieldType(name="timestamp", table_type=table_type),
        )
        finder = JoinedTableReferenceFinder(set())
        finder.visit(field)
        assert finder.found_joined_reference is False


class TestReferencesJoinedTable:
    def test_simple_comparison_with_joined_field(self):
        expr = parse_expr("session.duration > 0")
        # Clone to clear types since parse_expr doesn't resolve types
        expr = clone_expr(expr, clear_types=True)
        # Manually set the field chain for testing
        assert references_joined_table(expr, {"session"}) is True

    def test_simple_comparison_without_joined_field(self):
        expr = parse_expr("timestamp > '2024-01-01'")
        expr = clone_expr(expr, clear_types=True)
        assert references_joined_table(expr, {"session"}) is False

    def test_and_expression_with_joined_field(self):
        expr = parse_expr("timestamp > '2024-01-01' AND session.duration > 0")
        expr = clone_expr(expr, clear_types=True)
        assert references_joined_table(expr, {"session"}) is True

    def test_nested_function_with_joined_field(self):
        expr = parse_expr("ifNull(session.duration, 0) > 0")
        expr = clone_expr(expr, clear_types=True)
        assert references_joined_table(expr, {"session"}) is True


class TestTableAliasUnwrapper:
    def test_unwraps_table_alias_type(self):
        """TableAliasType should be unwrapped to the underlying TableType."""
        events_table_type = make_events_table_type()
        alias_type = make_alias_type("e", events_table_type)
        field = ast.Field(
            chain=["e", "timestamp"],
            type=ast.FieldType(name="timestamp", table_type=alias_type),
        )

        # Before unwrapping: type is TableAliasType
        assert isinstance(field.type, ast.FieldType)
        assert isinstance(field.type.table_type, ast.TableAliasType)

        unwrapper = TableAliasUnwrapper()
        result = unwrapper.visit(field)

        # After unwrapping: type is TableType, expression prints the same
        assert print_expr(result) == "e.timestamp"
        assert isinstance(result.type, ast.FieldType)
        assert isinstance(result.type.table_type, ast.TableType)
        assert result.type.table_type == events_table_type

    def test_preserves_non_aliased_fields(self):
        """Fields without TableAliasType should be preserved."""
        events_table_type = make_events_table_type()
        field = ast.Field(
            chain=["events", "timestamp"],
            type=ast.FieldType(name="timestamp", table_type=events_table_type),
        )

        unwrapper = TableAliasUnwrapper()
        result = unwrapper.visit(field)

        assert print_expr(result) == "events.timestamp"
        assert isinstance(result.type, ast.FieldType)
        assert result.type.table_type == events_table_type

    def test_preserves_fields_without_type(self):
        """Fields without type information should be preserved."""
        field = ast.Field(chain=["timestamp"])

        unwrapper = TableAliasUnwrapper()
        result = unwrapper.visit(field)

        assert print_expr(result) == "timestamp"
        assert result.type is None

    @parameterized.expand(
        [
            # (test_name, expr_str, expected_output)
            ("comparison_with_alias", "e.timestamp >= '2024-01-01'", "greaterOrEquals(e.timestamp, '2024-01-01')"),
            (
                "and_with_aliases",
                "e.timestamp >= '2024-01-01' AND e.event = 'click'",
                "and(greaterOrEquals(e.timestamp, '2024-01-01'), equals(e.event, 'click'))",
            ),
            ("function_with_alias", "ifNull(e.properties, '')", "ifNull(e.properties, '')"),
        ]
    )
    def test_unwraps_in_expressions(self, _name, expr_str, expected_output):
        """TableAliasType should be unwrapped in nested expressions while preserving structure."""
        expr = parse_expr(expr_str)
        expr = clone_expr(expr, clear_types=True)

        result = unwrap_table_aliases(expr)

        assert print_expr(result) == expected_output

    def test_unwraps_in_comparison_with_typed_field(self):
        """TableAliasType should be unwrapped in comparison with typed field."""
        events_table_type = make_events_table_type()
        alias_type = make_alias_type("e", events_table_type)
        field = ast.Field(
            chain=["e", "timestamp"],
            type=ast.FieldType(name="timestamp", table_type=alias_type),
        )
        comparison = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=field,
            right=ast.Constant(value="2024-01-01"),
        )

        # Before: field has TableAliasType
        assert isinstance(comparison.left.type, ast.FieldType)
        assert isinstance(comparison.left.type.table_type, ast.TableAliasType)

        result = unwrap_table_aliases(comparison)

        # After: expression prints correctly and type is unwrapped
        assert print_expr(result) == "greaterOrEquals(e.timestamp, '2024-01-01')"
        result_cmp = cast(ast.CompareOperation, result)
        assert isinstance(result_cmp.left, ast.Field)
        assert isinstance(result_cmp.left.type, ast.FieldType)
        assert isinstance(result_cmp.left.type.table_type, ast.TableType)

    def test_unwraps_property_type_with_aliased_table(self):
        """PropertyType wrapping FieldType with TableAliasType should be unwrapped."""
        events_table_type = make_events_table_type()
        alias_type = make_alias_type("e", events_table_type)

        # Create a field with PropertyType (e.g., e.properties["$filter_prop"])
        inner_field_type = ast.FieldType(name="properties", table_type=alias_type)
        property_type = ast.PropertyType(chain=["$filter_prop"], field_type=inner_field_type)
        field = ast.Field(
            chain=["e", "properties", "$filter_prop"],
            type=property_type,
        )

        # Before: PropertyType wraps FieldType with TableAliasType
        assert isinstance(field.type, ast.PropertyType)
        assert isinstance(field.type.field_type.table_type, ast.TableAliasType)

        unwrapper = TableAliasUnwrapper()
        result = unwrapper.visit(field)

        # After: PropertyType wraps FieldType with TableType (unwrapped)
        assert isinstance(result.type, ast.PropertyType)
        assert isinstance(result.type.field_type.table_type, ast.TableType)
        assert result.type.field_type.table_type == events_table_type


def print_expr(expr: Optional[ast.Expr]) -> Optional[str]:
    """Print an expression to HogQL string for comparison."""
    if expr is None:
        return None
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.printer import print_prepared_ast

    context = HogQLContext(team_id=1)
    return print_prepared_ast(node=expr, context=context, dialect="hogql")


class TestEventsPredicatePushdownExtractor:
    @parameterized.expand(
        [
            # (test_name, expr_str, joined_aliases, expected_inner, expected_outer)
            (
                "simple_timestamp_filter_pushable",
                "timestamp >= '2024-01-01'",
                set(),
                "greaterOrEquals(timestamp, '2024-01-01')",
                None,
            ),
            (
                "joined_field_not_pushable",
                "session.duration > 0",
                {"session"},
                None,
                "greater(session.duration, 0)",
            ),
            (
                "and_with_all_pushable",
                "timestamp >= '2024-01-01' AND event = 'click'",
                set(),
                "and(greaterOrEquals(timestamp, '2024-01-01'), equals(event, 'click'))",
                None,
            ),
            (
                "and_splits_pushable_from_joined",
                "timestamp >= '2024-01-01' AND session.duration > 0",
                {"session"},
                "greaterOrEquals(timestamp, '2024-01-01')",
                "greater(session.duration, 0)",
            ),
            (
                "or_with_joined_stays_in_outer",
                "timestamp >= '2024-01-01' OR session.duration > 0",
                {"session"},
                None,
                "or(greaterOrEquals(timestamp, '2024-01-01'), greater(session.duration, 0))",
            ),
            (
                "multiple_pushable_predicates",
                "timestamp >= '2024-01-01' AND timestamp < '2024-02-01' AND event = 'click'",
                set(),
                "and(greaterOrEquals(timestamp, '2024-01-01'), less(timestamp, '2024-02-01'), equals(event, 'click'))",
                None,
            ),
            (
                "nested_and_with_joined",
                "(timestamp >= '2024-01-01' AND event = 'click') AND session.duration > 0",
                {"session"},
                "and(greaterOrEquals(timestamp, '2024-01-01'), equals(event, 'click'))",
                "greater(session.duration, 0)",
            ),
            (
                "function_with_joined_field_not_pushable",
                "ifNull(session.duration, 0) > 0",
                {"session"},
                None,
                "greater(ifNull(session.duration, 0), 0)",
            ),
        ]
    )
    def test_predicate_splitting(self, _name, expr_str, joined_aliases, expected_inner, expected_outer):
        expr = parse_expr(expr_str)
        expr = clone_expr(expr, clear_types=True)

        extractor = EventsPredicatePushdownExtractor(joined_aliases)
        inner_where, outer_where = extractor.get_pushdown_predicates(expr)

        assert print_expr(inner_where) == expected_inner
        assert print_expr(outer_where) == expected_outer

    def test_empty_joined_aliases_relies_on_type_system(self):
        """With empty joined_aliases, detection relies entirely on type system."""
        # Create a field with LazyJoinType
        lazy_join_type = make_lazy_join_type("session")
        field = ast.Field(
            chain=["session", "duration"],
            type=ast.FieldType(name="duration", table_type=lazy_join_type),
        )
        comparison = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=field,
            right=ast.Constant(value=0),
        )

        extractor = EventsPredicatePushdownExtractor(set())
        inner_where, outer_where = extractor.get_pushdown_predicates(comparison)

        # Should detect via type system even with empty joined_aliases
        assert inner_where is None
        assert outer_where is not None
