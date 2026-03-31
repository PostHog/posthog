from types import SimpleNamespace
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaPostHogTable,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaSchema,
    DatabaseSchemaSource,
    DatabaseSerializedFieldType,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
)

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.postgres_table import PostgresTable

from posthog.api.services.query import process_query_model

from products.data_warehouse.backend.models import DataWarehouseCredential, DataWarehouseTable
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestQueryService(APIBaseTest):
    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_filters_tables_to_selected_connection(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "selected_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="selected_table_id",
                name="selected_table",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-selected-1",
                    name="selected_table",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            )
        }
        mock_resolve_database_for_connection.return_value = (selected_source, mock_database)

        join_for_selected_source = SimpleNamespace(
            id="1",
            source_table_name="selected_table",
            source_table_key="selected_table.id",
            joining_table_name="selected_table_2",
            joining_table_key="selected_table_2.id",
            field_name="selected_join",
            configuration={},
            created_at=selected_source.created_at,
        )
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([join_for_selected_source])
        mock_join_filter.return_value = mock_join_queryset

        mock_database.serialize.return_value["selected_table_2"] = DatabaseSchemaDataWarehouseTable(
            fields={},
            format="Parquet",
            id="selected_table_2_id",
            name="selected_table_2",
            url_pattern="direct://postgres",
            schema=DatabaseSchemaSchema(
                id="schema-selected-2",
                name="selected_table_2",
                should_sync=True,
                incremental=False,
            ),
            source=DatabaseSchemaSource(
                id=str(selected_source.id),
                status=selected_source.status,
                source_type=selected_source.source_type,
                access_method=selected_source.access_method,
                prefix=selected_source.prefix or "",
            ),
        )

        response = cast(
            DatabaseSchemaQueryResponse,
            process_query_model(
                self.team,
                DatabaseSchemaQuery(connectionId=str(selected_source.id)),
            ),
        )

        self.assertIsInstance(response, DatabaseSchemaQueryResponse)
        self.assertEqual(set(response.tables.keys()), {"selected_table", "selected_table_2"})
        self.assertEqual(len(response.joins), 1)
        self.assertEqual(response.joins[0].field_name, "selected_join")
        mock_filtered_join_queryset.filter.assert_called_once_with(
            source_table_name__in={"selected_table", "selected_table_2"},
            joining_table_name__in={"selected_table", "selected_table_2"},
        )

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_preserves_serialized_join_fields(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "selected_table": DatabaseSchemaDataWarehouseTable(
                fields={
                    "selected_join": DatabaseSchemaField(
                        name="selected_join",
                        hogql_value="selected_join",
                        type=DatabaseSerializedFieldType.LAZY_TABLE,
                        schema_valid=True,
                        table="selected_table_2",
                        fields=["id", "email"],
                        id="selected_join",
                    )
                },
                format="Parquet",
                id="selected_table_id",
                name="selected_table",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-selected",
                    name="selected_table",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            ),
            "selected_table_2": DatabaseSchemaDataWarehouseTable(
                fields={
                    "id": DatabaseSchemaField(
                        name="id",
                        hogql_value="id",
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=True,
                    ),
                    "email": DatabaseSchemaField(
                        name="email",
                        hogql_value="email",
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=True,
                    ),
                },
                format="Parquet",
                id="selected_table_2_id",
                name="selected_table_2",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-selected-2",
                    name="selected_table_2",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            ),
        }
        mock_resolve_database_for_connection.return_value = (selected_source, mock_database)

        join_for_selected_source = SimpleNamespace(
            id="1",
            source_table_name="selected_table",
            source_table_key="selected_table.id",
            joining_table_name="selected_table_2",
            joining_table_key="selected_table_2.id",
            field_name="selected_join",
            configuration={},
            created_at=selected_source.created_at,
        )
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([join_for_selected_source])
        mock_join_filter.return_value = mock_join_queryset

        response = cast(
            DatabaseSchemaQueryResponse,
            process_query_model(
                self.team,
                DatabaseSchemaQuery(connectionId=str(selected_source.id)),
            ),
        )

        source_table = cast(DatabaseSchemaDataWarehouseTable, response.tables["selected_table"])
        assert "selected_join" in source_table.fields
        join_field = source_table.fields["selected_join"]
        assert join_field.type == DatabaseSerializedFieldType.LAZY_TABLE
        assert join_field.table == "selected_table_2"
        assert join_field.fields == ["id", "email"]

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_direct_connection_only_returns_queriable_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "queriable_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="queriable_table_id",
                name="queriable_table",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-queriable",
                    name="queriable_table",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            )
        }
        mock_resolve_database_for_connection.return_value = (selected_source, mock_database)
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([])
        mock_join_filter.return_value = mock_join_queryset

        response = cast(
            DatabaseSchemaQueryResponse,
            process_query_model(
                self.team,
                DatabaseSchemaQuery(connectionId=str(selected_source.id)),
            ),
        )

        self.assertEqual(set(response.tables.keys()), {"queriable_table"})
        mock_filtered_join_queryset.filter.assert_called_once_with(
            source_table_name__in={"queriable_table"},
            joining_table_name__in={"queriable_table"},
        )

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_without_connection_hides_direct_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        database = Database()
        database.tables.add_child(
            TableNode(
                name="events",
                table=PostgresTable(name="events", fields={}, postgres_table_name="events"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database.tables.add_child(
            TableNode(
                name="direct_table",
                table=PostgresTable(
                    name="direct_table",
                    fields={},
                    postgres_table_name="posthog_dashboard",
                ),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database._warehouse_table_names = ["direct_table"]
        database._direct_access_warehouse_table_names = {"direct_table"}
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (None, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("events"))
            self.assertFalse(database_arg.has_table("direct_table"))
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
            ),
        )

        self.assertEqual(response, HogQLAutocompleteResponse(suggestions=[], incomplete_list=False))

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_with_direct_connection_hides_posthog_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        database = Database()
        database.tables.add_child(
            TableNode(
                name="posthog_dashboard",
                table=PostgresTable(name="posthog_dashboard", fields={}, postgres_table_name="posthog_dashboard"),
            )
        )
        database._connection_id = str(source.id)
        database._warehouse_table_names = ["posthog_dashboard"]
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (source, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("posthog_dashboard"))
            self.assertFalse(database_arg.has_table("events"))
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            ),
        )

        self.assertEqual(response, HogQLAutocompleteResponse(suggestions=[], incomplete_list=False))
        self.assertEqual(mock_resolve_database_for_connection.call_args.kwargs["user"], None)
        self.assertEqual(mock_get_hogql_autocomplete.call_args.kwargs["user"], None)

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_with_direct_connection_filters_other_source_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        database = Database()
        database.tables.add_child(
            TableNode(
                name="selected_table",
                table=PostgresTable(name="selected_table", fields={}, postgres_table_name="selected_table"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database._connection_id = str(selected_source.id)
        database._warehouse_table_names = ["selected_table"]
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (selected_source, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("selected_table"))
            self.assertFalse(database_arg.has_table("other_table"))
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(selected_source.id),
            ),
        )

        self.assertEqual(response, HogQLAutocompleteResponse(suggestions=[], incomplete_list=False))
        self.assertEqual(mock_resolve_database_for_connection.call_args.kwargs["user"], None)
        self.assertEqual(mock_get_hogql_autocomplete.call_args.kwargs["user"], None)

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_with_direct_connection_exposes_selected_tables_only(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        database = Database()
        database.tables.add_child(
            TableNode(
                name="selected_table",
                table=PostgresTable(name="selected_table", fields={}, postgres_table_name="selected_table"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database.tables.add_child(
            TableNode(
                name="events",
                table=PostgresTable(name="events", fields={}, postgres_table_name="events"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database._connection_id = str(source.id)
        database._warehouse_table_names = ["selected_table"]
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (source, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("selected_table"))
            self.assertFalse(database_arg.has_table("events"))
            self.assertEqual(database_arg.get_all_table_names(), ["selected_table"])
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            ),
        )

        self.assertEqual(response, HogQLAutocompleteResponse(suggestions=[], incomplete_list=False))

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_passes_user_context(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        database = Database()
        mock_resolve_database_for_connection.return_value = (source, database)
        mock_get_hogql_autocomplete.return_value = HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            ),
            user=self.user,
        )

        self.assertEqual(mock_resolve_database_for_connection.call_args.kwargs["user"], self.user)
        self.assertEqual(mock_get_hogql_autocomplete.call_args.kwargs["user"], self.user)

    @parameterized.expand(
        [
            ("autocomplete", HogQLAutocomplete),
            ("schema", DatabaseSchemaQuery),
        ]
    )
    def test_query_service_rejects_soft_deleted_connection_ids(self, _label: str, query_cls):
        query: HogQLAutocomplete | DatabaseSchemaQuery
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            deleted=True,
        )

        if query_cls is HogQLAutocomplete:
            query = HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            )
        else:
            query = DatabaseSchemaQuery(connectionId=str(source.id))

        with self.assertRaises(ValidationError) as error:
            process_query_model(self.team, query)

        self.assertEqual(cast(list[str], error.exception.detail)[0], "Invalid connectionId for this team")

    @parameterized.expand(
        [
            ("autocomplete", HogQLAutocomplete),
            ("schema", DatabaseSchemaQuery),
        ]
    )
    def test_query_service_rejects_non_direct_connection_ids(self, _label: str, query_cls):
        query: HogQLAutocomplete | DatabaseSchemaQuery
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        )

        if query_cls is HogQLAutocomplete:
            query = HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            )
        else:
            query = DatabaseSchemaQuery(connectionId=str(source.id))

        with self.assertRaises(ValidationError) as error:
            process_query_model(self.team, query)

        self.assertEqual(cast(list[str], error.exception.detail)[0], "Invalid connectionId for this team")

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_without_connection_excludes_direct_sources(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "warehouse_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="warehouse_table_id",
                name="warehouse_table",
                url_pattern="s3://bucket/path",
                source=DatabaseSchemaSource(
                    id="warehouse-source",
                    status="Completed",
                    source_type="Stripe",
                    access_method="warehouse",
                    prefix="stripe",
                ),
            ),
            "events": DatabaseSchemaPostHogTable(fields={}, id="events", name="events"),
        }
        mock_resolve_database_for_connection.return_value = (None, mock_database)
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        dangling_direct_join = SimpleNamespace(
            id="1",
            source_table_name="direct_table",
            source_table_key="direct_table.id",
            joining_table_name="warehouse_table",
            joining_table_key="warehouse_table.id",
            field_name="direct_join",
            configuration={},
            created_at=self.team.created_at,
        )
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([dangling_direct_join])
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value.iterator.return_value = iter([])
        mock_join_filter.return_value = mock_join_queryset

        response = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))

        self.assertEqual(set(response.tables.keys()), {"warehouse_table", "events"})
        self.assertEqual(response.joins, [])
        mock_filtered_join_queryset.filter.assert_called_once_with(
            source_table_name__in={"warehouse_table", "events"},
            joining_table_name__in={"warehouse_table", "events"},
        )

    def test_database_schema_query_without_connection_preserves_posthog_tables_with_direct_name_collisions(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key",
            access_secret="test_secret",
            team=self.team,
        )
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
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

        response = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))

        self.assertIsInstance(response.tables["events"], DatabaseSchemaPostHogTable)
        self.assertIsInstance(response.tables["persons"], DatabaseSchemaPostHogTable)
