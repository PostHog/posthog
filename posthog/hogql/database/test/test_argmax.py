import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.utils.timezone import now

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select, pushdown_predicates_to_argmax_subquery
from posthog.hogql.database.schema.groups import GROUPS_PUSHDOWN_FIELDS, GroupsTable
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.group.util import create_group, raw_create_group_ch


class TestArgmax(BaseTest):
    def test_argmax_select(self):
        response = argmax_select(
            table_name="raw_persons",
            select_fields={"moo": ["properties", "moo"], "id": ["id"]},
            group_fields=["id"],
            argmax_field="version",
        )
        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="moo",
                    expr=ast.Call(
                        name="tupleElement",
                        args=[
                            ast.Call(
                                name="argMax",
                                args=[
                                    ast.Call(
                                        name="tuple",
                                        args=[
                                            ast.Field(chain=["raw_persons", "properties", "moo"]),
                                        ],
                                    ),
                                    ast.Field(chain=["raw_persons", "version"]),
                                ],
                            ),
                            ast.Constant(value=1),
                        ],
                    ),
                ),
                ast.Alias(alias="id", expr=ast.Field(chain=["raw_persons", "id"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),
            group_by=[ast.Field(chain=["raw_persons", "id"])],
        )
        self.assertEqual(response, expected)

    def test_argmax_select_deleted(self):
        response = argmax_select(
            table_name="raw_persons",
            select_fields={"moo": ["properties", "moo"], "id": ["id"]},
            group_fields=["id"],
            argmax_field="version",
            deleted_field="is_deleted",
        )
        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="moo",
                    expr=ast.Call(
                        name="tupleElement",
                        args=[
                            ast.Call(
                                name="argMax",
                                args=[
                                    ast.Call(
                                        name="tuple", args=[ast.Field(chain=["raw_persons", "properties", "moo"])]
                                    ),
                                    ast.Field(chain=["raw_persons", "version"]),
                                ],
                            ),
                            ast.Constant(value=1),
                        ],
                    ),
                ),
                ast.Alias(alias="id", expr=ast.Field(chain=["raw_persons", "id"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["raw_persons"])),
            group_by=[ast.Field(chain=["raw_persons", "id"])],
            having=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Call(
                    name="tupleElement",
                    args=[
                        ast.Call(
                            name="argMax",
                            args=[
                                ast.Call(
                                    name="tuple",
                                    args=[
                                        ast.Field(chain=["raw_persons", "is_deleted"]),
                                    ],
                                ),
                                ast.Field(chain=["raw_persons", "version"]),
                            ],
                        ),
                        ast.Constant(value=1),
                    ],
                ),
                right=ast.Constant(value=0),
            ),
        )
        self.assertEqual(response, expected)


