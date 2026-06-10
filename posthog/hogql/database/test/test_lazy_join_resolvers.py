import json
from collections.abc import Iterator

from posthog.test.base import BaseTest

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode, SessionTableVersion

from posthog.hogql.database.database import Database
from posthog.hogql.database.lazy_join_registry import RESOLVERS
from posthog.hogql.database.lazy_join_tags import DATA_WAREHOUSE
from posthog.hogql.database.models import LazyJoin, Table, TableNode
from posthog.hogql.database.warehouse_join_resolvers import data_warehouse_resolver_params


class TestLazyJoinResolvers(BaseTest):
    def test_data_warehouse_join_params_round_trip_json(self):
        lazy_join = LazyJoin(
            from_field=["id"],
            to_field=["account_id"],
            join_table="stripe.accounts",
            resolver=DATA_WAREHOUSE,
            resolver_params=data_warehouse_resolver_params(
                source_table_key="id",
                joining_table_key="account_id",
                joining_table_name="stripe.accounts",
            ),
        )

        # The whole point: the join is described by plain JSON-able data, not a Python closure,
        # so the Database that holds it can be serialized and cached.
        encoded = json.dumps(lazy_join.resolver_params)
        assert "stripe.accounts" in encoded

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

    def test_resolver_is_required(self):
        with self.assertRaises(ValidationError):
            LazyJoin(from_field=["id"], join_table="x")


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
        database = Database.create_for(team=self.team, modifiers=modifiers)

        lazy_joins = list(_walk_lazy_joins(database))
        assert len(lazy_joins) > 15  # sanity: the walker actually reached the schema's joins

        for path, lazy_join in lazy_joins:
            assert lazy_join.resolver in RESOLVERS, f"{path} resolver {lazy_join.resolver!r} is not in the manifest"
            json.dumps(lazy_join.resolver_params)  # params must round-trip through JSON


class TestLazyJoinManifest(BaseTest):
    def test_manifest_is_the_explicit_contract(self):
        """The manifest is the closed contract a serialized Database depends on. Changing this
        list changes what consumers of a serialized schema must implement — update deliberately."""
        assert sorted(RESOLVERS) == [
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
