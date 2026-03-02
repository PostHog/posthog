from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import DatabaseSchemaQuery, DatabaseSchemaQueryResponse

from posthog.api.services.query import _source_id_for_connection, process_query_model

from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType


class TestQueryService(APIBaseTest):
    def test_source_id_for_connection_uses_external_data_source_id(self):
        source = ExternalDataSource.objects.create(
            source_id="upstream-source",
            connection_id="selected-connection",
            destination_id="destination",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )

        result = _source_id_for_connection(self.team, "selected-connection")

        self.assertEqual(result, str(source.id))

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
                type="data_warehouse", source=SimpleNamespace(id=str(selected_source.id))
            ),
            "other_table": SimpleNamespace(type="data_warehouse", source=SimpleNamespace(id=str(other_source.id))),
            "events": SimpleNamespace(type="events", source=None),
        }
        mock_create_for.return_value = mock_database

        mock_joins = MagicMock()
        mock_joins.exclude.return_value = []
        mock_join_filter.return_value = mock_joins

        response = process_query_model(
            self.team,
            DatabaseSchemaQuery(connectionId="selected-connection"),
        )

        self.assertIsInstance(response, DatabaseSchemaQueryResponse)
        self.assertEqual(set(response.tables.keys()), {"selected_table"})
