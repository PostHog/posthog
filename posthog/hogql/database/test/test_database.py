import io
import json
import pickle
import dataclasses
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest, FuzzyInt, QueryMatchingTest, snapshot_postgres_queries
from unittest import TestCase
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from pydantic import BaseModel

from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaPostHogTable,
    DataWarehouseEventsModifier,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import (
    ROOT_TABLES__DO_NOT_ADD_ANY_MORE,
    Database,
    _CatalogUnpickler,
    _compute_system_table_access_decision,
    _construct_database_root_node,
    _preload_active_external_data_schemas,
    build_database_root_node,
    get_data_warehouse_table_name,
)
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.database.lazy_join_tags import FOREIGN_KEY
from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    DatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FieldTraverser,
    LazyJoin,
    LazyTable,
    StringDatabaseField,
    Table,
    TableNode,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.database.s3_table import DataWarehouseTable as HogQLDataWarehouseTable
from posthog.hogql.errors import ExposedHogQLError, QueryError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


def _collect_mutable_object_ids(obj: Any, ids: set[int]) -> None:
    # Record the id() of every mutable object in a catalog tree, so two trees can be checked for sharing.
    stack = [obj]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, BaseModel):
            ids.add(id(current))
            stack.extend(current.__dict__.values())
        elif dataclasses.is_dataclass(current) and not isinstance(current, type):
            ids.add(id(current))
            stack.extend(getattr(current, f.name) for f in dataclasses.fields(current))
        elif isinstance(current, dict):
            ids.add(id(current))
            stack.extend(current.values())
        elif isinstance(current, (list, set)):
            ids.add(id(current))
            stack.extend(current)
        elif isinstance(current, (tuple, frozenset)):
            stack.extend(current)


class TestBuildDatabaseRootNode(TestCase):
    # The static catalog build touches no database, so these run on a plain TestCase (no Postgres).

    @parameterized.expand([("with_posthog_tables", True), ("without_posthog_tables", False)])
    def test_build_database_root_node_matches_fresh_construction(self, _name: str, include_posthog_tables: bool):
        cached = build_database_root_node(include_posthog_tables=include_posthog_tables)
        fresh = _construct_database_root_node(include_posthog_tables=include_posthog_tables)

        assert cached == fresh
        assert cached is not fresh
        if include_posthog_tables:
            assert "events" in cached.children

    @parameterized.expand([("with_posthog_tables", True), ("without_posthog_tables", False)])
    def test_build_database_root_node_catalog_stays_picklable(self, _name: str, include_posthog_tables: bool):
        # Guards against a future catalog field becoming unpicklable (which would otherwise fail at request time).
        fresh = _construct_database_root_node(include_posthog_tables=include_posthog_tables)
        restored = pickle.loads(pickle.dumps(fresh, protocol=pickle.HIGHEST_PROTOCOL))

        assert restored == fresh
        if include_posthog_tables:
            assert restored.children["events"].table is not fresh.children["events"].table

    def test_build_database_root_node_loads_are_deeply_independent(self):
        # Hold both trees while walking, or a GC'd first tree's id()s get recycled by the second (false overlap).
        first = build_database_root_node()
        second = build_database_root_node()
        first_ids: set[int] = set()
        second_ids: set[int] = set()
        _collect_mutable_object_ids(first, first_ids)
        _collect_mutable_object_ids(second, second_ids)

        assert first_ids and second_ids
        assert first_ids.isdisjoint(second_ids)

    def test_slim_pickle_state_falls_back_when_private_or_extra_present(self):
        # Slim path: a plain field round-trips its values.
        field = StringDatabaseField(name="col")
        restored = pickle.loads(pickle.dumps(field, protocol=pickle.HIGHEST_PROTOCOL))
        assert restored == field and restored.name == "col"

        # extra/private set: must fall back to full state so they survive the round-trip.
        with_private = StringDatabaseField(name="col")
        object.__setattr__(with_private, "__pydantic_private__", {"secret": 1})
        restored_private = pickle.loads(pickle.dumps(with_private, protocol=pickle.HIGHEST_PROTOCOL))
        assert restored_private.__pydantic_private__ == {"secret": 1}

        with_extra = StringDatabaseField(name="col")
        object.__setattr__(with_extra, "__pydantic_extra__", {"extra_key": "value"})
        restored_extra = pickle.loads(pickle.dumps(with_extra, protocol=pickle.HIGHEST_PROTOCOL))
        assert restored_extra.__pydantic_extra__ == {"extra_key": "value"}

    def test_catalog_unpickler_allowlists_catalog_classes_and_rejects_others(self):
        # Restricted unpickler resolves catalog classes but rejects anything else, so a tampered blob
        # can't instantiate code-execution gadgets.
        unpickler = _CatalogUnpickler(io.BytesIO(b""))
        assert unpickler.find_class("posthog.hogql.database.models", "StringDatabaseField") is not None
        assert unpickler.find_class("posthog.clickhouse.workload", "Workload") is not None
        for module, name in [
            ("os", "system"),
            ("builtins", "eval"),
            ("subprocess", "Popen"),
            ("posthog.models", "Team"),
        ]:
            with self.assertRaises(pickle.UnpicklingError):
                unpickler.find_class(module, name)


