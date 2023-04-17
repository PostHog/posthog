from posthog.hogql import ast
from posthog.hogql.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_types
from posthog.hogql.transforms import expand_asterisks
from posthog.test.base import BaseTest


class TestAsteriskExpander(BaseTest):
    def setUp(self):
        self.database = create_hogql_database(self.team.pk)

    def test_asterisk_expander_table(self):
        node = parse_select("select * from events")
        resolve_types(node, self.database)
        expand_asterisks(node)
        events_table_type = ast.TableType(table=self.database.events)
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table=events_table_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table=events_table_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table=events_table_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table=events_table_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table=events_table_type)),
                ast.Field(chain=["elements_chain"], type=ast.FieldType(name="elements_chain", table=events_table_type)),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table=events_table_type)),
            ],
        )

    def test_asterisk_expander_table_alias(self):
        node = parse_select("select * from events e")
        resolve_types(node, self.database)
        expand_asterisks(node)
        events_table_type = ast.TableType(table=self.database.events)
        events_table_alias_type = ast.TableAliasType(table_type=events_table_type, name="e")
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table=events_table_alias_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table=events_table_alias_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table=events_table_alias_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table=events_table_alias_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table=events_table_alias_type)),
                ast.Field(
                    chain=["elements_chain"],
                    type=ast.FieldType(name="elements_chain", table=events_table_alias_type),
                ),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table=events_table_alias_type)),
            ],
        )

    def test_asterisk_expander_subquery(self):
        node = parse_select("select * from (select 1 as a, 2 as b)")
        resolve_types(node, self.database)
        expand_asterisks(node)
        select_subquery_type = ast.SelectQueryType(
            aliases={
                "a": ast.FieldAliasType(name="a", type=ast.ConstantType(data_type="int")),
                "b": ast.FieldAliasType(name="b", type=ast.ConstantType(data_type="int")),
            },
            columns={
                "a": ast.FieldAliasType(name="a", type=ast.ConstantType(data_type="int")),
                "b": ast.FieldAliasType(name="b", type=ast.ConstantType(data_type="int")),
            },
            tables={},
            anonymous_tables=[],
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], type=ast.FieldType(name="a", table=select_subquery_type)),
                ast.Field(chain=["b"], type=ast.FieldType(name="b", table=select_subquery_type)),
            ],
        )

    def test_asterisk_expander_subquery_alias(self):
        node = parse_select("select x.* from (select 1 as a, 2 as b) x")
        resolve_types(node, self.database)
        expand_asterisks(node)
        select_subquery_type = ast.SelectQueryAliasType(
            name="x",
            type=ast.SelectQueryType(
                aliases={
                    "a": ast.FieldAliasType(name="a", type=ast.ConstantType(data_type="int")),
                    "b": ast.FieldAliasType(name="b", type=ast.ConstantType(data_type="int")),
                },
                columns={
                    "a": ast.FieldAliasType(name="a", type=ast.ConstantType(data_type="int")),
                    "b": ast.FieldAliasType(name="b", type=ast.ConstantType(data_type="int")),
                },
                tables={},
                anonymous_tables=[],
            ),
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], type=ast.FieldType(name="a", table=select_subquery_type)),
                ast.Field(chain=["b"], type=ast.FieldType(name="b", table=select_subquery_type)),
            ],
        )

    def test_asterisk_expander_from_subquery_table(self):
        node = parse_select("select * from (select * from events)")
        resolve_types(node, self.database)
        expand_asterisks(node)

        events_table_type = ast.TableType(table=self.database.events)
        inner_select_type = ast.SelectQueryType(
            tables={"events": events_table_type},
            anonymous_tables=[],
            aliases={},
            columns={
                "uuid": ast.FieldType(name="uuid", table=events_table_type),
                "event": ast.FieldType(name="event", table=events_table_type),
                "properties": ast.FieldType(name="properties", table=events_table_type),
                "timestamp": ast.FieldType(name="timestamp", table=events_table_type),
                "distinct_id": ast.FieldType(name="distinct_id", table=events_table_type),
                "elements_chain": ast.FieldType(name="elements_chain", table=events_table_type),
                "created_at": ast.FieldType(name="created_at", table=events_table_type),
            },
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table=inner_select_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table=inner_select_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table=inner_select_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table=inner_select_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table=inner_select_type)),
                ast.Field(
                    chain=["elements_chain"],
                    type=ast.FieldType(name="elements_chain", table=inner_select_type),
                ),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table=inner_select_type)),
            ],
        )

    def test_asterisk_expander_multiple_table_error(self):
        node = parse_select("select * from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a")
        with self.assertRaises(ResolverException) as e:
            resolve_types(node, self.database)
        self.assertEqual(
            str(e.exception), "Cannot use '*' without table name when there are multiple tables in the query"
        )

    def test_asterisk_expander_select_union(self):
        node = parse_select("select * from (select * from events union all select * from events)")
        resolve_types(node, self.database)
        expand_asterisks(node)

        events_table_type = ast.TableType(table=self.database.events)
        inner_select_type = ast.SelectUnionQueryType(
            types=[
                ast.SelectQueryType(
                    tables={"events": events_table_type},
                    anonymous_tables=[],
                    aliases={},
                    columns={
                        "uuid": ast.FieldType(name="uuid", table=events_table_type),
                        "event": ast.FieldType(name="event", table=events_table_type),
                        "properties": ast.FieldType(name="properties", table=events_table_type),
                        "timestamp": ast.FieldType(name="timestamp", table=events_table_type),
                        "distinct_id": ast.FieldType(name="distinct_id", table=events_table_type),
                        "elements_chain": ast.FieldType(name="elements_chain", table=events_table_type),
                        "created_at": ast.FieldType(name="created_at", table=events_table_type),
                    },
                )
            ]
            * 2
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table=inner_select_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table=inner_select_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table=inner_select_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table=inner_select_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table=inner_select_type)),
                ast.Field(
                    chain=["elements_chain"],
                    type=ast.FieldType(name="elements_chain", table=inner_select_type),
                ),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table=inner_select_type)),
            ],
        )
