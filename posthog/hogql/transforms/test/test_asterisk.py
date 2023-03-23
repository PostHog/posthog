from posthog.hogql import ast
from posthog.hogql.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_refs
from posthog.hogql.transforms import expand_asterisks
from posthog.test.base import BaseTest


class TestAsteriskExpander(BaseTest):
    def setUp(self):
        self.database = create_hogql_database(self.team.pk)

    def test_asterisk_expander_table(self):
        node = parse_select("select * from events")
        resolve_refs(node, self.database)
        expand_asterisks(node)
        events_table_ref = ast.TableRef(table=self.database.events)
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], ref=ast.FieldRef(name="uuid", table=events_table_ref)),
                ast.Field(chain=["event"], ref=ast.FieldRef(name="event", table=events_table_ref)),
                ast.Field(chain=["properties"], ref=ast.FieldRef(name="properties", table=events_table_ref)),
                ast.Field(chain=["timestamp"], ref=ast.FieldRef(name="timestamp", table=events_table_ref)),
                ast.Field(chain=["distinct_id"], ref=ast.FieldRef(name="distinct_id", table=events_table_ref)),
                ast.Field(chain=["elements_chain"], ref=ast.FieldRef(name="elements_chain", table=events_table_ref)),
                ast.Field(chain=["created_at"], ref=ast.FieldRef(name="created_at", table=events_table_ref)),
            ],
        )

    def test_asterisk_expander_table_alias(self):
        node = parse_select("select * from events e")
        resolve_refs(node, self.database)
        expand_asterisks(node)
        events_table_ref = ast.TableRef(table=self.database.events)
        events_table_alias_ref = ast.TableAliasRef(table_ref=events_table_ref, name="e")
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], ref=ast.FieldRef(name="uuid", table=events_table_alias_ref)),
                ast.Field(chain=["event"], ref=ast.FieldRef(name="event", table=events_table_alias_ref)),
                ast.Field(chain=["properties"], ref=ast.FieldRef(name="properties", table=events_table_alias_ref)),
                ast.Field(chain=["timestamp"], ref=ast.FieldRef(name="timestamp", table=events_table_alias_ref)),
                ast.Field(chain=["distinct_id"], ref=ast.FieldRef(name="distinct_id", table=events_table_alias_ref)),
                ast.Field(
                    chain=["elements_chain"],
                    ref=ast.FieldRef(name="elements_chain", table=events_table_alias_ref),
                ),
                ast.Field(chain=["created_at"], ref=ast.FieldRef(name="created_at", table=events_table_alias_ref)),
            ],
        )

    def test_asterisk_expander_subquery(self):
        node = parse_select("select * from (select 1 as a, 2 as b)")
        resolve_refs(node, self.database)
        expand_asterisks(node)
        select_subquery_ref = ast.SelectQueryRef(
            aliases={
                "a": ast.FieldAliasRef(name="a", ref=ast.ConstantRef(value=1)),
                "b": ast.FieldAliasRef(name="b", ref=ast.ConstantRef(value=2)),
            },
            columns={
                "a": ast.FieldAliasRef(name="a", ref=ast.ConstantRef(value=1)),
                "b": ast.FieldAliasRef(name="b", ref=ast.ConstantRef(value=2)),
            },
            tables={},
            anonymous_tables=[],
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], ref=ast.FieldRef(name="a", table=select_subquery_ref)),
                ast.Field(chain=["b"], ref=ast.FieldRef(name="b", table=select_subquery_ref)),
            ],
        )

    def test_asterisk_expander_subquery_alias(self):
        node = parse_select("select x.* from (select 1 as a, 2 as b) x")
        resolve_refs(node, self.database)
        expand_asterisks(node)
        select_subquery_ref = ast.SelectQueryAliasRef(
            name="x",
            ref=ast.SelectQueryRef(
                aliases={
                    "a": ast.FieldAliasRef(name="a", ref=ast.ConstantRef(value=1)),
                    "b": ast.FieldAliasRef(name="b", ref=ast.ConstantRef(value=2)),
                },
                columns={
                    "a": ast.FieldAliasRef(name="a", ref=ast.ConstantRef(value=1)),
                    "b": ast.FieldAliasRef(name="b", ref=ast.ConstantRef(value=2)),
                },
                tables={},
                anonymous_tables=[],
            ),
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], ref=ast.FieldRef(name="a", table=select_subquery_ref)),
                ast.Field(chain=["b"], ref=ast.FieldRef(name="b", table=select_subquery_ref)),
            ],
        )

    def test_asterisk_expander_from_subquery_table(self):
        node = parse_select("select * from (select * from events)")
        resolve_refs(node, self.database)
        expand_asterisks(node)

        events_table_ref = ast.TableRef(table=self.database.events)
        inner_select_ref = ast.SelectQueryRef(
            tables={"events": events_table_ref},
            anonymous_tables=[],
            aliases={},
            columns={
                "uuid": ast.FieldRef(name="uuid", table=events_table_ref),
                "event": ast.FieldRef(name="event", table=events_table_ref),
                "properties": ast.FieldRef(name="properties", table=events_table_ref),
                "timestamp": ast.FieldRef(name="timestamp", table=events_table_ref),
                "distinct_id": ast.FieldRef(name="distinct_id", table=events_table_ref),
                "elements_chain": ast.FieldRef(name="elements_chain", table=events_table_ref),
                "created_at": ast.FieldRef(name="created_at", table=events_table_ref),
            },
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], ref=ast.FieldRef(name="uuid", table=inner_select_ref)),
                ast.Field(chain=["event"], ref=ast.FieldRef(name="event", table=inner_select_ref)),
                ast.Field(chain=["properties"], ref=ast.FieldRef(name="properties", table=inner_select_ref)),
                ast.Field(chain=["timestamp"], ref=ast.FieldRef(name="timestamp", table=inner_select_ref)),
                ast.Field(chain=["distinct_id"], ref=ast.FieldRef(name="distinct_id", table=inner_select_ref)),
                ast.Field(
                    chain=["elements_chain"],
                    ref=ast.FieldRef(name="elements_chain", table=inner_select_ref),
                ),
                ast.Field(chain=["created_at"], ref=ast.FieldRef(name="created_at", table=inner_select_ref)),
            ],
        )

    def test_asterisk_expander_multiple_table_error(self):
        node = parse_select("select * from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a")
        with self.assertRaises(ResolverException) as e:
            resolve_refs(node, self.database)
        self.assertEqual(
            str(e.exception), "Cannot use '*' without table name when there are multiple tables in the query"
        )

    def test_asterisk_expander_select_union(self):
        node = parse_select("select * from (select * from events union all select * from events)")
        resolve_refs(node, self.database)
        expand_asterisks(node)

        events_table_ref = ast.TableRef(table=self.database.events)
        inner_select_ref = ast.SelectUnionQueryRef(
            refs=[
                ast.SelectQueryRef(
                    tables={"events": events_table_ref},
                    anonymous_tables=[],
                    aliases={},
                    columns={
                        "uuid": ast.FieldRef(name="uuid", table=events_table_ref),
                        "event": ast.FieldRef(name="event", table=events_table_ref),
                        "properties": ast.FieldRef(name="properties", table=events_table_ref),
                        "timestamp": ast.FieldRef(name="timestamp", table=events_table_ref),
                        "distinct_id": ast.FieldRef(name="distinct_id", table=events_table_ref),
                        "elements_chain": ast.FieldRef(name="elements_chain", table=events_table_ref),
                        "created_at": ast.FieldRef(name="created_at", table=events_table_ref),
                    },
                )
            ]
            * 2
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], ref=ast.FieldRef(name="uuid", table=inner_select_ref)),
                ast.Field(chain=["event"], ref=ast.FieldRef(name="event", table=inner_select_ref)),
                ast.Field(chain=["properties"], ref=ast.FieldRef(name="properties", table=inner_select_ref)),
                ast.Field(chain=["timestamp"], ref=ast.FieldRef(name="timestamp", table=inner_select_ref)),
                ast.Field(chain=["distinct_id"], ref=ast.FieldRef(name="distinct_id", table=inner_select_ref)),
                ast.Field(
                    chain=["elements_chain"],
                    ref=ast.FieldRef(name="elements_chain", table=inner_select_ref),
                ),
                ast.Field(chain=["created_at"], ref=ast.FieldRef(name="created_at", table=inner_select_ref)),
            ],
        )
