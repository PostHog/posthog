from functools import lru_cache
from typing import Literal

from posthog.test.base import BaseTest

from django.apps import apps
from django.db.models import ForeignKey, Model
from django.test import SimpleTestCase
from django.urls import get_resolver

from parameterized import parameterized

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
from posthog.hogql.database.schema.system import SystemTables
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

from ee.api.rbac.access_control import AccessControlViewSetMixin


@lru_cache(maxsize=1)
def _object_grant_registry() -> dict[type[Model], str]:
    """Map every model that is object-restrictable to the resource (`scope_object`) its
    per-object grants are stored under. Derived from `AccessControlViewSetMixin` viewsets —
    the authoritative source of which resources can hold object-level grants. Loading the
    full URLconf forces all viewsets (including product ones) to be imported first."""
    _ = get_resolver().url_patterns

    def all_subclasses(cls: type) -> set[type]:
        subs: set[type] = set()
        for sub in cls.__subclasses__():
            subs.add(sub)
            subs |= all_subclasses(sub)
        return subs

    registry: dict[type[Model], str] = {}
    for viewset in all_subclasses(AccessControlViewSetMixin):
        scope = getattr(viewset, "scope_object", None)
        if not isinstance(scope, str) or scope == "INTERNAL":
            continue
        queryset = getattr(viewset, "queryset", None)
        model = queryset.model if queryset is not None else None
        if model is None:
            meta = getattr(getattr(viewset, "serializer_class", None), "Meta", None)
            model = getattr(meta, "model", None)
        if model is not None:
            registry[model] = scope
    return registry


@lru_cache(maxsize=1)
def _model_by_pg_table() -> dict[str, type[Model]]:
    # Skip proxy models — they share their base's db_table and would shadow the concrete model.
    mapping: dict[str, type[Model]] = {}
    for model in apps.get_models():
        if model._meta.proxy:
            continue
        mapping.setdefault(model._meta.db_table, model)
    return mapping


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


ALL_POSTGRES_SYSTEM_TABLES = [
    (name, node.table) for name, node in SystemTables().children.items() if isinstance(node.table, PostgresTable)
]


class TestPostgresTablePrimaryKey(BaseTest):
    """Validate primary_key auto-detection and access_scope constraints."""

    @parameterized.expand(ALL_POSTGRES_SYSTEM_TABLES)
    def test_tables_with_access_scope_have_single_column_pk(self, table_name, table):
        """Object-level access control requires a single-column PK to filter by."""
        if table.access_scope is None:
            return
        assert table.primary_key is not None, (
            f"system.{table_name} has access_scope='{table.access_scope}' "
            f"but no single-column primary key (composite PK). "
            f"Object-level access control requires a single-column PK."
        )


class TestObjectAccessControlIdField(SimpleTestCase):
    """Every scoped system table must filter object-level denials against the correct column.

    A table whose rows ARE the access-controlled object filters its primary key (the default).
    A child table that only exposes a parent object's data must set `access_control_id_field`
    to the foreign key pointing at that parent — otherwise a member denied the parent could
    still read the child rows through HogQL. The set of object-restrictable resources is
    derived from `AccessControlViewSetMixin` viewsets, so new restrictable models or child
    tables fail this test until their `access_control_id_field` is declared correctly."""

    @parameterized.expand(ALL_POSTGRES_SYSTEM_TABLES)
    def test_access_control_id_field_targets_the_restricted_object(self, table_name, table) -> None:
        if table.access_scope is None:
            self.assertIsNone(
                table.access_control_id_field,
                f"system.{table_name} has no access_scope, so access_control_id_field is meaningless — remove it.",
            )
            return

        model = _model_by_pg_table().get(table.postgres_table_name)
        self.assertIsNotNone(model, f"could not resolve a Django model for system.{table_name}")

        scope = table.access_scope
        registry = _object_grant_registry()
        # Models whose per-object grants are stored under this table's scope.
        target_models = {m for m, s in registry.items() if s == scope}

        # This table's rows ARE the access-controlled object → filter the primary key (default).
        if model in target_models:
            self.assertIsNone(
                table.access_control_id_field,
                f"system.{table_name} is itself access-controlled under '{scope}'; it must filter its "
                f"primary key — leave access_control_id_field unset.",
            )
            return

        # The scope has no object-restrictable models → no per-object grants ever exist → the
        # guard short-circuits on an empty deny set. No id override is meaningful.
        if not target_models:
            self.assertIsNone(
                table.access_control_id_field,
                f"system.{table_name} scope '{scope}' has no object-level grants; remove access_control_id_field.",
            )
            return

        # Child table: it must filter the FK pointing at one of the restricted parent models.
        fk_columns = sorted(
            field.attname
            for field in model._meta.get_fields()  # type: ignore[union-attr]
            if isinstance(field, ForeignKey) and field.related_model in target_models
        )
        self.assertTrue(
            fk_columns,
            f"system.{table_name} is scoped to the object-restrictable resource '{scope}' but is neither "
            f"one of its objects ({sorted(m.__name__ for m in target_models)}) nor has a foreign key to one. "
            f"It may leak access-controlled rows — add the right FK or reconsider its access_scope.",
        )
        self.assertIn(
            table.access_control_id_field,
            fk_columns,
            f"system.{table_name} is a child of '{scope}'; set access_control_id_field to the FK pointing at "
            f"its parent (one of {fk_columns}), got {table.access_control_id_field!r}.",
        )
