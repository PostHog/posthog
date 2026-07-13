import json
from collections.abc import Iterator

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.lazy_join_registry import RESOLVERS
from posthog.hogql.database.lazy_join_tags import DATA_WAREHOUSE, DATA_WAREHOUSE_EXPERIMENTS, GROUP_N
from posthog.hogql.database.models import LazyJoin, LazyJoinToAdd, Table, TableNode
from posthog.hogql.database.schema.groups import join_with_group_n_table
from posthog.hogql.database.warehouse_join_resolvers import (
    data_warehouse_resolver_params,
    resolve_data_warehouse_experiments_join,
)
from posthog.hogql.errors import ResolutionError

from products.data_tools.backend.models.join import DataWarehouseJoin


class TestLazyJoinResolvers(SimpleTestCase):
    def test_resolver_params_applies_overrides(self):
        params = data_warehouse_resolver_params(
            source_table_key="id",
            joining_table_key="account_id",
            joining_table_name="events",
            override_source_table_key="person.id",
            override_join_type="INNER JOIN",
        )

        assert params["source_table_key"] == "person.id"
        assert params["join_type"] == "INNER JOIN"
        assert params["configuration"] == {}

    def test_unknown_resolver_raises(self):
        lazy_join = LazyJoin(from_field=["id"], join_table="x", resolver="does_not_exist")
        with self.assertRaises(ValueError):
            lazy_join.resolve_join_to_add(None, None, None)  # type: ignore[arg-type]

    def test_group_n_join_requires_group_index(self):
        lazy_join = LazyJoin(from_field=["key"], join_table="groups", resolver=GROUP_N)
        join_to_add = LazyJoinToAdd(
            from_table="events",
            to_table="group_0",
            lazy_join=lazy_join,
            lazy_join_type=None,  # type: ignore[arg-type]
            fields_accessed={"key": ["key"]},
        )
        with self.assertRaises(ResolutionError):
            join_with_group_n_table(join_to_add, HogQLContext(team_id=1), ast.SelectQuery(select=[]))

    def test_experiments_join_builds_asof_join_with_timestamp_bounds(self):
        lazy_join = LazyJoin(
            from_field=["id"],
            join_table="events",
            resolver=DATA_WAREHOUSE_EXPERIMENTS,
            resolver_params=data_warehouse_resolver_params(
                source_table_key="user_id",
                joining_table_key="distinct_id",
                joining_table_name="events",
                configuration={"experiments_optimized": True, "experiments_timestamp_key": "created_at"},
            ),
        )
        join_to_add = LazyJoinToAdd(
            from_table="subscriptions",
            to_table="events",
            lazy_join=lazy_join,
            lazy_join_type=None,  # type: ignore[arg-type]
            fields_accessed={"distinct_id": ["distinct_id"]},
        )

        def timestamp_bound(op: ast.CompareOperationOp, value: str) -> ast.CompareOperation:
            return ast.CompareOperation(
                op=op,
                left=ast.Alias(alias="created_at", expr=ast.Field(chain=["subscriptions", "created_at"])),
                right=ast.Constant(value=value),
            )

        node = ast.SelectQuery(
            select=[],
            where=ast.And(
                exprs=[
                    timestamp_bound(ast.CompareOperationOp.GtEq, "2023-01-01"),
                    timestamp_bound(ast.CompareOperationOp.LtEq, "2023-02-01"),
                ]
            ),
        )

        join_expr = resolve_data_warehouse_experiments_join(join_to_add, HogQLContext(team_id=1), node)

        assert join_expr.join_type == "ASOF LEFT JOIN"
        assert isinstance(join_expr.table, ast.SelectQuery)
        assert isinstance(join_expr.table.where, ast.And)
        # The subquery filters to exposure events and copies the query's timestamp bounds in,
        # since the subquery can't reference the parent data warehouse table directly.
        flag_filter, *bounds = join_expr.table.where.exprs
        assert isinstance(flag_filter, ast.CompareOperation)
        assert isinstance(flag_filter.right, ast.Constant)
        assert flag_filter.right.value == "$feature_flag_called"
        bound_values = [
            (b.op, b.right.value)
            for b in bounds
            if isinstance(b, ast.CompareOperation) and isinstance(b.right, ast.Constant)
        ]
        assert bound_values == [
            (ast.CompareOperationOp.GtEq, "2023-01-01"),
            (ast.CompareOperationOp.LtEq, "2023-02-01"),
        ]


