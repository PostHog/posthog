from pathlib import Path

from freezegun import freeze_time
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries


from posthog.schema import (
    DataWarehouseNode,
    DateRange,
    EventsNode,
    FunnelsQuery,
)

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv


TEST_BUCKET = "test_storage_bucket-posthog.hogql_queries.insights.funnels.funnel_data_warehouse"


class TestFunnelDataWarehouse(ClickhouseTestMixin, BaseTest):
    def teardown_method(self, method) -> None:
        if getattr(self, "cleanUpDataWarehouse", None):
            self.cleanUpDataWarehouse()

    def setup_data_warehouse(self):
        table, _source, _credential, _df, self.cleanUpDataWarehouse = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "funnels_data.csv",
            table_name="test_table_1",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
                "event_name": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "properties": {"hogql": "StringJSONDatabaseField", "clickhouse": "Nullable(String)"},
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        return table.name

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse(self):
        table_name = self.setup_data_warehouse()
        # events = [
        #     {
        #         "event": "step one",
        #         "timestamp": datetime(2021, 5, 1, 0, 0, 0),
        #     },
        #     # Exclusion happens after time expires
        #     {
        #         "event": "exclusion",
        #         "timestamp": datetime(2021, 5, 1, 0, 0, 11),
        #     },
        #     {
        #         "event": "step two",
        #         "timestamp": datetime(2021, 5, 1, 0, 0, 12),
        #     },
        # ]
        # journeys_for(
        #     {
        #         "user_one": events,
        #     },
        #     self.team,
        # )

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
            ],
        )

        with freeze_time("2025-11-07"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            result = runner.calculate()

        # self.assertTrue(result.results.isUdf)

        # assert response.columns is not None
        # assert set(response.columns).issubset({"date", "total"})
        # assert response.results[0][1] == [1, 1, 1, 1, 0, 0, 0]

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_and_regular_nodes(self):
        table_name = self.setup_data_warehouse()
        # events = [
        #     {
        #         "event": "step one",
        #         "timestamp": datetime(2021, 5, 1, 0, 0, 0),
        #     },
        #     # Exclusion happens after time expires
        #     {
        #         "event": "exclusion",
        #         "timestamp": datetime(2021, 5, 1, 0, 0, 11),
        #     },
        #     {
        #         "event": "step two",
        #         "timestamp": datetime(2021, 5, 1, 0, 0, 12),
        #     },
        # ]
        # journeys_for(
        #     {
        #         "user_one": events,
        #     },
        #     self.team,
        # )

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                EventsNode(event="$pageview"),
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
            ],
        )

        with freeze_time("2025-11-07"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            result = runner.calculate()

        # self.assertTrue(result.results.isUdf)

        # assert response.columns is not None
        # assert set(response.columns).issubset({"date", "total"})
        # assert response.results[0][1] == [1, 1, 1, 1, 0, 0, 0]
