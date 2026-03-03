from types import SimpleNamespace
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import DatabaseSchemaQuery, DatabaseSchemaQueryResponse

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
            "selected_table": SimpleNamespace(
                type="data_warehouse", source=SimpleNamespace(id=selected_source.source_id)
            ),
            "other_table": SimpleNamespace(type="data_warehouse", source=SimpleNamespace(id=other_source.source_id)),
            "events": SimpleNamespace(type="events", source=None),
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

        mock_database.serialize.return_value["selected_table_2"] = SimpleNamespace(
            type="data_warehouse", source=SimpleNamespace(id=selected_source.source_id)
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