def _walk_lazy_joins(database: Database) -> Iterator[tuple[str, LazyJoin]]:
    """Yield every LazyJoin reachable from the database's table tree, with its path for error messages."""
    seen: set[int] = set()

    def walk_field_or_table(path: str, item: object) -> Iterator[tuple[str, LazyJoin]]:
        if id(item) in seen:
            return
        seen.add(id(item))
        if isinstance(item, LazyJoin):
            yield path, item
            if isinstance(item.join_table, Table):
                yield from walk_field_or_table(f"{path}.<join_table>", item.join_table)
        elif isinstance(item, Table):
            for name, field in item.fields.items():
                yield from walk_field_or_table(f"{path}.{name}", field)

    def walk_node(path: str, node: TableNode) -> Iterator[tuple[str, LazyJoin]]:
        if node.table is not None:
            yield from walk_field_or_table(path, node.table)
        for name, child in node.children.items():
            yield from walk_node(f"{path}.{name}", child)

    yield from walk_node("", database.tables)


class TestBuiltDatabaseSerializable(BaseTest):
    """The serializability gate: a built Database must describe every lazy join as plain data —
    a tag listed in the resolver manifest plus JSON-able params."""

    @parameterized.expand(
        [
            ("default", HogQLQueryModifiers()),
            ("sessions_v3", HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V3)),
            (
                "poe_overrides_joined",
                HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED),
            ),
        ]
    )
    def test_built_database_lazy_joins_are_serializable(self, _name: str, modifiers: HogQLQueryModifiers) -> None:
        # A user-defined join, so the walk also covers the data-warehouse attachment path —
        # the one category whose resolver_params are built from user data at build time.
        DataWarehouseJoin(
            team=self.team,
            source_table_name="cohort_people",
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="new_person",
        ).save()

        database = Database.create_for(team=self.team, modifiers=modifiers)

        lazy_joins = list(_walk_lazy_joins(database))
        assert len(lazy_joins) > 15  # sanity: the walker actually reached the schema's joins
        assert any(lj.resolver == DATA_WAREHOUSE for _, lj in lazy_joins)  # the user-defined join got attached

        for path, lazy_join in lazy_joins:
            assert lazy_join.resolver in RESOLVERS, f"{path} resolver {lazy_join.resolver!r} is not in the manifest"
            json.dumps(lazy_join.resolver_params)  # params must round-trip through JSON


class TestLazyJoinManifest(SimpleTestCase):
    def test_manifest_is_the_explicit_contract(self):
        """The manifest is the closed contract a serialized Database depends on. Changing this
        list changes what consumers of a serialized schema must implement — update deliberately."""
        assert sorted(RESOLVERS) == [
            "account_custom_properties",
            "account_notebooks",
            "account_tags",
            "data_warehouse",
            "data_warehouse_experiments",
            "error_tracking_fingerprint_issue_state",
            "error_tracking_issue_fingerprint_overrides",
            "events_to_sessions_v1",
            "events_to_sessions_v2",
            "events_to_sessions_v3",
            "foreign_key",
            "group_n",
            "groups_revenue_analytics",
            "person_distinct_id_overrides",
            "person_distinct_ids",
            "persons",
            "persons_pdi",
            "persons_revenue_analytics",
            "replay_to_console_logs",
            "replay_to_events",
            "replay_to_sessions_v1",
            "replay_to_sessions_v2",
            "replay_to_sessions_v3",
        ]
