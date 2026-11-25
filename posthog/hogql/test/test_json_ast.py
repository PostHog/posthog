import math
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.json_ast import deserialize_ast, serialize_ast
from posthog.hogql.parser import parse_program, parse_select

PYTHON_ONLY_CONSTANTS = [
    datetime(2026, 1, 2, 3, 4, 5, 678, tzinfo=UTC),
    datetime(2026, 1, 2, 3, 4, 5),
    date(2026, 1, 2),
    UUID("0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"),
    (1, "a"),
    [date(2026, 1, 2), (UUID("0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"), [1.5])],
    2**70,
    -(2**70),
]


class SettingsSubclass(HogQLQuerySettings):
    max_bytes_before_external_sort: int | None = 1


def round_trip(node: ast.AST) -> ast.AST:
    return deserialize_ast(serialize_ast(node))


class TestSerializeAst(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "joins_operators_and_positions",
                parse_select(
                    "select e.a + 1 as total, not b from events e left join persons p on e.person_id = p.id "
                    "where c in (1, 2) and d like 'x%' order by total desc limit 10 offset 5"
                ),
            ),
            (
                "ctes_and_named_windows",
                parse_select(
                    "with 1 as x, y as (select 2) select row_number() over w, "
                    "sum(a) over (partition by b order by c rows between 1 preceding and current row) "
                    "from events window w as (partition by d)"
                ),
            ),
            ("columns_replace", parse_select("select columns(* replace (1 as a)) from events")),
            ("enum_member_used_as_a_string", ast.Field(chain=["properties", ast.CompareOperationOp.Eq])),
            ("special_numbers", parse_select("select inf, -inf, 123456789012345678901234567890, 1.5, true, null")),
            ("hogqlx_attributes", parse_select("select <Sparkline data={[1, 2]} type='line' /> from events")),
            (
                "hog_program_dict_and_catch",
                parse_program("let x := {'a': 1}; try { throw Error('x') } catch (e: Error) { print(e) }"),
            ),
            ("python_only_constants", ast.Tuple(exprs=[ast.Constant(value=value) for value in PYTHON_ONLY_CONSTANTS])),
            (
                "hidden_alias_and_settings",
                ast.SelectQuery(
                    select=[ast.Alias(alias="a", expr=ast.Field(chain=["b", 0]), hidden=True)],
                    settings=HogQLQuerySettings(optimize_aggregation_in_order=True),
                    view_name="v",
                ),
            ),
            (
                "dict_entries_named_node",
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    ctes={"node": ast.CTE(name="node", expr=ast.Constant(value=2), cte_type="column")},
                    window_exprs={"node": ast.WindowExpr(partition_by=[ast.Field(chain=["a"])])},
                ),
            ),
        ]
    )
    def test_round_trip_preserves_tree(self, _name: str, node: ast.AST) -> None:
        self.assertEqual(round_trip(node), node)

    def test_nan_round_trips_as_nan(self) -> None:
        restored = round_trip(ast.Constant(value=float("nan")))

        assert isinstance(restored, ast.Constant)
        self.assertTrue(math.isnan(restored.value))

    def test_resolved_types_are_left_out(self) -> None:
        resolved = ast.Constant(value=1, type=ast.IntegerType())

        self.assertEqual(round_trip(resolved), ast.Constant(value=1))

    @parameterized.expand(
        [
            ("constant_type", ast.Constant(value=Decimal("1.5"))),
            ("settings_subclass", ast.SelectQuery(select=[], settings=SettingsSubclass())),
        ]
    )
    def test_value_the_reader_cannot_rebuild_fails_to_serialize(self, _name: str, node: ast.AST) -> None:
        with self.assertRaises(TypeError):
            serialize_ast(node)

    def test_unknown_constant_value_type_fails_to_deserialize(self) -> None:
        with self.assertRaisesMessage(ValueError, "Unknown constant value_type: 'decimal'"):
            deserialize_ast('{"node": "Constant", "value": "1.5", "value_type": "decimal"}')
