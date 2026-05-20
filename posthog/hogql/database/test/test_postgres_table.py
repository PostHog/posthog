from typing import Literal

from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    StringDatabaseField,
    StringJSONDatabaseField,
    TableNode,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team


class TestPostgresTable(BaseTest):
    def _init_database(self, *, predicates=None, extra_fields=None):
        self.database = Database.create_for(team=self.team)

        fields = {
            "id": IntegerDatabaseField(name="id"),
            "team_id": IntegerDatabaseField(name="team_id"),
            "name": StringDatabaseField(name="name"),
        }
        if extra_fields:
            fields.update(extra_fields)

        self.database.tables.add_child(
            TableNode(
                name="postgres_table",
                table=PostgresTable(
                    name="postgres_table",
                    postgres_table_name="some_table_on_postgres",
                    **({} if predicates is None else {"predicates": predicates}),
                    fields=fields,
                ),
            )
        )

        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _init_database_for_joins(self, *, predicates=None, extra_fields=None):
        self._init_database(predicates=predicates, extra_fields=extra_fields)
        self.database.tables.add_child(
            TableNode(
                name="other_table",
                table=PostgresTable(
                    name="other_table",
                    postgres_table_name="some_other_table",
                    fields={
                        "id": IntegerDatabaseField(name="id"),
                        "team_id": IntegerDatabaseField(name="team_id"),
                        "ref_id": IntegerDatabaseField(name="ref_id"),
                    },
                ),
            )
        )

    def _select(self, query: str, dialect: Literal["hogql", "clickhouse"] = "clickhouse") -> str:
        return prepare_and_print_ast(parse_select(query), self.context, dialect=dialect)[0]

    def test_select(self):
        self._init_database()
        self.assertEqual(
            self._select("SELECT * FROM postgres_table LIMIT 10", dialect="hogql"),
            "SELECT id, team_id, name FROM postgres_table LIMIT 10",
        )
        self.assertEqual(
            self._select("SELECT * FROM postgres_table LIMIT 10"),
            f"SELECT postgres_table.id AS id, postgres_table.team_id AS team_id, postgres_table.name AS name FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS postgres_table WHERE equals(postgres_table.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_single_predicate(self):
        self._init_database(
            predicates=[parse_expr("created_at >= today() - interval 30 day")],
            extra_fields={"created_at": DateTimeDatabaseField(name="created_at")},
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table LIMIT 10", dialect="hogql"),
            "SELECT id FROM postgres_table WHERE greaterOrEquals(created_at, minus(today(), toIntervalDay(30))) LIMIT 10",
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table LIMIT 10"),
            f"SELECT postgres_table.id AS id FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS postgres_table WHERE and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))) LIMIT 10",
        )

    def test_multiple_predicates(self):
        self._init_database(
            predicates=[
                parse_expr("created_at >= today() - interval 30 day"),
                parse_expr("status != 'deleted'"),
            ],
            extra_fields={
                "created_at": DateTimeDatabaseField(name="created_at"),
                "status": StringDatabaseField(name="status"),
            },
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table LIMIT 10", dialect="hogql"),
            "SELECT id FROM postgres_table WHERE and(greaterOrEquals(created_at, minus(today(), toIntervalDay(30))), notEquals(status, 'deleted')) LIMIT 10",
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table LIMIT 10"),
            f"SELECT postgres_table.id AS id FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS postgres_table WHERE and(and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))), notEquals(postgres_table.status, %(hogql_val_5)s)) LIMIT 10",
        )

    def test_predicate_combined_with_user_where(self):
        self._init_database(
            predicates=[parse_expr("created_at >= today() - interval 30 day")],
            extra_fields={"created_at": DateTimeDatabaseField(name="created_at")},
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table where name = 'test' LIMIT 10", dialect="hogql"),
            "SELECT id FROM postgres_table WHERE and(greaterOrEquals(created_at, minus(today(), toIntervalDay(30))), equals(name, 'test')) LIMIT 10",
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table where name = 'test' LIMIT 10"),
            f"SELECT postgres_table.id AS id FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS postgres_table WHERE and(and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))), equals(postgres_table.name, %(hogql_val_5)s)) LIMIT 10",
        )

    def test_left_join_single_predicate(self):
        self._init_database_for_joins(
            predicates=[parse_expr("created_at >= today() - interval 30 day")],
            extra_fields={"created_at": DateTimeDatabaseField(name="created_at")},
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id, postgres_table.name "
                "FROM other_table "
                "LEFT JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "LIMIT 10",
                dialect="hogql",
            ),
            "SELECT other_table.id, postgres_table.name FROM other_table LEFT JOIN postgres_table ON and(greaterOrEquals(created_at, minus(today(), toIntervalDay(30))), equals(other_table.ref_id, postgres_table.id)) LIMIT 10",
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id, postgres_table.name "
                "FROM other_table "
                "LEFT JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "LIMIT 10",
            ),
            f"SELECT other_table.id AS id, postgres_table.name AS name FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS other_table LEFT JOIN postgresql(%(hogql_val_6_sensitive)s, %(hogql_val_7_sensitive)s, %(hogql_val_5_sensitive)s, %(hogql_val_8_sensitive)s, %(hogql_val_9_sensitive)s) AS postgres_table ON and(and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))), equals(other_table.ref_id, postgres_table.id)) WHERE equals(other_table.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_left_join_multiple_predicates(self):
        self._init_database_for_joins(
            predicates=[
                parse_expr("created_at >= today() - interval 30 day"),
                parse_expr("status != 'deleted'"),
            ],
            extra_fields={
                "created_at": DateTimeDatabaseField(name="created_at"),
                "status": StringDatabaseField(name="status"),
            },
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id "
                "FROM other_table "
                "LEFT JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "LIMIT 10",
                dialect="hogql",
            ),
            "SELECT other_table.id FROM other_table LEFT JOIN postgres_table ON and(and(greaterOrEquals(created_at, minus(today(), toIntervalDay(30))), notEquals(status, 'deleted')), equals(other_table.ref_id, postgres_table.id)) LIMIT 10",
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id "
                "FROM other_table "
                "LEFT JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "LIMIT 10",
            ),
            f"SELECT other_table.id AS id FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS other_table LEFT JOIN postgresql(%(hogql_val_6_sensitive)s, %(hogql_val_7_sensitive)s, %(hogql_val_5_sensitive)s, %(hogql_val_8_sensitive)s, %(hogql_val_9_sensitive)s) AS postgres_table ON and(and(and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))), notEquals(postgres_table.status, %(hogql_val_10)s)), equals(other_table.ref_id, postgres_table.id)) WHERE equals(other_table.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_inner_join_predicate(self):
        self._init_database_for_joins(
            predicates=[parse_expr("created_at >= today() - interval 30 day")],
            extra_fields={"created_at": DateTimeDatabaseField(name="created_at")},
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id, postgres_table.name "
                "FROM other_table "
                "INNER JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "LIMIT 10",
                dialect="hogql",
            ),
            "SELECT other_table.id, postgres_table.name FROM other_table INNER JOIN postgres_table ON equals(other_table.ref_id, postgres_table.id) WHERE greaterOrEquals(created_at, minus(today(), toIntervalDay(30))) LIMIT 10",
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id, postgres_table.name "
                "FROM other_table "
                "INNER JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "LIMIT 10",
            ),
            f"SELECT other_table.id AS id, postgres_table.name AS name FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS other_table INNER JOIN postgresql(%(hogql_val_6_sensitive)s, %(hogql_val_7_sensitive)s, %(hogql_val_5_sensitive)s, %(hogql_val_8_sensitive)s, %(hogql_val_9_sensitive)s) AS postgres_table ON equals(other_table.ref_id, postgres_table.id) WHERE and(and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))), equals(other_table.team_id, {self.team.pk})) LIMIT 10",
        )

    def test_left_join_predicate_with_user_where(self):
        self._init_database_for_joins(
            predicates=[parse_expr("created_at >= today() - interval 30 day")],
            extra_fields={"created_at": DateTimeDatabaseField(name="created_at")},
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id, postgres_table.name "
                "FROM other_table "
                "LEFT JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "WHERE other_table.ref_id > 100 "
                "LIMIT 10",
                dialect="hogql",
            ),
            "SELECT other_table.id, postgres_table.name FROM other_table LEFT JOIN postgres_table ON and(greaterOrEquals(created_at, minus(today(), toIntervalDay(30))), equals(other_table.ref_id, postgres_table.id)) WHERE greater(other_table.ref_id, 100) LIMIT 10",
        )
        self.assertEqual(
            self._select(
                "SELECT other_table.id, postgres_table.name "
                "FROM other_table "
                "LEFT JOIN postgres_table ON other_table.ref_id = postgres_table.id "
                "WHERE other_table.ref_id > 100 "
                "LIMIT 10",
            ),
            f"SELECT other_table.id AS id, postgres_table.name AS name FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS other_table LEFT JOIN postgresql(%(hogql_val_6_sensitive)s, %(hogql_val_7_sensitive)s, %(hogql_val_5_sensitive)s, %(hogql_val_8_sensitive)s, %(hogql_val_9_sensitive)s) AS postgres_table ON and(and(equals(postgres_table.team_id, {self.team.pk}), greaterOrEquals(postgres_table.created_at, minus(today(), toIntervalDay(30)))), equals(other_table.ref_id, postgres_table.id)) WHERE and(equals(other_table.team_id, {self.team.pk}), greater(other_table.ref_id, 100)) LIMIT 10",
        )

    def test_lazy_join_with_predicate(self):
        from posthog.hogql import ast

        def join_fn(join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery):
            table = join_to_add.lazy_join.join_table
            table_name = table if isinstance(table, str) else table.name
            assert table_name is not None
            join_expr = ast.JoinExpr(table=ast.Field(chain=[table_name]))
            join_expr.join_type = "LEFT JOIN"
            join_expr.alias = join_to_add.to_table
            join_expr.constraint = ast.JoinConstraint(
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[join_to_add.from_table, "ref_id"]),
                    right=ast.Field(chain=[join_to_add.to_table, "id"]),
                ),
                constraint_type="ON",
            )
            return join_expr

        self.database = Database.create_for(team=self.team)

        pg_table = PostgresTable(
            name="postgres_table",
            postgres_table_name="some_table_on_postgres",
            predicates=[parse_expr("created_at >= today() - interval 30 day")],
            fields={
                "id": IntegerDatabaseField(name="id"),
                "team_id": IntegerDatabaseField(name="team_id"),
                "name": StringDatabaseField(name="name"),
                "created_at": DateTimeDatabaseField(name="created_at"),
            },
        )

        self.database.tables.add_child(TableNode(name="postgres_table", table=pg_table))
        self.database.tables.add_child(
            TableNode(
                name="other_table",
                table=PostgresTable(
                    name="other_table",
                    postgres_table_name="some_other_table",
                    fields={
                        "id": IntegerDatabaseField(name="id"),
                        "team_id": IntegerDatabaseField(name="team_id"),
                        "ref_id": IntegerDatabaseField(name="ref_id"),
                        "details": LazyJoin(
                            from_field=["ref_id"],
                            join_table=pg_table,
                            join_function=join_fn,
                        ),
                    },
                ),
            )
        )

        self.context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=self.database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        self.assertEqual(
            self._select("SELECT details.name FROM other_table LIMIT 10", dialect="hogql"),
            "SELECT details.name FROM other_table LIMIT 10",
        )
        self.assertEqual(
            self._select("SELECT details.name FROM other_table LIMIT 10"),
            f"SELECT other_table__details.name AS name FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS other_table LEFT JOIN postgresql(%(hogql_val_6_sensitive)s, %(hogql_val_7_sensitive)s, %(hogql_val_5_sensitive)s, %(hogql_val_8_sensitive)s, %(hogql_val_9_sensitive)s) AS other_table__details ON and(and(equals(other_table__details.team_id, {self.team.pk}), greaterOrEquals(other_table__details.created_at, minus(today(), toIntervalDay(30)))), equals(other_table.ref_id, other_table__details.id)) WHERE equals(other_table.team_id, {self.team.pk}) LIMIT 10",
        )

    def test_predicate_with_nested_property_access(self):
        self._init_database(
            predicates=[parse_expr("properties.email != ''")],
            extra_fields={"properties": StringJSONDatabaseField(name="properties")},
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table LIMIT 10", dialect="hogql"),
            "SELECT id FROM postgres_table WHERE notEquals(properties.email, '') LIMIT 10",
        )
        self.assertEqual(
            self._select("SELECT id FROM postgres_table LIMIT 10"),
            f"SELECT postgres_table.id AS id FROM postgresql(%(hogql_val_1_sensitive)s, %(hogql_val_2_sensitive)s, %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s) AS postgres_table WHERE and(equals(postgres_table.team_id, {self.team.pk}), ifNull(notEquals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(postgres_table.properties, %(hogql_val_15)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_16)s), 1)) LIMIT 10",
        )
