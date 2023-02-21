from posthog.hogql import ast
from posthog.hogql.database import database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_symbols
from posthog.hogql.transforms import expand_asterisks
from posthog.test.base import BaseTest


class TestTransforms(BaseTest):
    def test_asterisk_expander_table(self):
        node = parse_select("select * from events")
        resolve_symbols(node)
        expand_asterisks(node)
        events_table_symbol = ast.TableSymbol(table=database.events)
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], symbol=ast.FieldSymbol(name="uuid", table=events_table_symbol)),
                ast.Field(chain=["event"], symbol=ast.FieldSymbol(name="event", table=events_table_symbol)),
                ast.Field(chain=["properties"], symbol=ast.FieldSymbol(name="properties", table=events_table_symbol)),
                ast.Field(chain=["timestamp"], symbol=ast.FieldSymbol(name="timestamp", table=events_table_symbol)),
                ast.Field(chain=["team_id"], symbol=ast.FieldSymbol(name="team_id", table=events_table_symbol)),
                ast.Field(chain=["distinct_id"], symbol=ast.FieldSymbol(name="distinct_id", table=events_table_symbol)),
                ast.Field(
                    chain=["elements_chain"], symbol=ast.FieldSymbol(name="elements_chain", table=events_table_symbol)
                ),
                ast.Field(chain=["created_at"], symbol=ast.FieldSymbol(name="created_at", table=events_table_symbol)),
            ],
        )

    def test_asterisk_expander_table_alias(self):
        node = parse_select("select * from events e")
        resolve_symbols(node)
        expand_asterisks(node)
        events_table_symbol = ast.TableSymbol(table=database.events)
        events_table_alias_symbol = ast.TableAliasSymbol(table=events_table_symbol, name="e")
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], symbol=ast.FieldSymbol(name="uuid", table=events_table_alias_symbol)),
                ast.Field(chain=["event"], symbol=ast.FieldSymbol(name="event", table=events_table_alias_symbol)),
                ast.Field(
                    chain=["properties"], symbol=ast.FieldSymbol(name="properties", table=events_table_alias_symbol)
                ),
                ast.Field(
                    chain=["timestamp"], symbol=ast.FieldSymbol(name="timestamp", table=events_table_alias_symbol)
                ),
                ast.Field(chain=["team_id"], symbol=ast.FieldSymbol(name="team_id", table=events_table_alias_symbol)),
                ast.Field(
                    chain=["distinct_id"], symbol=ast.FieldSymbol(name="distinct_id", table=events_table_alias_symbol)
                ),
                ast.Field(
                    chain=["elements_chain"],
                    symbol=ast.FieldSymbol(name="elements_chain", table=events_table_alias_symbol),
                ),
                ast.Field(
                    chain=["created_at"], symbol=ast.FieldSymbol(name="created_at", table=events_table_alias_symbol)
                ),
            ],
        )

    def test_asterisk_expander_subquery(self):
        node = parse_select("select * from (select 1 as a, 2 as b)")
        resolve_symbols(node)
        expand_asterisks(node)
        select_subquery_symbol = ast.SelectQuerySymbol(
            aliases={
                "a": ast.FieldAliasSymbol(name="a", symbol=ast.ConstantSymbol(value=1)),
                "b": ast.FieldAliasSymbol(name="b", symbol=ast.ConstantSymbol(value=2)),
            },
            columns={
                "a": ast.FieldAliasSymbol(name="a", symbol=ast.ConstantSymbol(value=1)),
                "b": ast.FieldAliasSymbol(name="b", symbol=ast.ConstantSymbol(value=2)),
            },
            tables={},
            anonymous_tables=[],
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], symbol=ast.FieldSymbol(name="a", table=select_subquery_symbol)),
                ast.Field(chain=["b"], symbol=ast.FieldSymbol(name="b", table=select_subquery_symbol)),
            ],
        )

    def test_asterisk_expander_subquery_alias(self):
        node = parse_select("select x.* from (select 1 as a, 2 as b) x")
        resolve_symbols(node)
        expand_asterisks(node)
        select_subquery_symbol = ast.SelectQueryAliasSymbol(
            name="x",
            symbol=ast.SelectQuerySymbol(
                aliases={
                    "a": ast.FieldAliasSymbol(name="a", symbol=ast.ConstantSymbol(value=1)),
                    "b": ast.FieldAliasSymbol(name="b", symbol=ast.ConstantSymbol(value=2)),
                },
                columns={
                    "a": ast.FieldAliasSymbol(name="a", symbol=ast.ConstantSymbol(value=1)),
                    "b": ast.FieldAliasSymbol(name="b", symbol=ast.ConstantSymbol(value=2)),
                },
                tables={},
                anonymous_tables=[],
            ),
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], symbol=ast.FieldSymbol(name="a", table=select_subquery_symbol)),
                ast.Field(chain=["b"], symbol=ast.FieldSymbol(name="b", table=select_subquery_symbol)),
            ],
        )

    def test_asterisk_expander_multiple_table_error(self):
        node = parse_select("select * from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a")
        with self.assertRaises(ResolverException) as e:
            resolve_symbols(node)
        self.assertEqual(
            str(e.exception), "Cannot use '*' without table name when there are multiple tables in the query"
        )
