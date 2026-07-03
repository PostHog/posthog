from datetime import datetime
from pathlib import Path

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    ActorsQuery,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    DateRange,
    EventsNode,
    FunnelMathType,
    FunnelsActorsQuery,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    PropertyOperator,
    StepOrderValue,
)

from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.test.test_journeys import journeys_for
from posthog.types import AnyPropertyFilter

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.hogql_queries.insights.funnels.funnel_data_warehouse"


class TestFunnelDataWarehouse(ClickhouseTestMixin, BaseTest):
    def teardown_method(self, method) -> None:
        if getattr(self, "cleanUpDataWarehouse", None):
            self.cleanUpDataWarehouse()
        if getattr(self, "cleanUpLeadWarehouse", None):
            self.cleanUpLeadWarehouse()
        if getattr(self, "cleanUpOpportunityWarehouse", None):
            self.cleanUpOpportunityWarehouse()
        if getattr(self, "cleanUpCrossMatchWarehouseOne", None):
            self.cleanUpCrossMatchWarehouseOne()
        if getattr(self, "cleanUpCrossMatchWarehouseTwo", None):
            self.cleanUpCrossMatchWarehouseTwo()

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
                "id_decimal": {"clickhouse": "Decimal(18, 2)", "hogql": "DecimalDatabaseField"},
                "uuid": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created": {
                    "clickhouse": "DateTime64(3, 'UTC')",
                    "hogql": "DateTimeDatabaseField",
                },
                "created_epoch": {
                    "clickhouse": "Int64",
                    "hogql": "IntegerDatabaseField",
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

    def setup_salesforce_data_warehouse(self):
        lead_table, _source, _credential, _df, self.cleanUpLeadWarehouse = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "salesforce_lead_data.csv",
            table_name="salesforce_lead",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created_date": {
                    "clickhouse": "DateTime64(3, 'UTC')",
                    "hogql": "DateTimeDatabaseField",
                },
                "converted_opportunity_id": {
                    "clickhouse": "Nullable(String)",
                    "hogql": "StringDatabaseField",
                },
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        opportunity_table, _source, _credential, _df, self.cleanUpOpportunityWarehouse = (
            create_data_warehouse_table_from_csv(
                csv_path=Path(__file__).parent / "salesforce_opportunity_data.csv",
                table_name="salesforce_opportunity",
                table_columns={
                    "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                    "created_date": {
                        "clickhouse": "DateTime64(3, 'UTC')",
                        "hogql": "DateTimeDatabaseField",
                    },
                    "close_date": {"clickhouse": "Nullable(Date)", "hogql": "DateDatabaseField"},
                },
                test_bucket=TEST_BUCKET,
                team=self.team,
            )
        )

        return lead_table.name, opportunity_table.name

    def setup_salesforce_opportunity_repeated_created_date_data_warehouse(self):
        opportunity_table, _source, _credential, _df, self.cleanUpOpportunityWarehouse = (
            create_data_warehouse_table_from_csv(
                csv_path=Path(__file__).parent / "salesforce_opportunity_repeated_created_date_data.csv",
                table_name="salesforce_opportunity_repeated_created_date",
                table_columns={
                    "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                    "created_date": {
                        "clickhouse": "DateTime64(3, 'UTC')",
                        "hogql": "DateTimeDatabaseField",
                    },
                    "close_date": {"clickhouse": "Nullable(Date)", "hogql": "DateDatabaseField"},
                },
                test_bucket=TEST_BUCKET,
                team=self.team,
            )
        )

        return opportunity_table.name

    def setup_same_config_different_tables_data_warehouse(self):
        table_one, _source, _credential, _df, self.cleanUpCrossMatchWarehouseOne = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "cross_match_table_one_data.csv",
            table_name="cross_match_table_one",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created": {
                    "clickhouse": "DateTime64(3, 'UTC')",
                    "hogql": "DateTimeDatabaseField",
                },
                "step_tag": {
                    "clickhouse": "String",
                    "hogql": "StringDatabaseField",
                },
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )
        table_two, _source, _credential, _df, self.cleanUpCrossMatchWarehouseTwo = create_data_warehouse_table_from_csv(
            csv_path=Path(__file__).parent / "cross_match_table_two_data.csv",
            table_name="cross_match_table_two",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "user_id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "created": {
                    "clickhouse": "DateTime64(3, 'UTC')",
                    "hogql": "DateTimeDatabaseField",
                },
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )
        return table_one.name, table_two.name

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse(self):
        table_name = self.setup_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                ),
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    aggregation_target_field="user_id",
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
    def test_funnels_data_warehouse_integer_epoch_timestamp(self):
        # Warehouse sources like Stripe store dates as Unix-epoch integers. The funnel must
        # convert them via fromUnixTimestamp instead of raising ValidationError. created_epoch
        # mirrors the created DateTime column, so counts match test_funnels_data_warehouse.
        table_name = self.setup_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    aggregation_target_field="user_id",
                    timestamp_field="created_epoch",
                ),
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    aggregation_target_field="user_id",
                    timestamp_field="created_epoch",
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
                    FunnelsDataWarehouseNode(
                        id=table_name,
                        table_name=table_name,
                        id_field="uuid",
                        aggregation_target_field="toUUID(user_id)",
                        timestamp_field="created",
                    ),
                ],
            )

            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

            results = response.results
            assert results[0]["count"] == 2
            assert results[1]["count"] == 2

    def _string_aggregation_target_funnels_query(self, table_name: str) -> FunnelsQuery:
        return FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                EventsNode(event="$pageview"),
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="uuid",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                ),
            ],
        )

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_and_regular_nodes_string_aggregation_target(self):
        # A mixed funnel where the warehouse series aggregates by a plain string
        # column (not cast to UUID) must not fail the UNION ALL with NO_COMMON_TYPE
        # against the events series' person_id UUID.
        table_name = self.setup_data_warehouse()
        with freeze_time("2025-11-07"):
            _create_person(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                uuid="bc53b62b-7cc4-b3b8-0688-c6ee3dfb8539",
            )
            journeys_for(
                {"person1": [{"event": "$pageview", "timestamp": datetime(2025, 11, 1, 0, 0, 0)}]},
                self.team,
                create_people=False,
            )

            funnels_query = self._string_aggregation_target_funnels_query(table_name)
            response = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True).calculate()

            results = response.results
            assert results[0]["count"] == 1
            assert results[1]["count"] == 1

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_and_regular_nodes_string_aggregation_target_actors(self):
        # The actors drill-down INNER-joins person.id (UUID) against the funnel
        # actor_id, which is a String for a mixed funnel. Exercise it to confirm
        # the stringified actor id still resolves to a person.
        table_name = self.setup_data_warehouse()
        with freeze_time("2025-11-07"):
            _create_person(
                distinct_ids=["person1"],
                team_id=self.team.pk,
                uuid="bc53b62b-7cc4-b3b8-0688-c6ee3dfb8539",
            )
            journeys_for(
                {"person1": [{"event": "$pageview", "timestamp": datetime(2025, 11, 1, 0, 0, 0)}]},
                self.team,
                create_people=False,
            )

            funnels_query = self._string_aggregation_target_funnels_query(table_name)
            actors_query = ActorsQuery(
                source=FunnelsActorsQuery(source=funnels_query, funnelStep=2),
                select=["id", "person"],
            )
            response = ActorsQueryRunner(query=actors_query, team=self.team).calculate()

            actor_ids = [str(row[0]) for row in response.results]
            assert actor_ids == ["bc53b62b-7cc4-b3b8-0688-c6ee3dfb8539"]

    @snapshot_clickhouse_queries
    def test_funnels_data_warehouse_non_uuid_id_column(self):
        table_name = self.setup_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                ),
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id",
                    aggregation_target_field="user_id",
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

    def test_funnels_data_warehouse_decimal_id_column(self):
        table_name = self.setup_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id_decimal",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                ),
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id_decimal",
                    aggregation_target_field="user_id",
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
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id_with_nulls",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                ),
                FunnelsDataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    id_field="id_with_nulls",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                ),
            ],
        )
        assert isinstance(funnels_query.series[0], FunnelsDataWarehouseNode)  # for mypy
        assert isinstance(funnels_query.series[1], FunnelsDataWarehouseNode)  # for mypy

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

    def test_funnels_event_step_filtering_on_warehouse_person_property(self):
        table_name = self.setup_data_warehouse()

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=table_name,
            joining_table_key="user_id",
            field_name=table_name,
        )

        matching_user_id = "bc53b62b-7cc4-b3b8-0688-c6ee3dfb8539"
        non_matching_user_id = "8cadb28f-1825-f158-73fa-3f228865b540"

        _create_person(
            distinct_ids=["person1"],
            team_id=self.team.pk,
            properties={"email": matching_user_id},
        )
        _create_person(
            distinct_ids=["person2"],
            team_id=self.team.pk,
            properties={"email": non_matching_user_id},
        )

        _create_event(team=self.team, event="$pageview", distinct_id="person1", timestamp="2025-11-04T10:00:00Z")
        _create_event(team=self.team, event="$checkout", distinct_id="person1", timestamp="2025-11-04T11:00:00Z")
        _create_event(team=self.team, event="$pageview", distinct_id="person2", timestamp="2025-11-05T10:00:00Z")
        _create_event(team=self.team, event="$checkout", distinct_id="person2", timestamp="2025-11-05T11:00:00Z")
        flush_persons_and_events()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="all"),
            series=[
                EventsNode(
                    event="$pageview",
                    properties=[
                        DataWarehousePersonPropertyFilter(
                            key=f"{table_name}.event_name",
                            operator=PropertyOperator.EXACT,
                            value="payment_succeeded",
                        )
                    ],
                ),
                EventsNode(event="$checkout"),
            ],
        )

        response = FunnelsQueryRunner(
            query=funnels_query,
            team=self.team,
        ).calculate()

        results = response.results
        assert results[0]["count"] == 1
        assert results[1]["count"] == 1

    @snapshot_clickhouse_queries
    def test_funnels_salesforce_lead_to_opportunity(self):
        lead_table_name, opportunity_table_name = self.setup_salesforce_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2024-05-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=lead_table_name,
                    table_name=lead_table_name,
                    id_field="id",
                    aggregation_target_field="coalesce(converted_opportunity_id, id)",
                    timestamp_field="created_date",
                ),
                FunnelsDataWarehouseNode(
                    id=opportunity_table_name,
                    table_name=opportunity_table_name,
                    id_field="id",
                    aggregation_target_field="id",
                    timestamp_field="created_date",
                ),
                FunnelsDataWarehouseNode(
                    id=opportunity_table_name,
                    table_name=opportunity_table_name,
                    id_field="id",
                    aggregation_target_field="id",
                    timestamp_field="close_date",
                ),
            ],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=30),
        )

        with freeze_time("2024-06-30"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

        results = response.results
        assert results[0]["count"] == 5
        assert results[1]["count"] == 3
        assert results[2]["count"] == 2

    def test_funnels_same_data_warehouse_table_different_timestamp_fields(self):
        """
        Steps with the same table but different configurations (in this example, a different timestamp
        field) must not cross-match. Repeated created_date rows with null close_date should never count
        as completing step 2.
        """
        opportunity_table_name = self.setup_salesforce_opportunity_repeated_created_date_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2024-05-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=opportunity_table_name,
                    table_name=opportunity_table_name,
                    id_field="id",
                    aggregation_target_field="id",
                    timestamp_field="created_date",
                ),
                FunnelsDataWarehouseNode(
                    id=opportunity_table_name,
                    table_name=opportunity_table_name,
                    id_field="id",
                    aggregation_target_field="id",
                    timestamp_field="close_date",
                ),
            ],
            funnelsFilter=FunnelsFilter(funnelWindowInterval=30, funnelOrderType=StepOrderValue.UNORDERED),
        )

        with freeze_time("2024-06-30"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

        results = response.results
        assert results[0]["count"] == 2
        assert results[1]["count"] == 0

    def test_funnels_different_tables_same_config_do_not_share_step_filters(self):
        table_one_name, table_two_name = self.setup_same_config_different_tables_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=table_one_name,
                    table_name=table_one_name,
                    id_field="id",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                    properties=[DataWarehousePropertyFilter(key="step_tag", value="go", operator="exact")],
                ),
                FunnelsDataWarehouseNode(
                    id=table_two_name,
                    table_name=table_two_name,
                    id_field="id",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                    properties=[],
                ),
            ],
            funnelsFilter=FunnelsFilter(funnelOrderType=StepOrderValue.UNORDERED),
        )

        with freeze_time("2025-11-07"):
            runner = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True)
            response = runner.calculate()

        results = response.results
        assert results[0]["count"] == 2
        assert results[1]["count"] == 2

    def test_funnels_data_warehouse_first_time_for_user(self):
        # cf6a408b's first-ever row is 2025-11-02, before the 2025-11-03 window start, so
        # first-time-for-user must exclude that user from step 0 while a plain (total) funnel
        # still counts their later 2025-11-06 row.
        table_name = self.setup_data_warehouse()

        def _query(first_time: bool) -> FunnelsQuery:
            node = FunnelsDataWarehouseNode(
                id=table_name,
                table_name=table_name,
                id_field="uuid",
                aggregation_target_field="user_id",
                timestamp_field="created",
                math=FunnelMathType.FIRST_TIME_FOR_USER if first_time else None,
            )
            return FunnelsQuery(
                kind="FunnelsQuery",
                dateRange=DateRange(date_from="2025-11-03"),
                series=[node, node],
            )

        with freeze_time("2025-11-07"):
            total = FunnelsQueryRunner(query=_query(False), team=self.team, just_summarize=True).calculate()
            first_time = FunnelsQueryRunner(query=_query(True), team=self.team, just_summarize=True).calculate()

        # 4 distinct users have a row in the window; first-time-for-user drops cf6a408b,
        # whose first-ever occurrence falls before the window.
        assert total.results[0]["count"] == 4
        assert first_time.results[0]["count"] == 3

    def test_funnels_first_time_for_user_two_different_tables(self):
        table_one_name, table_two_name = self.setup_same_config_different_tables_data_warehouse()

        funnels_query = FunnelsQuery(
            kind="FunnelsQuery",
            dateRange=DateRange(date_from="2025-11-01"),
            series=[
                FunnelsDataWarehouseNode(
                    id=table_one_name,
                    table_name=table_one_name,
                    id_field="id",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                    math=FunnelMathType.FIRST_TIME_FOR_USER,
                ),
                FunnelsDataWarehouseNode(
                    id=table_two_name,
                    table_name=table_two_name,
                    id_field="id",
                    aggregation_target_field="user_id",
                    timestamp_field="created",
                    math=FunnelMathType.FIRST_TIME_FOR_USER,
                ),
            ],
            funnelsFilter=FunnelsFilter(funnelOrderType=StepOrderValue.UNORDERED),
        )

        with freeze_time("2025-11-07"):
            response = FunnelsQueryRunner(query=funnels_query, team=self.team, just_summarize=True).calculate()

        # Each user appears once per table, so first-time-for-user leaves the counts unchanged —
        # but the funnel must still run with an independent first-time subquery per table
        # (a config bleed between the two tables would error or miscount).
        results = response.results
        assert results[0]["count"] == 2
        assert results[1]["count"] == 2