class TestDatabase(BaseTest, QueryMatchingTest):
    snapshot: Any

    def test_create_hogql_database_team_id_and_team_must_be_the_same(self):
        with self.assertRaises(ValueError, msg="team_id and team must be the same"):
            Database.create_for(team_id=self.team.pk + 1, team=self.team)

    def test_create_hogql_database_must_have_either_team_id_or_team(self):
        with self.assertRaises(ValueError, msg="Either team_id or team must be provided"):
            Database.create_for()

    def test_create_hogql_database_raises_query_error_for_missing_team(self):
        missing_team_id = self.team.pk + 10_000
        with self.assertRaises(QueryError) as cm:
            Database.create_for(team_id=missing_team_id)
        self.assertIn(str(missing_team_id), str(cm.exception))

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_no_person_on_events(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            database = Database.create_for(team=self.team, user=self.user)
            serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

            assert (
                json.dumps(
                    {table_name: table.model_dump() for table_name, table in serialized_database.items()}, indent=4
                )
                == self.snapshot
            )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_with_person_on_events_enabled(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            database = Database.create_for(team=self.team, user=self.user)
            serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

            assert (
                json.dumps(
                    {table_name: table.model_dump() for table_name, table in serialized_database.items()}, indent=4
                )
                == self.snapshot
            )

    @parameterized.expand([False, True])
    def test_can_select_from_each_table_at_all(self, poe_enabled: bool) -> None:
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=poe_enabled):
            database = Database.create_for(team=self.team)
            serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))
            for table_name, table in serialized_database.items():
                columns = [
                    field.name
                    for field in table.fields.values()
                    if field.chain is None and field.table is None and field.fields is None
                ]

                execute_hogql_query(
                    f"SELECT {','.join(columns)} FROM {table_name}",
                    team=self.team,
                    pretty=False,
                )

    def test_serialize_database_posthog_table(self):
        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        posthog_table_names = database.get_posthog_table_names()
        for table_name in posthog_table_names:
            assert serialized_database.get(table_name) is not None

    def test_apply_schema_scope_removes_lazy_joins_to_hidden_direct_tables(self):
        database = Database()
        events = PostgresTable(
            name="events",
            fields={
                "dashboard": LazyJoin(
                    from_field=["dashboard_id"],
                    to_field=["id"],
                    join_table="direct_table",
                    resolver=FOREIGN_KEY,
                )
            },
            postgres_table_name="events",
        )
        direct_table = PostgresTable(name="direct_table", fields={}, postgres_table_name="direct_table")

        database.tables.add_child(TableNode(name="events", table=events))
        database.tables.add_child(TableNode(name="direct_table", table=direct_table))
        database._warehouse_table_names = ["direct_table"]
        database._direct_access_warehouse_table_names = {"direct_table"}

        database.apply_schema_scope()

        assert database.has_table("events")
        assert not database.has_table("direct_table")
        assert "dashboard" not in cast(PostgresTable, database.get_table("events")).fields

    def test_serialize_database_deleted_saved_query(self):
        saved_query_name = "deleted_saved_query"
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="DELETED",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            deleted=True,
            deleted_name=saved_query_name,
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert saved_query_name not in serialized_database
        assert saved_query_name not in database._view_table_names
        assert "DELETED" not in serialized_database
        assert "DELETED" not in database._view_table_names

    def test_serialize_database_warehouse_table_s3_with_unknown_field(self):
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        DataWarehouseTable.objects.create(
            name="table_1",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "UnknownDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
            row_count=100,
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        table = cast(DatabaseSchemaDataWarehouseTable | None, serialized_database.get("table_1"))
        assert table is not None
        assert table.row_count == 100

        field = table.fields.get("id")
        assert field is not None
        assert field.type == "unknown"
        assert field.schema_valid is True

    def test_serialize_database_warehouse_table_s3(self):
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        DataWarehouseTable.objects.create(
            name="table_1",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        table = cast(DatabaseSchemaDataWarehouseTable | None, serialized_database.get("table_1"))
        assert table is not None
        assert len(table.fields.keys()) == 1
        assert table.source is None
        assert table.schema_ is None

        field = table.fields.get("id")
        assert field is not None
        assert field.name == "id"
        assert field.type == "string"
        assert field.schema_valid is True

    def test_serialize_database_warehouse_table_s3_with_legacy_column_shape(self):
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        DataWarehouseTable.objects.create(
            name="table_1",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": "Nullable(String)"},
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        table = cast(DatabaseSchemaDataWarehouseTable | None, serialized_database.get("table_1"))
        assert table is not None

        field = table.fields.get("id")
        assert field is not None
        assert field.name == "id"
        assert field.type == "string"
        assert field.schema_valid is True

    def test_warehouse_table_names_do_not_leak_between_database_instances(self):
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        DataWarehouseTable.objects.create(
            name="team_1_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        team_1_database = Database.create_for(team=self.team)
        assert "team_1_table" in team_1_database.get_warehouse_table_names()

        other_organization = Organization.objects.create(name="other_org")
        other_team = Team.objects.create(organization=other_organization)
        team_2_database = Database.create_for(team=other_team)

        assert "team_1_table" not in team_2_database.get_warehouse_table_names()

    def test_root_tables_do_not_leak_between_database_instances(self):
        first_root = build_database_root_node()
        second_root = build_database_root_node()

        assert first_root.children["events"] is not second_root.children["events"]

        first_database = Database()
        second_database = Database()

        assert first_database.tables.children["events"] is not second_database.tables.children["events"]

        first_database.tables.children["events"].table = None

        assert second_database.tables.children["events"].table is not None

    def test_serialize_database_warehouse_with_deleted_joins(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="event",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
            deleted=True,
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        events_table = serialized_database.get("events")
        assert events_table is not None

        joined_field = events_table.fields.get("some_field")
        assert joined_field is None

    def test_serialize_database_warehouse_table_s3_with_hyphens(self):
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        DataWarehouseTable.objects.create(
            name="table_1",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "id-hype": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
            },
            row_count=100,
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        table = cast(DatabaseSchemaDataWarehouseTable | None, serialized_database.get("table_1"))
        assert table is not None
        assert table.row_count == 100

        field = table.fields.get("id-hype")
        assert field is not None
        assert field.name == "id-hype"
        assert field.hogql_value == "`id-hype`"

    def test_serialize_database_warehouse_table_source(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        warehouse_table = DataWarehouseTable.objects.create(
            name="stripe_table_1",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            external_data_source_id=source.id,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="table_1",
            source=source,
            table=warehouse_table,
            should_sync=True,
            last_synced_at="2024-01-01",
            # No status but should be completed because a data warehouse table already exists
        )

        database = Database.create_for(team=self.team)
        serialized_database = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        table = cast(DatabaseSchemaDataWarehouseTable | None, serialized_database.get("stripe.table_1"))
        assert table is not None
        assert len(table.fields.keys()) == 1

        # The table is also queryable by its raw underscore name, so it must be surfaced for search
        assert table.search_aliases == ["stripe_table_1"]

        assert table.source is not None
        assert table.source.id == str(source.id)
        assert table.source.status == "Completed"
        assert table.source.source_type == "Stripe"

        assert table.schema_ is not None
        assert table.schema_.id == str(schema.id)
        assert table.schema_.name == "table_1"
        assert table.schema_.should_sync is True
        assert table.schema_.incremental is False
        assert table.schema_.status is None
        assert table.schema_.last_synced_at == "2024-01-01 00:00:00+00:00"

        field = table.fields.get("id")
        assert field is not None
        assert field.name == "id"
        assert field.hogql_value == "id"
        assert field.type == "string"
        assert field.schema_valid is True

    def _create_warehouse_table(self, *, name, url_pattern, source=None, credential=None):
        return DataWarehouseTable.objects.create(
            name=name,
            format="Parquet",
            team=self.team,
            external_data_source=source,
            credential=credential,
            url_pattern=url_pattern,
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

    def test_create_hogql_database_ignores_tables_of_deleted_sources(self):
        # A table left behind by a soft-deleted source must not shadow the live table that a
        # re-connected source created under the same name (the orphan-table resolution bug).
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")

        deleted_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="old",
            connection_id="old",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        # Created first, so without the fix it would win the first-come tree insertion. Mark the
        # source — not the table — deleted to reproduce the orphan state (table.deleted stays False).
        self._create_warehouse_table(
            name="pull_requests", url_pattern="s3://orphan/*", source=deleted_source, credential=credential
        )
        deleted_source.deleted = True
        deleted_source.save()

        live_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="new",
            connection_id="new",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self._create_warehouse_table(
            name="pull_requests", url_pattern="s3://live/*", source=live_source, credential=credential
        )

        database = Database.create_for(team=self.team)

        assert database.has_table("pull_requests")
        assert cast(HogQLDataWarehouseTable, database.get_table("pull_requests")).url == "s3://live/*"

    def test_create_hogql_database_keeps_self_managed_table_without_source(self):
        # Guards the deleted-source exclusion against the Django exclude()-with-NULL gotcha:
        # a self-managed table (no source) must still resolve.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        self._create_warehouse_table(name="self_managed", url_pattern="s3://self/*", credential=credential)

        database = Database.create_for(team=self.team)

        assert database.has_table("self_managed")
        assert cast(HogQLDataWarehouseTable, database.get_table("self_managed")).url == "s3://self/*"

    def test_create_hogql_database_resolves_duplicate_live_table_names_to_newest(self):
        # Two live tables share a name (e.g. a re-sync produced a duplicate): newest wins.
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="k", access_secret="s")
        older = self._create_warehouse_table(name="pull_requests", url_pattern="s3://older/*", credential=credential)
        newer = self._create_warehouse_table(name="pull_requests", url_pattern="s3://newer/*", credential=credential)

        # Pin created_at explicitly (bypasses auto_now_add) so the tiebreak is deterministic.
        DataWarehouseTable.objects.filter(pk=older.pk).update(created_at="2024-01-01T00:00:00+00:00")
        DataWarehouseTable.objects.filter(pk=newer.pk).update(created_at="2024-06-01T00:00:00+00:00")

        database = Database.create_for(team=self.team)

        assert cast(HogQLDataWarehouseTable, database.get_table("pull_requests")).url == "s3://newer/*"

    def test_serialize_database_warehouse_table_source_query_count(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id_1",
            connection_id="connection_id_1",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=self.team)
        warehouse_table = DataWarehouseTable.objects.create(
            name="table_1",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            external_data_source_id=source.id,
            credential=credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name="table_1",
            source=source,
            table=warehouse_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        database = Database.create_for(team=self.team)
        with self.assertNumQueries(4):
            database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        for i in range(5):
            source = ExternalDataSource.objects.create(
                team=self.team,
                source_id=f"source_id_{i + 2}",
                connection_id=f"connection_id_{i + 2}",
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.STRIPE,
            )
            warehouse_table = DataWarehouseTable.objects.create(
                name=f"table_{i + 2}",
                format="Parquet",
                team=self.team,
                external_data_source=source,
                external_data_source_id=source.id,
                credential=credentials,
                url_pattern="https://bucket.s3/data/*",
                columns={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
                },
            )
            ExternalDataSchema.objects.create(
                team=self.team,
                name=f"table_{i + 2}",
                source=source,
                table=warehouse_table,
                should_sync=True,
                last_synced_at="2024-01-01",
            )

        database = Database.create_for(team=self.team)

        with self.assertNumQueries(4):
            database.serialize(HogQLContext(team_id=self.team.pk, database=database))

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_database_with_warehouse_tables(self, patch_execute):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            name="whatever",
            team=self.team,
            columns={"id": "String"},
            credential=credential,
            url_pattern="",
        )
        Database.create_for(team=self.team)

        response = execute_hogql_query(
            "select * from whatever",
            team=self.team,
            pretty=False,
        )

        self.assertEqual(
            response.clickhouse,
            f"SELECT whatever.id AS id FROM s3(%(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s, %(hogql_val_1)s, %(hogql_val_2)s) AS whatever LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, optimize_rewrite_aggregate_function_with_if=0, optimize_min_inequality_conjunction_chain_length=4294967295, allow_experimental_join_condition=1, use_hive_partitioning=0",
        )

    @snapshot_postgres_queries
    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_database_with_warehouse_tables_and_saved_queries_n_plus_1(self, patch_execute):
        # +1 vs the pre-bulk-credential baseline: one bulk credential fetch replaces the per-row
        # credential joins (decrypt once per credential, not per table/view).
        max_queries = FuzzyInt(7, 9)
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            name="whatever",
            team=self.team,
            columns={"id": "String"},
            credential=credential,
            url_pattern="",
        )

        for i in range(5):
            new_credential = DataWarehouseCredential.objects.create(
                team=self.team, access_key="_accesskey", access_secret="_secret"
            )
            table = DataWarehouseTable.objects.create(
                name=f"whatever{i}",
                team=self.team,
                columns={"id": "String"},
                credential=new_credential,
                url_pattern="",
            )
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"whatever_view{i}",
                query={"query": f"SELECT id FROM whatever{i}"},
                columns={"id": "String"},
                table=table,
                status=DataWarehouseSavedQuery.Status.COMPLETED,
            )

        with self.assertNumQueries(max_queries):
            modifiers = create_default_modifiers_for_team(
                self.team, modifiers=HogQLQueryModifiers(useMaterializedViews=True)
            )
            Database.create_for(team=self.team, modifiers=modifiers)

        for i in range(5):
            table = DataWarehouseTable.objects.create(
                name=f"whatever{i + 5}",
                team=self.team,
                columns={"id": "String"},
                credential=new_credential,
                url_pattern="",
            )
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"whatever_view{i + 5}",
                query={"query": f"SELECT id FROM whatever{i + 5}"},
                columns={"id": "String"},
                table=table,
                status=DataWarehouseSavedQuery.Status.COMPLETED,
            )

        # initialization team query doesn't run; the extra query is the single bulk credential fetch
        # (credentials are decrypted once each here instead of re-decrypted per table/view row)
        with self.assertNumQueries(6):
            modifiers = create_default_modifiers_for_team(
                self.team, modifiers=HogQLQueryModifiers(useMaterializedViews=True)
            )
            Database.create_for(team=self.team, modifiers=modifiers)

    def test_database_group_type_mappings(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="test", group_type_index=0
        )
        invalidate_group_types_cache(self.team.project_id)
        db = Database.create_for(team=self.team)

        assert db.get_table("events").fields["test"] == FieldTraverser(chain=["group_0"])

    def test_database_group_type_mappings_overwrite(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="event", group_type_index=0
        )
        invalidate_group_types_cache(self.team.project_id)
        db = Database.create_for(team=self.team)

        event_field = db.get_table("events").fields["event"]
        assert isinstance(event_field, StringDatabaseField)
        assert event_field.name == "event"
        assert event_field.nullable is False
        assert not event_field.array
        assert event_field.hidden is False

    def test_database_expression_fields(self):
        db = Database.create_for(team=self.team)

        numbers_table = db.get_table("numbers")
        numbers_table.fields["expression"] = ExpressionField(name="expression", expr=parse_expr("1 + 1"))
        numbers_table.fields["double"] = ExpressionField(name="double", expr=parse_expr("number * 2"))
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        sql = "select number, double, expression + number from numbers(2)"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            query
            == f"SELECT numbers.number AS number, multiply(numbers.number, 2) AS double, plus(plus(1, 1), numbers.number) FROM numbers(2) AS numbers LIMIT {MAX_SELECT_RETURNED_ROWS}"
        ), query

        sql = "select double from (select double from numbers(2))"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            query
            == f"SELECT double AS double FROM (SELECT multiply(numbers.number, 2) AS double FROM numbers(2) AS numbers) LIMIT {MAX_SELECT_RETURNED_ROWS}"
        ), query

        # expression fields are not included in select *
        sql = "select * from (select * from numbers(2))"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            query
            == f"SELECT number AS number, expression AS expression, double AS double FROM (SELECT numbers.number AS number, plus(1, 1) AS expression, multiply(numbers.number, 2) AS double FROM numbers(2) AS numbers) LIMIT {MAX_SELECT_RETURNED_ROWS}"
        ), query

    def test_database_warehouse_joins(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="event",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select some_field.key from events"
        prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_build_from_sources_performs_no_io(self, patch_execute):
        # _fetch_sources does all the Postgres / feature-flag I/O; _build_from_sources must not query.
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        for i in range(3):
            DataWarehouseTable.objects.create(
                name=f"whatever{i}",
                team=self.team,
                columns={"id": "String"},
                credential=credential,
                url_pattern="",
            )
            saved_query = DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"whatever_view{i}",
                query={"query": f"SELECT id FROM whatever{i}"},
                columns={"id": "String"},
                status=DataWarehouseSavedQuery.Status.COMPLETED,
            )
            # Give the view a materialized backing table so the build exercises that path with no IO
            backing_table = DataWarehouseTable.objects.create(
                name=f"whatever_view{i}",
                team=self.team,
                columns={"id": "String"},
                credential=credential,
                url_pattern=saved_query.url_pattern,
            )
            saved_query.table = backing_table
            saved_query.save(update_fields=["table"])
        # Endpoint-origin saved query so the endpoint build loop is exercised under assertNumQueries(0).
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="whatever_endpoint",
            query={"query": "SELECT id FROM whatever0"},
            columns={"id": "String"},
            status=DataWarehouseSavedQuery.Status.COMPLETED,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="event",
            joining_table_name="whatever0",
            joining_table_key="id",
            field_name="some_field",
        )

        # A dataWarehouseEventsModifier so the define_mappings path (get_clickhouse_column_type, the
        # events-join lookup) is also exercised under assertNumQueries(0) - it used to query per modifier.
        modifiers = create_default_modifiers_for_team(
            self.team,
            modifiers=HogQLQueryModifiers(
                useMaterializedViews=True,
                dataWarehouseEventsModifiers=[
                    DataWarehouseEventsModifier(
                        table_name="whatever0",
                        id_field="id",
                        timestamp_field="created_at",
                        distinct_id_field="id",
                    )
                ],
            ),
        )
        sources = Database._fetch_sources(team=self.team, modifiers=modifiers)

        with self.assertNumQueries(0):
            db = Database._build_from_sources(sources)

        # The warehouse table, saved query, endpoint view, join and modifier were all wired up without queries.
        assert db.has_table("whatever0")
        assert db.has_table("whatever_view0")
        assert db.has_table("whatever_endpoint")
        assert "some_field" in db.get_table("events").fields
        assert "timestamp" in db.get_table("whatever0").fields

    def test_materialized_backing_filter_keeps_source_tables_but_hides_backing_tables(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        source_table = DataWarehouseTable.objects.create(
            name="stripe_charge",
            team=self.team,
            columns={"id": "String"},
            credential=credential,
            url_pattern="s3://source/stripe_charge/*",
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="charges_view",
            query={"query": "SELECT id FROM stripe_charge"},
            columns={"id": "String"},
            table=source_table,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

        renamed_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="renamed_view",
            query={"query": "SELECT id FROM stripe_charge"},
            columns={"id": "String"},
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )
        backing_table = DataWarehouseTable.objects.create(
            name="old_view_name",
            team=self.team,
            columns={"id": "String"},
            credential=credential,
            url_pattern=renamed_view.url_pattern,
        )
        renamed_view.table = backing_table
        renamed_view.save(update_fields=["table"])

        database = Database.create_for(team=self.team, bypass_warehouse_access_control=True)

        assert database.has_table("stripe_charge")
        assert database.has_table("charges_view")
        assert database.has_table("renamed_view")
        assert not database.has_table("old_view_name")

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_build_from_sources_performs_no_io_for_direct_postgres(self, patch_execute):
        # Direct-query mode builds a DirectPostgresTable, whose hogql_definition reads the source's
        # job_inputs when no schema option is set on the table. _fetch_sources must hydrate job_inputs in
        # this mode (defer_job_inputs=False) rather than deferring it, so the build phase stays query-free;
        # otherwise the deferred field would lazily reload during build. This guards that branch.
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="direct_source",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"schema": "myschema"},
        )
        # No direct_postgres_schema in options, so hogql_definition falls back to job_inputs["schema"].
        DataWarehouseTable.objects.create(
            name="direct_table",
            format="Parquet",
            team=self.team,
            credential=credential,
            external_data_source=source,
            external_data_source_id=source.id,
            url_pattern="s3://test/*",
            columns={"id": {"clickhouse": "Int64", "hogql": "integer"}},
        )

        sources = Database._fetch_sources(team=self.team, connection_id=str(source.id))

        with self.assertNumQueries(0):
            db = Database._build_from_sources(sources)

        direct_table = db.get_table("direct_table")
        assert isinstance(direct_table, DirectPostgresTable)
        # The schema came from the source's job_inputs, proving that branch ran during the zero-query build.
        assert direct_table.postgres_schema == "myschema"

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_build_from_sources_resolves_direct_snowflake_case_insensitively(self, patch_execute):
        # Snowflake stores object names uppercase but resolves unquoted identifiers case-insensitively.
        # A natural all-lowercase query must resolve to the canonical uppercase table and columns.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="snowflake_source",
            source_type=ExternalDataSourceType.SNOWFLAKE,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"database": "DB", "schema": ""},
        )
        DataWarehouseTable.objects.create(
            name="TPCH_SF1.NATION",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            external_data_source_id=source.id,
            url_pattern="s3://test/*",
            options={
                "direct_snowflake_catalog": "DB",
                "direct_snowflake_schema": "TPCH_SF1",
                "direct_snowflake_table": "NATION",
            },
            columns={"N_NAME": {"clickhouse": "String", "hogql": "string"}},
        )

        sources = Database._fetch_sources(team=self.team, connection_id=str(source.id))
        db = Database._build_from_sources(sources)

        canonical = db.get_table("TPCH_SF1.NATION")
        assert isinstance(canonical, DirectSnowflakeTable)
        # Any-case table name resolves to the same direct table (Snowflake folds unquoted names).
        for typed_name in ("tpch_sf1.nation", "Tpch_Sf1.Nation", "TPCH_SF1.nation"):
            resolved = db.get_table(typed_name)
            assert isinstance(resolved, DirectSnowflakeTable), typed_name
        # Columns resolve regardless of case and report their canonical stored name.
        assert canonical.has_field("n_name")
        resolved_field = canonical.get_field("N_Name")
        assert isinstance(resolved_field, DatabaseField)
        assert resolved_field.name == "N_NAME"

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_build_from_sources_keeps_non_snowflake_tables_case_sensitive(self, patch_execute):
        # The case-insensitive fallback is opt-in per node, so a non-Snowflake direct table must NOT
        # resolve under a different case.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="pg_source",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"schema": "public"},
        )
        DataWarehouseTable.objects.create(
            name="accounts",
            format="Parquet",
            team=self.team,
            external_data_source=source,
            external_data_source_id=source.id,
            url_pattern="s3://test/*",
            columns={"id": {"clickhouse": "Int64", "hogql": "integer"}},
        )

        sources = Database._fetch_sources(team=self.team, connection_id=str(source.id))
        db = Database._build_from_sources(sources)

        assert db.has_table("accounts")
        assert not db.has_table("ACCOUNTS")

    @patch("posthog.hogql.query.sync_execute", return_value=([], []))
    def test_build_from_sources_raises_when_modifier_table_has_no_backing_row(self, patch_execute):
        # A dataWarehouseEventsModifier whose table resolves to a node with no backing row must fail
        # loudly (as the eager .latest() did), not silently skip timestamp-field resolution.
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orphan_view",
            query={"query": "SELECT id FROM events"},
            columns={"id": "String"},
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )
        modifiers = create_default_modifiers_for_team(
            self.team,
            modifiers=HogQLQueryModifiers(
                dataWarehouseEventsModifiers=[
                    DataWarehouseEventsModifier(
                        table_name="orphan_view",
                        id_field="id",
                        timestamp_field="created_at",
                        distinct_id_field="id",
                    )
                ],
            ),
        )
        sources = Database._fetch_sources(team=self.team, modifiers=modifiers)
        # Simulate the node existing without a backing saved-query row (e.g. a revenue-analytics view).
        sources.event_modifier_saved_queries["orphan_view"] = None

        with self.assertRaises(DataWarehouseSavedQuery.DoesNotExist):
            Database._build_from_sources(sources)

    def test_database_warehouse_joins_on_system_table_are_serialized(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="system.accounts",
            source_table_key="external_id",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="my_join_field",
        )

        db = Database.create_for(team=self.team, user=self.user)
        context = HogQLContext(team_id=self.team.pk, database=db)
        serialized = db.serialize(context, include_only={"system.accounts"})

        assert "system.accounts" in serialized
        assert "my_join_field" in serialized["system.accounts"].fields

    def test_database_warehouse_joins_deleted_join(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="lower(event)",
            joining_table_name="groups",
            joining_table_key="upper(key)",
            field_name="some_field",
            deleted=True,
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select some_field.key from events"
        with pytest.raises(ExposedHogQLError):
            prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

    def test_database_warehouse_joins_other_team(self):
        other_organization = Organization.objects.create(name="some_other_org")
        other_team = Team.objects.create(organization=other_organization)

        DataWarehouseJoin.objects.create(
            team=other_team,
            source_table_name="events",
            source_table_key="lower(event)",
            joining_table_name="groups",
            joining_table_key="upper(key)",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select some_field.key from events"
        with pytest.raises(ExposedHogQLError):
            prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

    def test_database_warehouse_joins_bad_key_expression(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="blah_de_blah(event)",
            joining_table_name="groups",
            joining_table_key="upper(key)",
            field_name="some_field",
        )

        Database.create_for(team=self.team)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_database_warehouse_joins_persons_no_poe(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        pdi = cast(LazyJoin, db.get_table("events").fields["pdi"])
        pdi_persons_join = cast(LazyJoin, pdi.resolve_table(context).fields["person"])
        pdi_table = pdi_persons_join.resolve_table(context)

        assert pdi_table.fields["some_field"] is not None

        prepare_and_print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_database_warehouse_joins_persons_poe_v1(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        poe = cast(Table, db.get_table("events").fields["poe"])

        assert poe.fields["some_field"] is not None

        prepare_and_print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_database_warehouse_joins_persons_poe_v2(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        poe = cast(Table, db.get_table("events").fields["poe"])

        assert poe.fields["some_field"] is not None

        printed, _ = prepare_and_print_ast(
            parse_select("select person.some_field.key from events"), context, dialect="clickhouse"
        )

        assert pretty_print_in_tests(printed, self.team.pk) == self.snapshot

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_database_warehouse_joins_persons_poe_v2_source_key_ast_call(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="toString(properties.email)",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        poe = cast(Table, db.get_table("events").fields["poe"])

        assert poe.fields["some_field"] is not None

        printed, _ = prepare_and_print_ast(
            parse_select("select person.some_field.key from events"), context, dialect="clickhouse"
        )

        assert pretty_print_in_tests(printed, self.team.pk) == self.snapshot

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_database_warehouse_joins_persons_poe_v2_source_key_nested_ast_call(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="toString(ifNull(properties.email, ''))",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        poe = cast(Table, db.get_table("events").fields["poe"])

        assert poe.fields["some_field"] is not None

        prepare_and_print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")

    def test_database_warehouse_joins_on_view(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="event_view",
            query={"query": "SELECT event AS event from events"},
            columns={"event": "String"},
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="event_view",
            source_table_key="event",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        sql = "select event_view.some_field.key from event_view"
        prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

        sql = "select some_field.key from event_view"
        prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

        sql = "select e.some_field.key from event_view as e"
        prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")

    def test_selecting_from_persons_ignores_future_persons(self):
        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        sql = "select id from persons"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            "equals(argMax(person.is_deleted, person.version), 0), less(argMax(toTimeZone(person.created_at, %(hogql_val_0)s), person.version), plus(now64(6, %(hogql_val_1)s), toIntervalDay(1))"
            in query
        ), query

    def test_selecting_persons_from_events_ignores_future_persons(self):
        db = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
            # disable PoE
            modifiers=create_default_modifiers_for_team(
                self.team, HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED)
            ),
        )
        sql = "select person.id from events"
        query, _ = prepare_and_print_ast(parse_select(sql), context, dialect="clickhouse")
        assert (
            "less(argMax(toTimeZone(person.created_at, %(hogql_val_0)s), person.version), plus(now64(6, %(hogql_val_1)s), toIntervalDay(1)))"
            in query
        ), query

    def test_database_credentials_is_not_n_plus_1(self) -> None:
        for i in range(10):
            # we keep adding credentials and tables, number of queries should be stable
            credentials = DataWarehouseCredential.objects.create(
                access_key=f"blah-{i}", access_secret="blah", team=self.team
            )
            DataWarehouseTable.objects.create(
                name=f"table_{i}",
                format="Parquet",
                team=self.team,
                credential=credentials,
                url_pattern="https://bucket.s3/data/*",
                columns={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
                },
            )

            # +1 vs the pre-bulk-credential baseline: one bulk credential fetch replaces the per-row
            # credential joins (decrypt once per credential, not per table/view).
            with self.assertNumQueries(FuzzyInt(6, 9)):
                Database.create_for(team=self.team)

    # We keep adding sources, credentials and tables, number of queries should be stable
    def test_external_data_source_is_not_n_plus_1(self) -> None:
        # +2 vs the pre-bulk baseline: one bulk source fetch and one bulk credential fetch replace the
        # per-row source/credential joins (hydrate/decrypt once each, not per table).
        num_queries = FuzzyInt(7, 13)

        for i in range(10):
            source = ExternalDataSource.objects.create(
                team=self.team,
                source_id=f"source_id_{i}",
                connection_id=f"connection_id_{i}",
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.STRIPE,
            )
            credentials = DataWarehouseCredential.objects.create(
                access_key=f"blah-{i}", access_secret="blah", team=self.team
            )
            warehouse_table = DataWarehouseTable.objects.create(
                name=f"table_{i}",
                format="Parquet",
                team=self.team,
                external_data_source=source,
                external_data_source_id=source.id,
                credential=credentials,
                url_pattern="https://bucket.s3/data/*",
                columns={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
                },
            )
            ExternalDataSchema.objects.create(
                team=self.team,
                name=f"table_{i}",
                source=source,
                table=warehouse_table,
                should_sync=True,
                last_synced_at="2024-01-01",
            )

            with self.assertNumQueries(num_queries):
                Database.create_for(team=self.team)

    def test_database_warehouse_joins_persons_poe_old_properties(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="some_field",
        )

        db = Database.create_for(team=self.team)

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        person_on_event_table = cast(LazyJoin, db.get_table("events").fields["person"])
        assert "some_field" in person_on_event_table.join_table.fields.keys()  # type: ignore

        prepare_and_print_ast(parse_select("select person.some_field.key from events"), context, dialect="clickhouse")

    def test_database_warehouse_person_id_field_with_events_join(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="warehouse_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={"id": "String", "user_id": "String", "timestamp": "DateTime64(3, 'UTC')"},
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="warehouse_table",
            source_table_key="user_id",
            joining_table_name="events",
            joining_table_key="distinct_id",
            field_name="events_data",
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="warehouse_table",
                    id_field="id",
                    timestamp_field="timestamp",
                    distinct_id_field="user_id",
                )
            ]
        )
        db = Database.create_for(team=self.team, modifiers=modifiers)

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        actual_table = db.get_table("warehouse_table")
        person_id_field = actual_table.fields.get("person_id")

        assert isinstance(person_id_field, FieldTraverser)
        assert person_id_field.chain == ["events_data", "person_id"]

        prepare_and_print_ast(parse_select("SELECT person_id FROM warehouse_table"), context, dialect="clickhouse")

    def test_data_warehouse_events_modifier_remaps_timestamp_over_existing_column(self):
        # A warehouse table can have its own DateTime column literally named `timestamp` (e.g. an
        # ingestion timestamp) while the series is configured to use a different event-time column.
        # The configured timestamp_field must win: `timestamp` should resolve to the configured column,
        # not the table's own `timestamp`, so queries don't silently bucket/filter on the wrong column.
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="decoy_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={
                "id": "String",
                "event_time": "DateTime64(3, 'UTC')",
                "timestamp": "DateTime64(3, 'UTC')",
            },
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="decoy_table",
                    id_field="id",
                    timestamp_field="event_time",
                    distinct_id_field="id",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)

        timestamp_field = db.get_table("decoy_table").fields["timestamp"]
        assert isinstance(timestamp_field, ExpressionField)
        assert isinstance(timestamp_field.expr, ast.Field)
        assert timestamp_field.expr.chain == ["event_time"]

    def test_data_warehouse_events_modifier_keeps_existing_timestamp_column_when_configured(self):
        # When the configured timestamp_field is `timestamp` itself, the table's own DateTime column
        # should be used directly rather than wrapped in a remapping expression.
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="native_timestamp_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={"id": "String", "timestamp": "DateTime64(3, 'UTC')"},
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="native_timestamp_table",
                    id_field="id",
                    timestamp_field="timestamp",
                    distinct_id_field="id",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)

        timestamp_field = db.get_table("native_timestamp_table").fields["timestamp"]
        assert isinstance(timestamp_field, DateTimeDatabaseField)

    @parameterized.expand(
        [
            ("id", "real_id"),
            ("distinct_id", "real_distinct_id"),
        ]
    )
    def test_data_warehouse_events_modifier_remaps_identity_field_over_existing_column(
        self, virtual_field: str, configured_column: str
    ):
        # A warehouse table can have its own column literally named `id` / `distinct_id` while the
        # series is configured to use a different column. The configured `id_field` / `distinct_id_field`
        # must win, so the virtual field resolves to the configured column rather than the table's own
        # decoy column (which would otherwise be selected silently).
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="decoy_identity_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={
                "real_id": "String",
                "real_distinct_id": "String",
                "id": "String",
                "distinct_id": "String",
                "created_at": "DateTime64(3, 'UTC')",
            },
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="decoy_identity_table",
                    id_field="real_id",
                    distinct_id_field="real_distinct_id",
                    timestamp_field="created_at",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)

        field = db.get_table("decoy_identity_table").fields[virtual_field]
        assert isinstance(field, ExpressionField)
        assert isinstance(field.expr, ast.Field)
        assert field.expr.chain == [configured_column]

    @parameterized.expand(
        [
            ("id",),
            ("distinct_id",),
        ]
    )
    def test_data_warehouse_events_modifier_keeps_existing_identity_column_when_configured(self, virtual_field: str):
        # When the configured field name equals the virtual field name, the table's own column is used
        # directly rather than wrapped in a remapping expression.
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="native_identity_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={
                "id": "String",
                "distinct_id": "String",
                "created_at": "DateTime64(3, 'UTC')",
            },
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="native_identity_table",
                    id_field="id",
                    distinct_id_field="distinct_id",
                    timestamp_field="created_at",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)

        field = db.get_table("native_identity_table").fields[virtual_field]
        assert isinstance(field, StringDatabaseField)
        assert not isinstance(field, ExpressionField)

    def test_data_warehouse_events_modifier_keeps_existing_person_id_column(self):
        # Unlike id/distinct_id/timestamp, person_id has no configured field on the modifier to remap
        # from, and a native `person_id` column is treated as authoritative (e.g. an already-resolved
        # person UUID). It must win over the distinct_id-derived fallback rather than being overridden.
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="native_person_id_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={
                "id": "String",
                "user_id": "String",
                "person_id": "String",
                "created_at": "DateTime64(3, 'UTC')",
            },
        )
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="native_person_id_table",
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created_at",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)

        person_id_field = db.get_table("native_person_id_table").fields["person_id"]
        assert isinstance(person_id_field, StringDatabaseField)
        assert not isinstance(person_id_field, ExpressionField)

    def test_data_warehouse_events_modifiers_with_dot_notation(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            source_type=ExternalDataSourceType.STRIPE,
        )
        DataWarehouseTable.objects.create(
            name="stripe_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="s3://test/*",
            columns={"id": "String", "customer_id": "String", "created": "DateTime64(3, 'UTC')"},
        )

        # Table should be accessible via dot notation (stripe.table)
        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name="stripe.table",
                    id_field="id",
                    timestamp_field="created",
                    distinct_id_field="customer_id",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)

        stripe_table = db.get_table("stripe.table")
        assert isinstance(stripe_table, Table)

        # Ensure the correct table was retrieved by checking the original table name in dot notation mapping
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        # Doesn't throw
        prepare_and_print_ast(
            parse_select("SELECT id, timestamp, distinct_id FROM stripe.table"), context, dialect="clickhouse"
        )

    @parameterized.expand(
        [
            ("self_managed", False),
            ("external_source", True),
        ]
    )
    def test_data_warehouse_events_modifiers_when_view_and_table_share_a_name(
        self, _name: str, use_external_source: bool
    ):
        shared_name = "analytics_search_history"

        warehouse_table_kwargs: dict[str, Any] = {}
        if use_external_source:
            credentials = DataWarehouseCredential.objects.create(
                access_key="test_key", access_secret="test_secret", team=self.team
            )
            source = ExternalDataSource.objects.create(
                team=self.team,
                source_id="source_id",
                source_type=ExternalDataSourceType.STRIPE,
            )
            warehouse_table_kwargs = {
                "credential": credentials,
                "external_data_source": source,
            }

        DataWarehouseTable.objects.create(
            name=shared_name,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            team=self.team,
            url_pattern=f"s3://test/{shared_name}",
            queryable_folder=f"{shared_name}__query_1776789614",
            columns={
                "email": "Nullable(String)",
                "user_name": "Nullable(String)",
                "created_at": "Nullable(DateTime64(6))",
                "search_count": "Nullable(Float64)",
                "search_source": "Nullable(String)",
            },
            **warehouse_table_kwargs,
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=shared_name,
            query={"query": "SELECT 1 AS ignored_value", "kind": "HogQLQuery"},
            columns={"ignored_value": "UInt8"},
        )

        modifiers = HogQLQueryModifiers(
            dataWarehouseEventsModifiers=[
                DataWarehouseEventsModifier(
                    table_name=shared_name,
                    id_field="user_name",
                    timestamp_field="created_at",
                    distinct_id_field="user_name",
                )
            ]
        )

        db = Database.create_for(team=self.team, modifiers=modifiers)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        actual_table = db.get_table(shared_name)

        assert isinstance(actual_table, Table)
        assert isinstance(actual_table.fields.get("id"), ExpressionField)
        assert isinstance(actual_table.fields.get("timestamp"), ExpressionField)
        assert isinstance(actual_table.fields.get("distinct_id"), ExpressionField)
        assert isinstance(actual_table.fields.get("person_id"), ExpressionField)

        prepare_and_print_ast(
            parse_select(f"SELECT id, timestamp, distinct_id, person_id FROM {shared_name}"),
            context,
            dialect="clickhouse",
        )

    def test_direct_postgres_table_supports_properties_virtual_table(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        DataWarehouseTable.objects.create(
            name="direct_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            external_data_source_id=source.id,
            url_pattern="s3://test/*",
            columns={"id": {"clickhouse": "Int64", "hogql": "integer"}},
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        direct_table = database.get_table("direct_table")

        assert isinstance(direct_table, Table)
        assert "properties" in direct_table.fields

    def test_global_database_skips_loading_direct_query_tables(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        direct_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="direct_source_id",
            connection_id="direct_connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        warehouse_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="warehouse_source_id",
            connection_id="warehouse_connection_id",
            source_type=ExternalDataSourceType.STRIPE,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            prefix="stripe",
        )
        direct_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=direct_source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True}},
        )
        warehouse_table = DataWarehouseTable.objects.create(
            name="stripe_customers",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=warehouse_source,
            url_pattern="s3://test/*",
            columns={"id": {"hogql": "string", "clickhouse": "String", "schema_valid": True}},
        )

        with patch(
            "posthog.hogql.database.database._preload_active_external_data_schemas",
            wraps=_preload_active_external_data_schemas,
        ) as preload_mock:
            Database.create_for(team=self.team)

        loaded_table_ids = {table.id for table in preload_mock.call_args.args[0]}

        assert warehouse_table.id in loaded_table_ids
        assert direct_table.id not in loaded_table_ids

    def test_direct_database_only_loads_requested_connection_tables(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        first_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="first_source_id",
            connection_id="first_connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="first",
        )
        second_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="second_source_id",
            connection_id="second_connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="second",
        )
        first_table = DataWarehouseTable.objects.create(
            name="first_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=first_source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="second_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=second_source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True}},
        )

        with patch(
            "posthog.hogql.database.database._preload_active_external_data_schemas",
            wraps=_preload_active_external_data_schemas,
        ) as preload_mock:
            Database.create_for(team=self.team, connection_id=str(first_source.id))

        loaded_tables = preload_mock.call_args.args[0]

        assert [table.id for table in loaded_tables] == [first_table.id]

    def test_adds_foreign_key_joins_for_direct_postgres_tables(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        team_table = DataWarehouseTable.objects.create(
            name="posthog_team",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "name": {"hogql": "string", "clickhouse": "String", "schema_valid": True},
            },
        )
        activitylog_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "team_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(name="posthog_team", team=self.team, source=source, table=team_table)
        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=activitylog_table,
            sync_type_config={
                "schema_metadata": {
                    "foreign_keys": [
                        {
                            "column": "team_id",
                            "target_table": "posthog_team",
                            "target_column": "id",
                        }
                    ]
                }
            },
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        activitylog = database.get_table("posthog_activitylog")
        team = database.get_table("posthog_team")

        assert isinstance(activitylog.fields.get("team"), LazyJoin)
        assert isinstance(team.fields.get("posthog_activitylogs"), LazyJoin)

    def test_direct_postgres_foreign_key_joins_ignore_deleted_schemas(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        team_table = DataWarehouseTable.objects.create(
            name="posthog_team",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True}},
        )
        activitylog_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "actor_key": {"hogql": "string", "clickhouse": "String", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(name="posthog_team", team=self.team, source=source, table=team_table)
        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=activitylog_table,
            deleted=True,
            sync_type_config={
                "schema_metadata": {
                    "foreign_keys": [
                        {
                            "column": "actor_key",
                            "target_table": "posthog_team",
                            "target_column": "name",
                        }
                    ]
                }
            },
        )
        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=activitylog_table,
            sync_type_config={"schema_metadata": {"foreign_keys": []}},
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        activitylog = database.get_table("posthog_activitylog")

        assert activitylog.fields.get("team") is None

    def test_direct_postgres_foreign_key_joins_do_not_leak_to_posthog_tables(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        activitylog_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "person_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=activitylog_table,
        )

        database = Database.create_for(team=self.team)
        persons = database.get_table("persons")

        assert not database.has_table("postgres.ph3.posthog_activitylog")
        assert persons.fields.get("posthog_activitylogs") is None

    def test_direct_postgres_foreign_key_joins_do_not_resolve_global_targets_in_direct_mode(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        activitylog_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "person_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=activitylog_table,
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        activitylog = database.get_table("posthog_activitylog")

        assert activitylog.fields.get("person") is None

    def test_direct_postgres_foreign_key_uses_table_names_only(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="public",
        )
        customer_table = DataWarehouseTable.objects.create(
            name="customers",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "email": {"hogql": "string", "clickhouse": "String", "schema_valid": True},
            },
        )
        order_table = DataWarehouseTable.objects.create(
            name="orders",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "customer_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(name="customers", team=self.team, source=source, table=customer_table)
        ExternalDataSchema.objects.create(name="orders", team=self.team, source=source, table=order_table)

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        orders = database.get_table("orders")
        customers = database.get_table("customers")

        assert isinstance(orders.fields.get("customer"), LazyJoin)
        assert isinstance(customers.fields.get("orders"), LazyJoin)

    def test_direct_postgres_inferred_foreign_key_uses_matching_column_and_skips_self_reference(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ducklake_demo_finance",
        )
        invoice_table = DataWarehouseTable.objects.create(
            name="ducklake_demo_finance.invoices",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "invoice_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "customer_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "invoice_date": {"hogql": "date", "clickhouse": "Date", "schema_valid": True},
            },
        )
        payment_table = DataWarehouseTable.objects.create(
            name="ducklake_demo_finance.payments",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "payment_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "invoice_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "paid_at": {"hogql": "datetime", "clickhouse": "DateTime", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(
            name="ducklake_demo_finance.invoices", team=self.team, source=source, table=invoice_table
        )
        ExternalDataSchema.objects.create(
            name="ducklake_demo_finance.payments", team=self.team, source=source, table=payment_table
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        payments = database.get_table("ducklake_demo_finance.payments")
        invoices = database.get_table("ducklake_demo_finance.invoices")

        invoice_join = cast(LazyJoin, payments.fields.get("invoice"))

        assert invoice_join.from_field == ["invoice_id"]
        assert invoice_join.to_field == ["invoice_id"]
        assert invoices.fields.get("invoice") is None

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=database)

        prepare_and_print_ast(
            parse_select("SELECT invoice.invoice_id FROM ducklake_demo_finance.payments"),
            context,
            dialect="postgres",
        )

        with pytest.raises(ExposedHogQLError):
            prepare_and_print_ast(
                parse_select("SELECT invoice.invoice_id FROM ducklake_demo_finance.invoices"),
                context,
                dialect="postgres",
            )

    def test_direct_postgres_foreign_key_join_allows_user_traversal(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        user_table = DataWarehouseTable.objects.create(
            name="posthog_user",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "email": {"hogql": "string", "clickhouse": "String", "schema_valid": True},
            },
        )
        team_table = DataWarehouseTable.objects.create(
            name="posthog_team",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "user_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(name="posthog_user", team=self.team, source=source, table=user_table)
        ExternalDataSchema.objects.create(
            name="posthog_team",
            team=self.team,
            source=source,
            table=team_table,
            sync_type_config={
                "schema_metadata": {
                    "foreign_keys": [
                        {
                            "column": "user_id",
                            "target_table": "posthog_user",
                            "target_column": "id",
                        }
                    ]
                }
            },
        )

        db = Database.create_for(team=self.team, connection_id=str(source.id))
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=db)

        prepare_and_print_ast(parse_select("SELECT t.user.email FROM posthog_team t"), context, dialect="postgres")

    def test_adds_foreign_key_joins_for_non_direct_postgres_tables(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            prefix="ph3",
        )
        team_table = DataWarehouseTable.objects.create(
            name="posthog_team",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="s3://test/*",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "name": {"hogql": "string", "clickhouse": "String", "schema_valid": True},
            },
        )
        activitylog_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="s3://test/*",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "team_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(name="posthog_team", team=self.team, source=source, table=team_table)
        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=activitylog_table,
            sync_type_config={
                "schema_metadata": {
                    "foreign_keys": [
                        {
                            "column": "team_id",
                            "target_table": "posthog_team",
                            "target_column": "id",
                        }
                    ]
                }
            },
        )

        database = Database.create_for(team=self.team)
        activitylog = database.get_table("postgres.ph3.posthog_activitylog")
        team = database.get_table("postgres.ph3.posthog_team")

        assert isinstance(activitylog.fields.get("team"), LazyJoin)
        assert isinstance(team.fields.get("posthog_activitylogs"), LazyJoin)

    def test_serialize_direct_postgres_skips_foreign_key_join_when_target_table_is_missing(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        only_table = DataWarehouseTable.objects.create(
            name="activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "session_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(
            name="activitylog",
            team=self.team,
            source=source,
            table=only_table,
            sync_type_config={
                "schema_metadata": {
                    "foreign_keys": [
                        {
                            "column": "session_id",
                            "target_table": "sessions",
                            "target_column": "id",
                        }
                    ]
                }
            },
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert "activitylog" in serialized

    def test_direct_postgres_foreign_keys_ignore_invalid_metadata(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        broken_table = DataWarehouseTable.objects.create(
            name="posthog_activitylog",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={
                "id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
                "person_id": {"hogql": "integer", "clickhouse": "Int64", "schema_valid": True},
            },
        )

        ExternalDataSchema.objects.create(
            name="posthog_activitylog",
            team=self.team,
            source=source,
            table=broken_table,
            sync_type_config={
                "schema_metadata": {
                    "foreign_keys": [
                        1,
                        {"column": 2, "target_table": "posthog_user", "target_column": "id"},
                        {"column": "person(", "target_table": "posthog_user", "target_column": "id"},
                    ]
                }
            },
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert "posthog_activitylog" in serialized
        assert database.get_table("posthog_activitylog").fields.get("person") is None

    def test_serialize_direct_postgres_table_is_hidden_without_connection(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="analytics_platform_preaggregationjob",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team)
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert not database.has_table("analytics_platform_preaggregationjob")
        assert "analytics_platform_preaggregationjob" not in database.get_warehouse_table_names()
        assert "analytics_platform_preaggregationjob" not in serialized

    def test_serialize_direct_postgres_table_uses_table_name_in_direct_mode(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="analytics_platform_preaggregationjob",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert database.has_table("analytics_platform_preaggregationjob")
        assert database.has_table("numbers")
        assert not database.has_table("events")
        assert "analytics_platform_preaggregationjob" in serialized
        assert "events" not in serialized

    def test_serialize_direct_postgres_reserved_table_names_override_posthog_tables(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="events",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="persons",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"email": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert database.has_table("events")
        assert database.has_table("persons")
        assert set(serialized["events"].fields.keys()) == {"id"}
        assert set(serialized["persons"].fields.keys()) == {"email"}

    def test_direct_postgres_reserved_table_names_do_not_hide_posthog_tables_without_connection(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="events",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="persons",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"email": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team)
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert database.has_table("events")
        assert database.has_table("persons")
        assert isinstance(serialized["events"], DatabaseSchemaPostHogTable)
        assert isinstance(serialized["persons"], DatabaseSchemaPostHogTable)

    def test_serialize_direct_postgres_direct_mode_skips_disabled_tables_without_errors(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        enabled_table = DataWarehouseTable.objects.create(
            name="enabled_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        disabled_table = DataWarehouseTable.objects.create(
            name="disabled_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            name="enabled_table", team=self.team, source=source, table=enabled_table, should_sync=True
        )
        ExternalDataSchema.objects.create(
            name="disabled_table",
            team=self.team,
            source=source,
            table=disabled_table,
            should_sync=False,
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert "enabled_table" in serialized
        assert "disabled_table" not in serialized
        assert database.get_serialization_errors() == {}

    def test_direct_postgres_direct_mode_includes_tables_materialized_from_views(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="materialized_table",
            query={"kind": "HogQLQuery", "query": "SELECT event FROM events"},
        )
        DataWarehouseTable.objects.create(
            name="materialized_table",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        serialized = database.serialize(HogQLContext(team_id=self.team.pk, database=database))

        assert database.has_table("materialized_table")
        assert "materialized_table" in serialized

    def test_deleted_direct_postgres_schema_does_not_reenable_table(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        table = DataWarehouseTable.objects.create(
            name="posthog_dashboard",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            name="posthog_dashboard",
            team=self.team,
            source=source,
            table=table,
            deleted=True,
            should_sync=True,
        )
        ExternalDataSchema.objects.create(
            name="posthog_dashboard",
            team=self.team,
            source=source,
            table=table,
            should_sync=False,
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))

        assert not database.has_table("posthog_dashboard")

    def test_get_all_table_names_hides_direct_postgres_names_without_connection(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="analytics_platform_preaggregationjob",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team)
        all_table_names = database.get_all_table_names()

        assert "analytics_platform_preaggregationjob" not in all_table_names

    def test_get_all_table_names_uses_table_names_in_direct_mode(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="analytics_platform_preaggregationjob",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team, connection_id=str(source.id))
        all_table_names = database.get_all_table_names()

        assert "analytics_platform_preaggregationjob" in all_table_names
        assert "events" not in all_table_names

    def test_get_all_table_names_ignores_missing_warehouse_tables(self) -> None:
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )
        DataWarehouseTable.objects.create(
            name="customers",
            format="Parquet",
            team=self.team,
            credential=credentials,
            url_pattern="s3://test/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        database = Database.create_for(team=self.team)
        database._warehouse_table_names.append("missing_table")

        all_table_names = database.get_all_table_names()

        assert "customers" in all_table_names
        assert "missing_table" not in all_table_names

    def test_database_warehouse_resolve_field_through_linear_joins_basic_join(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )

        DataWarehouseTable.objects.create(
            team=self.team,
            name="subscriptions",
            columns={
                "id": "String",
                "created_at": "DateTime64(3, 'UTC')",
                "customer_id": "String",
            },
            credential=credentials,
            url_pattern="s3://test/*",
            format=DataWarehouseTable.TableFormat.Parquet,
        )

        DataWarehouseTable.objects.create(
            team=self.team,
            name="customers",
            columns={
                "id": "String",
                "email": "String",
            },
            credential=credentials,
            url_pattern="s3://test/*",
            format=DataWarehouseTable.TableFormat.Parquet,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="subscriptions",
            source_table_key="customer_id",
            joining_table_name="customers",
            joining_table_key="id",
            field_name="customer",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="customers",
            source_table_key="email",
            joining_table_name="events",
            joining_table_key="person.properties.email",
            field_name="events",
        )

        db = Database.create_for(team=self.team)

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        prepare_and_print_ast(
            parse_select("SELECT customer.events.distinct_id FROM subscriptions"), context, dialect="clickhouse"
        )

    def test_database_warehouse_resolve_field_through_nested_joins_basic_join(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )

        DataWarehouseTable.objects.create(
            team=self.team,
            name="subscriptions",
            columns={
                "id": "String",
                "created_at": "DateTime64(3, 'UTC')",
                "customer_id": "String",
            },
            credential=credentials,
            url_pattern="s3://test/*",
            format=DataWarehouseTable.TableFormat.Parquet,
        )

        DataWarehouseTable.objects.create(
            team=self.team,
            name="customers",
            columns={
                "id": "String",
                "email": "String",
            },
            credential=credentials,
            url_pattern="s3://test/*",
            format=DataWarehouseTable.TableFormat.Parquet,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="subscriptions",
            source_table_key="customer_id",
            joining_table_name="customers",
            joining_table_key="id",
            field_name="customer",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="subscriptions",
            source_table_key="customer.email",
            joining_table_name="events",
            joining_table_key="person.properties.email",
            field_name="events",
        )

        db = Database.create_for(team=self.team)

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        prepare_and_print_ast(
            parse_select("SELECT events.distinct_id FROM subscriptions"), context, dialect="clickhouse"
        )

    def test_database_warehouse_resolve_field_through_nested_joins_experiments_optimized_events_join(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key", access_secret="test_secret", team=self.team
        )

        DataWarehouseTable.objects.create(
            team=self.team,
            name="subscriptions",
            columns={
                "id": "String",
                "created_at": "DateTime64(3, 'UTC')",
                "customer_id": "String",
            },
            credential=credentials,
            url_pattern="s3://test/*",
            format=DataWarehouseTable.TableFormat.Parquet,
        )

        DataWarehouseTable.objects.create(
            team=self.team,
            name="customers",
            columns={
                "id": "String",
                "email": "String",
            },
            credential=credentials,
            url_pattern="s3://test/*",
            format=DataWarehouseTable.TableFormat.Parquet,
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="subscriptions",
            source_table_key="customer_id",
            joining_table_name="customers",
            joining_table_key="id",
            field_name="customer",
        )

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="subscriptions",
            source_table_key="customer.email",
            joining_table_name="events",
            joining_table_key="person.properties.email",
            field_name="events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "created_at"},
        )

        db = Database.create_for(team=self.team)

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=db,
        )

        prepare_and_print_ast(
            parse_select("SELECT events.distinct_id FROM subscriptions"), context, dialect="clickhouse"
        )

    def test_team_id_on_all_tables(self):
        db = Database.create_for(team=self.team)

        table_names = db.tables.resolve_all_table_names()
        for table_name in table_names:
            table = db.get_table(table_name)
            assert table is not None
            assert isinstance(table, Table)
            if isinstance(table, LazyTable | DANGEROUS_NoTeamIdCheckTable):
                continue
            assert "team_id" in table.fields, f"Table {table_name} must have a team_id column"

    def test_no_new_posthog_tables(self):
        existing_posthog_table_names = [
            "events",
            "groups",
            "persons",
            "person_distinct_ids",
            "person_distinct_id_overrides",
            "error_tracking_issue_fingerprint_overrides",
            "session_replay_events",
            "cohort_people",
            "static_cohort_people",
            "cohort_membership",
            "precalculated_events",
            "precalculated_person_properties",
            "log_entries",
            "query_log",
            "app_metrics",
            "console_logs_log_entries",
            "batch_export_log_entries",
            "sessions",
            "heatmaps",
            "exchange_rate",
            "document_embeddings",
            "pg_embeddings",
            "logs",
            "log_attributes",
            "logs_kafka_metrics",
            "web_pre_aggregated_stats",
            "web_pre_aggregated_bounces",
            "preaggregation_results",
            "experiment_exposures_preaggregated",
            "experiment_metric_events_preaggregated",
            "persons_revenue_analytics",
            "groups_revenue_analytics",
            "raw_session_replay_events",
            "raw_person_distinct_ids",
            "raw_persons",
            "raw_groups",
            "raw_cohort_people",
            "raw_person_distinct_id_overrides",
            "raw_error_tracking_issue_fingerprint_overrides",
            "raw_error_tracking_fingerprint_issue_state",
            "raw_sessions",
            "raw_sessions_v3",
            "raw_query_log",
            "raw_document_embeddings",
            "document_embeddings_text_embedding_3_small_1536",
            "document_embeddings_text_embedding_3_large_3072",
        ]

        current_tables = ROOT_TABLES__DO_NOT_ADD_ANY_MORE.keys()
        for table_name in current_tables:
            assert table_name in existing_posthog_table_names, (
                f"Table {table_name} should not be added to ROOT_TABLES__DO_NOT_ADD_ANY_MORE. Add the table to the `posthog` TableNode"
            )

    def test_posthog_qualified_table_names_are_resolvable(self):
        database = Database.create_for(team=self.team)

        for table_name in ROOT_TABLES__DO_NOT_ADD_ANY_MORE.keys():
            qualified_name = f"posthog.{table_name}"
            assert database.has_table(qualified_name), f"Table {qualified_name} should be resolvable"

            table = database.get_table(qualified_name)
            assert table is not None, f"Table {qualified_name} should return a valid table"

    def test_posthog_qualified_table_names_resolve_in_select(self):
        database = Database.create_for(team=self.team)
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            database=database,
            modifiers=create_default_modifiers_for_team(self.team),
        )

        prepare_and_print_ast(parse_select("select * from posthog.events"), context, dialect="clickhouse")

    def test_database_serialization_handles_invalid_sources_gracefully(self):
        """Test that serialization continues even with sources that have invalid prefixes."""
        # Create a valid source
        valid_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="valid_source_id",
            connection_id="valid_connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="valid_prefix",
        )
        valid_credentials = DataWarehouseCredential.objects.create(
            access_key="valid_key", access_secret="valid_secret", team=self.team
        )
        valid_table = DataWarehouseTable.objects.create(
            name="valid_prefixstripe_customers",
            format="Parquet",
            team=self.team,
            external_data_source=valid_source,
            credential=valid_credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name="customers",
            source=valid_source,
            table=valid_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        # Create an invalid source with characters that break HogQL identifier rules
        # Note: Stage 1 validation prevents creating new sources like this, but this tests
        # that serialization is resilient to existing invalid sources
        invalid_source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="invalid_source_id",
            connection_id="invalid_connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="invalid@prefix",  # Invalid character @
        )
        invalid_credentials = DataWarehouseCredential.objects.create(
            access_key="invalid_key", access_secret="invalid_secret", team=self.team
        )
        invalid_table = DataWarehouseTable.objects.create(
            name="invalid@prefixstripe_invoices",
            format="Parquet",
            team=self.team,
            external_data_source=invalid_source,
            credential=invalid_credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name="invoices",
            source=invalid_source,
            table=invalid_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        # Serialize database - should not crash
        database = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, database=database)
        serialized = database.serialize(context)

        # Should have tables from valid source
        assert serialized is not None
        valid_table_found = any("valid_prefix" in table_key for table_key in serialized.keys())
        assert valid_table_found, "Valid source tables should be serialized"

        # Note: The invalid source may still appear in serialized output because the @ character
        # doesn't cause get_table() to throw an exception - it just creates a malformed key.
        # The important behavior we're testing is that serialization completes without crashing,
        # allowing valid sources to work. Errors from actually using the invalid key are caught
        # when queries try to resolve it.

    @parameterized.expand(
        [
            (
                "warehouse_source_with_prefix",
                ExternalDataSource.AccessMethod.WAREHOUSE,
                "Postgres",
                "ph3",
                "ph3_postgres_analytics_platform_preaggregationjob",
                "postgres.ph3.analytics_platform_preaggregationjob",
            ),
            (
                "warehouse_source_without_prefix",
                ExternalDataSource.AccessMethod.WAREHOUSE,
                "Postgres",
                None,
                "postgres_analytics_platform_preaggregationjob",
                "postgres.analytics_platform_preaggregationjob",
            ),
            (
                "warehouse_source_with_leading_underscore_prefix",
                ExternalDataSource.AccessMethod.WAREHOUSE,
                "Postgres",
                "_ph3",
                "_ph3postgres_analytics_platform_preaggregationjob",
                "postgres.ph3.analytics_platform_preaggregationjob",
            ),
            (
                "direct_source_canonical_with_prefix",
                ExternalDataSource.AccessMethod.DIRECT,
                "Postgres",
                "ph3",
                "analytics_platform_preaggregationjob",
                "analytics_platform_preaggregationjob",
            ),
            (
                "direct_source_canonical_without_prefix",
                ExternalDataSource.AccessMethod.DIRECT,
                "Postgres",
                None,
                "analytics_platform_preaggregationjob",
                "analytics_platform_preaggregationjob",
            ),
        ]
    )
    def test_get_data_warehouse_table_name(
        self,
        _name: str,
        access_method: str,
        source_type: str,
        prefix: str | None,
        table_name: str,
        expected: str,
    ) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
            access_method=access_method,
        )

        assert get_data_warehouse_table_name(source, table_name) == expected

    def test_warehouse_join_on_persons_with_empty_columns_mid_sync(self):
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        DataWarehouseTable.objects.create(
            team=self.team,
            name="farm_size_table",
            columns={},
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="farm_size_table",
            joining_table_key="user_email",
            field_name="farm_size",
        )

        database = Database.create_for(team=self.team)
        persons = database.get_table("persons")

        assert "farm_size" in persons.fields
        assert isinstance(persons.fields["farm_size"], LazyJoin)

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=database)
        with pytest.raises(ExposedHogQLError):
            prepare_and_print_ast(
                parse_select("select person.farm_size.size_range from events"),
                context,
                dialect="clickhouse",
            )

    def test_warehouse_join_on_persons_with_partial_columns_mid_sync(self):
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="key", access_secret="secret")
        DataWarehouseTable.objects.create(
            team=self.team,
            name="farm_size_table",
            columns={
                "user_email": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            },
            credential=credential,
            url_pattern="https://bucket.s3/data/*",
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="farm_size_table",
            joining_table_key="user_email",
            field_name="farm_size",
        )

        database = Database.create_for(team=self.team)
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, database=database)

        prepare_and_print_ast(
            parse_select("select person.farm_size.user_email from events"),
            context,
            dialect="clickhouse",
        )

        with pytest.raises(ExposedHogQLError):
            prepare_and_print_ast(
                parse_select("select person.farm_size.size_range from events"),
                context,
                dialect="clickhouse",
            )

    def test_warehouse_join_skipped_when_joining_table_missing(self):
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="nonexistent_table",
            joining_table_key="email",
            field_name="ext_data",
        )

        database = Database.create_for(team=self.team)
        persons = database.get_table("persons")
        assert "ext_data" not in persons.fields

    def test_create_for_with_synthetic_user_skips_user_rbac(self):
        from posthog.auth import ProjectSecretAPIKeyUser
        from posthog.models.project_secret_api_key import ProjectSecretAPIKey

        psak = ProjectSecretAPIKey.objects.create(
            team=self.team,
            label="rbac-shortcircuit",
            secure_value="sha256$" + "f" * 64,
            scopes=["endpoint:read"],
        )
        synthetic_user = ProjectSecretAPIKeyUser(psak)

        captured: dict = {}

        def spy(team, user, user_access_control=None):
            result = _compute_system_table_access_decision(team, user, user_access_control)
            captured["result"] = result
            return result

        with patch(
            "posthog.hogql.database.database._compute_system_table_access_decision", side_effect=spy
        ) as decision:
            Database.create_for(team=self.team, user=synthetic_user)

        decision.assert_called_once()
        user_access_control, denied = captured["result"]
        # No per-user access control, but the endpoint:read scope keeps the endpoint-scoped
        # system tables; other scoped tables (e.g. feature_flags) stay hidden.
        assert user_access_control is None
        assert "data_modeling_endpoints" not in denied
        assert "data_modeling_endpoint_versions" not in denied
        assert "feature_flags" in denied

    def test_create_for_with_real_user_uses_user_rbac(self):
        captured: dict = {}

        def spy(team, user, user_access_control=None):
            result = _compute_system_table_access_decision(team, user, user_access_control)
            captured["result"] = result
            return result

        with patch(
            "posthog.hogql.database.database._compute_system_table_access_decision", side_effect=spy
        ) as decision:
            Database.create_for(team=self.team, user=self.user)

        decision.assert_called_once()
        user_access_control, _denied = captured["result"]
        # A real user gets per-user access control computed rather than the anonymous all-deny path.
        assert user_access_control is not None