class TestPushdownPredicatesToArgmaxSubquery(BaseTest):
    """Direct unit tests of the helper that runs against an already-built subquery."""

    def _build_subquery(self) -> ast.SelectQuery:
        return argmax_select(
            table_name="raw_groups",
            select_fields={"properties": ["properties"], "index": ["index"], "key": ["key"]},
            group_fields=["index", "key"],
            argmax_field="updated_at",
        )

    def test_no_outer_where_is_noop(self):
        subquery = self._build_subquery()
        pushdown_predicates_to_argmax_subquery(
            subquery=subquery,
            outer_where=None,
            lazy_table=GroupsTable(),
            pushdown_field_names=set(GROUPS_PUSHDOWN_FIELDS),
        )
        self.assertIsNone(subquery.where)

    def test_empty_pushdown_fields_is_noop(self):
        subquery = self._build_subquery()
        outer = ast.CompareOperation(
            left=ast.Field(chain=["index"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=0)
        )
        pushdown_predicates_to_argmax_subquery(
            subquery=subquery,
            outer_where=outer,
            lazy_table=GroupsTable(),
            pushdown_field_names=set(),
        )
        self.assertIsNone(subquery.where)


class TestGroupsPushdownSQL(BaseTest):
    """End-to-end tests that print SQL and assert the WHERE clause lands inside the
    argmax subquery for `FROM groups WHERE <index/key filter>` queries."""

    def _print(self, hogql: str) -> str:
        return prepare_and_print_ast(
            parse_select(hogql),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )[0]

    def test_index_filter_pushed_into_argmax_subquery(self):
        sql = self._print("SELECT key FROM groups WHERE index = 0")
        # Inner subquery's WHERE picks up `index = 0` next to the team_id guard.
        self.assertIn("FROM groups WHERE and(equals(groups.team_id,", sql)
        self.assertIn("equals(index, 0)) GROUP BY", sql)

    def test_key_filter_pushed_into_argmax_subquery(self):
        sql = self._print("SELECT key FROM groups WHERE key = 'abc'")
        self.assertIn("equals(key, %(hogql_val_0)s)) GROUP BY", sql)

    def test_compound_index_and_key_filter_pushed(self):
        sql = self._print("SELECT key FROM groups WHERE index = 0 AND key = 'abc'")
        self.assertIn("equals(index, 0)", sql.split("GROUP BY")[0])
        self.assertIn("equals(key, %(hogql_val_0)s)", sql.split("GROUP BY")[0])

    def test_non_group_by_field_is_not_pushed(self):
        # `properties` reaches through argMax(); pre-aggregation filtering on it would
        # change which row argMax picks, so it must stay above the subquery.
        sql = self._print("SELECT key FROM groups WHERE properties = '{}'")
        before_group_by, after_group_by = sql.split("GROUP BY", 1)
        self.assertNotIn("properties", before_group_by[before_group_by.index("FROM groups") :])
        self.assertIn("properties", after_group_by)

    def test_mixed_filter_only_pushes_safe_conjuncts(self):
        sql = self._print("SELECT key FROM groups WHERE index = 0 AND properties = '{}'")
        before_group_by, after_group_by = sql.split("GROUP BY", 1)
        self.assertIn("equals(index, 0)", before_group_by)
        # `properties` stays in the outer WHERE only.
        self.assertNotIn("properties", before_group_by[before_group_by.index("FROM groups WHERE") :])
        self.assertIn("properties", after_group_by)

    def test_no_where_clause_still_works(self):
        # Regression: a query without any WHERE shouldn't blow up or add a stray WHERE.
        sql = self._print("SELECT key FROM groups LIMIT 1")
        # Inner subquery still gets the team_id guard but nothing more.
        self.assertIn("FROM groups WHERE equals(groups.team_id,", sql)
        # No `AND` next to the team_id guard inside the subquery.
        # (a second AND would mean we incorrectly pushed something.)
        before_group_by = sql.split("GROUP BY", 1)[0]
        self.assertNotIn("AND", before_group_by.upper().replace("AND(", ""))

    def test_in_filter_on_index_pushed(self):
        sql = self._print("SELECT key FROM groups WHERE index IN (0, 1)")
        before_group_by = sql.split("GROUP BY", 1)[0]
        # The IN list lives inside the subquery WHERE alongside the team_id guard.
        self.assertIn("in(index,", before_group_by)

    def test_aliased_table_still_pushes(self):
        sql = self._print("SELECT g.key FROM groups AS g WHERE g.index = 0")
        before_group_by = sql.split("GROUP BY", 1)[0]
        self.assertIn("equals(index, 0)", before_group_by)


class TestGroupsPushdownExecution(ClickhouseTestMixin, BaseTest):
    """Run real ClickHouse queries to confirm the pushdown produces the same rows
    as the old behavior. The cheapest correctness guarantee for an optimization
    that rewrites the AST."""

    def setUp(self) -> None:
        super().setUp()
        earlier = now() - datetime.timedelta(minutes=5)
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org_a",
            properties={"name": "Org A"},
            timestamp=earlier,
        )
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org_b", properties={"name": "Org B"})
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key="account_c",
            properties={"name": "Account C"},
        )
        # Second ClickHouse-only version of org_a with a later _timestamp so argMax has to pick it.
        raw_create_group_ch(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org_a",
            properties={"name": "Org A Updated"},
            created_at=earlier,
            timestamp=now(),
        )

    def test_index_filter_returns_only_matching_index(self):
        result = execute_hogql_query(
            team=self.team,
            query="SELECT key FROM groups WHERE index = 0 ORDER BY key",
        )
        keys = [row[0] for row in result.results]
        self.assertEqual(keys, ["org_a", "org_b"])

    def test_index_and_key_filter_returns_single_row(self):
        result = execute_hogql_query(
            team=self.team,
            query="SELECT JSONExtractString(properties, 'name') FROM groups WHERE index = 0 AND key = 'org_a'",
        )
        names = [row[0] for row in result.results]
        # argMax must still resolve to the latest version of org_a.
        self.assertEqual(names, ["Org A Updated"])

    def test_filter_on_index_one_returns_only_account(self):
        result = execute_hogql_query(
            team=self.team,
            query="SELECT key FROM groups WHERE index = 1",
        )
        keys = [row[0] for row in result.results]
        self.assertEqual(keys, ["account_c"])

    def test_no_filter_returns_all_groups(self):
        result = execute_hogql_query(
            team=self.team,
            query="SELECT key FROM groups ORDER BY key",
        )
        keys = [row[0] for row in result.results]
        self.assertEqual(keys, ["account_c", "org_a", "org_b"])
