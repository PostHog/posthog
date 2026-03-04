from types import SimpleNamespace
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaPostHogTable,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaSource,
)

from posthog.api.services.query import _source_id_for_connection, process_query_model

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestQueryService(APIBaseTest):
    def test_source_id_for_connection_uses_source_id(self):
        source = ExternalDataSource.objects.create(
            source_id="upstream-source",
            connection_id="selected-connection",
            destination_id="destination",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        result = _source_id_for_connection(self.team, "selected-connection")

        self.assertEqual(result, source.source_id)

    def test_source_id_for_connection_supports_external_data_source_uuid(self):
        source = ExternalDataSource.objects.create(
            source_id="upstream-source",
            connection_id="selected-connection",
            destination_id="destination",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        result = _source_id_for_connection(self.team, str(source.id))

        self.assertEqual(result, source.source_id)

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.Database.create_for")
    def test_database_schema_query_filters_tables_to_selected_connection(
        self,
        mock_create_for: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        other_source = ExternalDataSource.objects.create(
            source_id="other-upstream-source",
            connection_id="other-connection",
            destination_id="destination-2",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.HUBSPOT,
        )

        mock_database = MagicMock()
        mock_database.serialize.return_value = {
            "selected_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="selected_table_id",
                name="selected_table",
                url_pattern="direct://postgres",
                source=DatabaseSchemaSource(
                    id=selected_source.source_id,
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            ),
            "other_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="other_table_id",
                name="other_table",
                url_pattern="direct://postgres",
                source=DatabaseSchemaSource(
                    id=other_source.source_id,
                    status=other_source.status,
                    source_type=other_source.source_type,
                    access_method=other_source.access_method,
                    prefix=other_source.prefix or "",
                ),
            ),
            "events": DatabaseSchemaPostHogTable(fields={}, id="events", name="events"),
        }
        mock_create_for.return_value = mock_database

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
        join_for_other_source = SimpleNamespace(
            id="2",
            source_table_name="selected_table",
            source_table_key="selected_table.id",
            joining_table_name="other_table",
            joining_table_key="other_table.id",
            field_name="cross_source_join",
            configuration={},
            created_at=other_source.created_at,
        )
        mock_joins = [join_for_selected_source, join_for_other_source]
        mock_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_joins
        mock_join_filter.return_value = mock_join_queryset

        mock_database.serialize.return_value["selected_table_2"] = DatabaseSchemaDataWarehouseTable(
            fields={},
            format="Parquet",
            id="selected_table_2_id",
            name="selected_table_2",
            url_pattern="direct://postgres",
            source=DatabaseSchemaSource(
                id=selected_source.source_id,
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
                DatabaseSchemaQuery(connectionId="selected-connection"),
            ),
        )

        self.assertIsInstance(response, DatabaseSchemaQueryResponse)
        self.assertEqual(set(response.tables.keys()), {"selected_table", "selected_table_2"})
        self.assertEqual(len(response.joins), 1)
        self.assertEqual(response.joins[0].field_name, "selected_join")

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.Database.create_for")
    def test_database_schema_query_without_connection_excludes_direct_sources(
        self,
        mock_create_for: MagicMock,
        mock_join_filter: MagicMock,
    ):
        mock_database = MagicMock()
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
            "direct_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="direct_table_id",
                name="direct_table",
                url_pattern="direct://postgres",
                source=DatabaseSchemaSource(
                    id="direct-source",
                    status="Completed",
                    source_type="Postgres",
                    access_method="direct",
                    prefix="ph3",
                ),
            ),
            "events": DatabaseSchemaPostHogTable(fields={}, id="events", name="events"),
        }
        mock_create_for.return_value = mock_database
        mock_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = []
        mock_join_filter.return_value = mock_join_queryset

        response = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))

        self.assertEqual(set(response.tables.keys()), {"warehouse_table", "events"})
