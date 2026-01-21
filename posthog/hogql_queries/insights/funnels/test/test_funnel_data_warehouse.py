from datetime import datetime
from pathlib import Path

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, snapshot_clickhouse_queries

from posthog.schema import DataWarehouseNode, DataWarehousePropertyFilter, DateRange, EventsNode, FunnelsQuery

from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.test.test_journeys import journeys_for
from posthog.types import AnyPropertyFilter

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
                "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
                "id_with_nulls": {
                    "clickhouse": "Nullable(Int64)",
                    "hogql": "IntegerDatabaseField",
                },
                "uuid": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created": {
                    "clickhouse": "DateTime64(3, 'UTC')",
                    "hogql": "DateTimeDatabaseField",
                },
                "event_name": {
                    "clickhouse": "String",
                    "hogql": "StringDatabaseField",
                },
                "properties": {
                    "clickhouse": "Nullable(String)",
                    "hogql": "StringJSONDatabaseField",
                },
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        return table.name

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse(self):
        table_name = self.setup_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
            ],
        )

        with freeze_time("2025-11-07"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

        results = response.results
        assert results[0]["count"] == 5
        assert results[1]["count"] == 1

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_and_regular_nodes(self):
        table_name = self.setup_data_warehouse()
        with freeze_time("2025-11-07"):
            _create_person(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                uuid="bc53b62b-7cc4-b3b8-0688-c6ee3dfb8539",
            )
            _create_person(
                distinct_ids=["person2"],
                team_id=self.team.pk,
                uuid="8cadb28f-1825-f158-73fa-3f228865b540",
            )
            journeys_for(
                {
                    "person1": [
                        {
                            "event": "$pageview",
                            "timestamp": datetime(2025, 11, 1, 0, 0, 0),
                        },
                    ],
                    "person2": [
                        {
                            "event": "$pageview",
                            "timestamp": datetime(2025, 11, 2, 0, 0, 0),
                        },
                    ],
                },
                self.team,
                create_people=False,
            )

            funnels_query = FunnelsQuery(
                kind="FunnelsQuery",
                dateRange=DateRange(date_from="2025-11-01"),
                series=[
                    EventsNode(event="$pageview"),
                    DataWarehouseNode(
                        id=table_name,
                        table_name=table_name,
                        id_field="uuid",
                        distinct_id_field="user_id",
                        timestamp_field="created",
                    ),
                ],
            )

            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

            results = response.results
            assert results[0]["count"] == 2
            assert results[1]["count"] == 2

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_non_uuid_id_column(self):
        table_name = self.setup_data_warehouse()

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
            response = runner.calculate()

        results = response.results
        assert results[0]["count"] == 5
        assert results[1]["count"] == 1

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_non_uuid_id_column_with_nulls(self):
        table_name = self.setup_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id_with_nulls",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id_with_nulls",
                    distinct_id_field="user_id",
                    timestamp_field="created",
                ),
            ],
        )

        # throws an error because of nulls in id field
        with freeze_time("2025-11-07"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            with pytest.raises(ExposedCHQueryError) as exc_info:
                runner.calculate()

        assert type(exc_info.value).__name__ == "CHQueryErrorFunctionThrowIfValueIsNonZero"
        assert "posthog_test_test_table_1.id_with_nulls, but a non-null value" in str(exc_info.value)

        # nulls can be filtered to make the query work
        not_null_filter: list[AnyPropertyFilter] = [
            DataWarehousePropertyFilter(key="id_with_nulls", operator="is_set", value="is_set")
        ]
        funnels_query.series[0].properties = not_null_filter
        funnels_query.series[1].properties = not_null_filter

        with freeze_time("2025-11-07"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

        results = response.results
        assert results[0]["count"] == 4
        assert results[1]["count"] == 1
