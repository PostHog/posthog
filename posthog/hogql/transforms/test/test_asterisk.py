from posthog.hogql import ast
from posthog.hogql.database import database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_pointers
from posthog.hogql.transforms import expand_asterisks
from posthog.test.base import BaseTest


class TestAsteriskExpander(BaseTest):
    def test_asterisk_expander_table(self):
        node = parse_select("select * from events")
        resolve_pointers(node)
        expand_asterisks(node)
        events_table_pointer = ast.TablePointer(table=database.events)
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], pointer=ast.FieldPointer(name="uuid", table=events_table_pointer)),
                ast.Field(chain=["event"], pointer=ast.FieldPointer(name="event", table=events_table_pointer)),
                ast.Field(
                    chain=["properties"], pointer=ast.FieldPointer(name="properties", table=events_table_pointer)
                ),
                ast.Field(chain=["timestamp"], pointer=ast.FieldPointer(name="timestamp", table=events_table_pointer)),
                ast.Field(
                    chain=["distinct_id"], pointer=ast.FieldPointer(name="distinct_id", table=events_table_pointer)
                ),
                ast.Field(
                    chain=["elements_chain"],
                    pointer=ast.FieldPointer(name="elements_chain", table=events_table_pointer),
                ),
                ast.Field(
                    chain=["created_at"], pointer=ast.FieldPointer(name="created_at", table=events_table_pointer)
                ),
            ],
        )

    def test_asterisk_expander_table_alias(self):
        node = parse_select("select * from events e")
        resolve_pointers(node)
        expand_asterisks(node)
        events_table_pointer = ast.TablePointer(table=database.events)
        events_table_alias_pointer = ast.TableAliasPointer(table_pointer=events_table_pointer, name="e")
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], pointer=ast.FieldPointer(name="uuid", table=events_table_alias_pointer)),
                ast.Field(chain=["event"], pointer=ast.FieldPointer(name="event", table=events_table_alias_pointer)),
                ast.Field(
                    chain=["properties"], pointer=ast.FieldPointer(name="properties", table=events_table_alias_pointer)
                ),
                ast.Field(
                    chain=["timestamp"], pointer=ast.FieldPointer(name="timestamp", table=events_table_alias_pointer)
                ),
                ast.Field(
                    chain=["distinct_id"],
                    pointer=ast.FieldPointer(name="distinct_id", table=events_table_alias_pointer),
                ),
                ast.Field(
                    chain=["elements_chain"],
                    pointer=ast.FieldPointer(name="elements_chain", table=events_table_alias_pointer),
                ),
                ast.Field(
                    chain=["created_at"], pointer=ast.FieldPointer(name="created_at", table=events_table_alias_pointer)
                ),
            ],
        )

    def test_asterisk_expander_subquery(self):
        node = parse_select("select * from (select 1 as a, 2 as b)")
        resolve_pointers(node)
        expand_asterisks(node)
        select_subquery_pointer = ast.SelectQueryPointer(
            aliases={
                "a": ast.FieldAliasPointer(name="a", pointer=ast.ConstantPointer(value=1)),
                "b": ast.FieldAliasPointer(name="b", pointer=ast.ConstantPointer(value=2)),
            },
            columns={
                "a": ast.FieldAliasPointer(name="a", pointer=ast.ConstantPointer(value=1)),
                "b": ast.FieldAliasPointer(name="b", pointer=ast.ConstantPointer(value=2)),
            },
            tables={},
            anonymous_tables=[],
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], pointer=ast.FieldPointer(name="a", table=select_subquery_pointer)),
                ast.Field(chain=["b"], pointer=ast.FieldPointer(name="b", table=select_subquery_pointer)),
            ],
        )

    def test_asterisk_expander_subquery_alias(self):
        node = parse_select("select x.* from (select 1 as a, 2 as b) x")
        resolve_pointers(node)
        expand_asterisks(node)
        select_subquery_pointer = ast.SelectQueryAliasPointer(
            name="x",
            pointer=ast.SelectQueryPointer(
                aliases={
                    "a": ast.FieldAliasPointer(name="a", pointer=ast.ConstantPointer(value=1)),
                    "b": ast.FieldAliasPointer(name="b", pointer=ast.ConstantPointer(value=2)),
                },
                columns={
                    "a": ast.FieldAliasPointer(name="a", pointer=ast.ConstantPointer(value=1)),
                    "b": ast.FieldAliasPointer(name="b", pointer=ast.ConstantPointer(value=2)),
                },
                tables={},
                anonymous_tables=[],
            ),
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], pointer=ast.FieldPointer(name="a", table=select_subquery_pointer)),
                ast.Field(chain=["b"], pointer=ast.FieldPointer(name="b", table=select_subquery_pointer)),
            ],
        )

    def test_asterisk_expander_from_subquery_table(self):
        node = parse_select("select * from (select * from events)")
        resolve_pointers(node)
        expand_asterisks(node)

        events_table_pointer = ast.TablePointer(table=database.events)
        inner_select_pointer = ast.SelectQueryPointer(
            tables={"events": events_table_pointer},
            anonymous_tables=[],
            aliases={},
            columns={
                "uuid": ast.FieldPointer(name="uuid", table=events_table_pointer),
                "event": ast.FieldPointer(name="event", table=events_table_pointer),
                "properties": ast.FieldPointer(name="properties", table=events_table_pointer),
                "timestamp": ast.FieldPointer(name="timestamp", table=events_table_pointer),
                "distinct_id": ast.FieldPointer(name="distinct_id", table=events_table_pointer),
                "elements_chain": ast.FieldPointer(name="elements_chain", table=events_table_pointer),
                "created_at": ast.FieldPointer(name="created_at", table=events_table_pointer),
            },
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], pointer=ast.FieldPointer(name="uuid", table=inner_select_pointer)),
                ast.Field(chain=["event"], pointer=ast.FieldPointer(name="event", table=inner_select_pointer)),
                ast.Field(
                    chain=["properties"], pointer=ast.FieldPointer(name="properties", table=inner_select_pointer)
                ),
                ast.Field(chain=["timestamp"], pointer=ast.FieldPointer(name="timestamp", table=inner_select_pointer)),
                ast.Field(
                    chain=["distinct_id"], pointer=ast.FieldPointer(name="distinct_id", table=inner_select_pointer)
                ),
                ast.Field(
                    chain=["elements_chain"],
                    pointer=ast.FieldPointer(name="elements_chain", table=inner_select_pointer),
                ),
                ast.Field(
                    chain=["created_at"], pointer=ast.FieldPointer(name="created_at", table=inner_select_pointer)
                ),
            ],
        )

    def test_asterisk_expander_multiple_table_error(self):
        node = parse_select("select * from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a")
        with self.assertRaises(ResolverException) as e:
            resolve_pointers(node)
        self.assertEqual(
            str(e.exception), "Cannot use '*' without table name when there are multiple tables in the query"
        )
