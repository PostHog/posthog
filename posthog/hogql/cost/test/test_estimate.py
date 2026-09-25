import dataclasses
from datetime import UTC, datetime
from typing import Literal, cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogLanguage, HogQLMetadata

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.cost.estimate import DEFAULT_RANGE_DAYS, ScanEstimate, TableScanEstimate, estimate_scan
from posthog.hogql.cost.statistics import EventVolume, FixedStatisticsProvider
from posthog.hogql.database.database import Database
from posthog.hogql.metadata import get_hogql_metadata
from posthog.hogql.parser import parse_select
from posthog.hogql.property_metadata import MaterializedColumnsByTable, PropertyMetadata
from posthog.hogql.resolver import resolve_types

from products.data_warehouse.backend.facade.sources import (
    DIRECT_ESTIMATED_ROW_COUNT_OPTION,
    DIRECT_MYSQL_SCHEMA_OPTION,
    DIRECT_MYSQL_TABLE_OPTION,
    DIRECT_MYSQL_URL_PATTERN,
    DIRECT_POSTGRES_SCHEMA_OPTION,
    DIRECT_POSTGRES_TABLE_OPTION,
    DIRECT_POSTGRES_URL_PATTERN,
)
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSource,
)

from ee.clickhouse.materialized_columns.columns import MaterializedColumn, MaterializedColumnDetails

NOW = datetime(2026, 9, 11, tzinfo=UTC)
# 100k events per day, 60% pageviews, 40% signups.
VOLUME = EventVolume(total=1_000_000, by_event={"$pageview": 600_000, "signup": 400_000}, days=10)
WHOLE_TABLE_ROWS = 100_000 * DEFAULT_RANGE_DAYS


def _events_table(
    *, rows: int, days: float, events: tuple[str, ...], time_range: Literal["bounded", "open"], name: str = "events"
) -> TableScanEstimate:
    return TableScanEstimate(
        name=name, source="events", precision="measured", rows=rows, days=days, events=events, time_range=time_range
    )


def _materialized(property_name: str, *, minmax: bool = False, bloom: bool = False) -> MaterializedColumn:
    return MaterializedColumn(
        name=f"mat_{property_name}",
        details=MaterializedColumnDetails(table_column="properties", property_name=property_name, is_disabled=False),
        is_nullable=False,
        has_minmax_index=minmax,
        has_bloom_filter_index=bloom,
    )


# order_id and plan have a bloom filter, duration has a minmax index, and $browser is read from the JSON blob.
MATERIALIZED_COLUMNS: MaterializedColumnsByTable = {
    "events": {
        ("order_id", "properties"): _materialized("order_id", bloom=True),
        ("plan", "properties"): _materialized("plan", bloom=True),
        ("uncounted", "properties"): _materialized("uncounted", bloom=True),
        ("duration", "properties"): _materialized("duration", minmax=True),
    }
}


class TestEstimateEventsScan(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.context = HogQLContext(
            database=Database.create_for(team=self.team), team_id=self.team.pk, enable_select_queries=True
        )
        self.context.property_metadata = PropertyMetadata(
            event_properties={}, materialized_columns=lambda: MATERIALIZED_COLUMNS
        )
        self.provider = FixedStatisticsProvider(
            event_volume={self.team.pk: VOLUME},
            property_ndv={(self.team.pk, "order_id"): 10_000_000, (self.team.pk, "plan"): 50},
        )

    def _with_table_rows(self, **rows: int) -> None:
        self.provider = FixedStatisticsProvider(
            event_volume={self.team.pk: VOLUME}, table_rows={(self.team.pk, table): n for table, n in rows.items()}
        )

    def _with_sessions_per_day(self, per_day: float) -> None:
        # Which physical sessions table a team reads depends on a modifier, so the rate is offered for every one.
        self.provider = FixedStatisticsProvider(
            event_volume={self.team.pk: VOLUME},
            daily_rows={(self.team.pk, table): per_day for table in ("sessions", "raw_sessions", "raw_sessions_v3")},
        )

    def _estimate(self, sql: str) -> ScanEstimate | None:
        node = cast(ast.SelectQuery, resolve_types(parse_select(sql), self.context, dialect="clickhouse"))
        return estimate_scan(node, self.context, self.provider, now=NOW)

    def _events(self, sql: str) -> TableScanEstimate:
        estimate = self._estimate(sql)
        assert estimate is not None
        [table] = estimate.tables
        assert table.rows == estimate.rows
        # The per-filter shares are the explain's concern; these cases assert the rows they produce.
        return dataclasses.replace(table, filters=())

    @parameterized.expand(
        [
            (
                "bounded_range_and_one_event",
                "SELECT count() FROM events WHERE timestamp > '2026-08-12' AND timestamp < '2026-09-11' AND event = '$pageview'",
                _events_table(rows=1_800_000, days=30.0, events=("$pageview",), time_range="bounded"),
            ),
            (
                "relative_lower_bound_only",
                "SELECT count() FROM events WHERE timestamp > now() - interval 7 day",
                _events_table(rows=700_000, days=7.0, events=(), time_range="open"),
            ),
            (
                "aliased_table_and_in_list_with_an_unseen_event",
                "SELECT count() FROM events AS e WHERE e.event IN ('signup', 'never_seen')",
                _events_table(
                    rows=14_600_000, days=float(DEFAULT_RANGE_DAYS), events=("never_seen", "signup"), time_range="open"
                ),
            ),
            (
                "flipped_comparison_and_datetime_literal",
                "SELECT count() FROM events WHERE '2026-09-01 00:00:00' <= timestamp AND timestamp <= '2026-09-03 12:00:00'",
                _events_table(rows=250_000, days=2.5, events=(), time_range="bounded"),
            ),
            (
                "subquery_source_keeps_the_inner_narrowing",
                "SELECT count() FROM (SELECT event FROM events WHERE event = 'signup' AND timestamp > now() - interval 30 day AND timestamp < now())",
                _events_table(rows=1_200_000, days=30.0, events=("signup",), time_range="bounded"),
            ),
            (
                "cte_is_followed",
                "WITH pageviews AS (SELECT event FROM events WHERE event = '$pageview') SELECT count() FROM pageviews",
                _events_table(
                    rows=21_900_000, days=float(DEFAULT_RANGE_DAYS), events=("$pageview",), time_range="open"
                ),
            ),
            (
                "indexed_equality_on_a_high_cardinality_property_reads_few_granules",
                "SELECT count() FROM events WHERE properties.order_id = 'a1'",
                _events_table(rows=29_888, days=float(DEFAULT_RANGE_DAYS), events=(), time_range="open"),
            ),
            (
                "indexed_in_list_scales_with_the_number_of_values",
                "SELECT count() FROM events WHERE properties.order_id IN ('a1', 'a2', 'a3')",
                _events_table(rows=89_592, days=float(DEFAULT_RANGE_DAYS), events=(), time_range="open"),
            ),
            (
                "indexed_equality_on_a_low_cardinality_property_still_reads_every_granule",
                "SELECT count() FROM events WHERE properties.plan = 'free'",
                _events_table(rows=WHOLE_TABLE_ROWS, days=float(DEFAULT_RANGE_DAYS), events=(), time_range="open"),
            ),
            (
                "two_indexed_filters_use_the_more_selective_one",
                "SELECT count() FROM events WHERE properties.plan = 'free' AND properties.order_id = 'a1'",
                _events_table(rows=29_888, days=float(DEFAULT_RANGE_DAYS), events=(), time_range="open"),
            ),
        ]
    )
    def test_estimates_events_scans(self, _name, sql, expected):
        assert self._events(sql) == expected

    @parameterized.expand(
        [
            (
                "union_all_lists_and_sums_both_branches",
                "SELECT event FROM events WHERE event = 'signup' UNION ALL SELECT event FROM events WHERE event = '$pageview'",
                36_500_000,
                [(14_600_000, ("signup",)), (21_900_000, ("$pageview",))],
            ),
            (
                "self_join_narrows_each_side_by_its_own_alias",
                "SELECT count() FROM events a JOIN events b ON a.distinct_id = b.distinct_id"
                " WHERE a.timestamp > now() - interval 10 day AND a.timestamp < now() AND b.event = 'signup'",
                15_600_000,
                [(1_000_000, ()), (14_600_000, ("signup",))],
            ),
        ]
    )
    def test_several_events_scans_get_one_entry_each(self, _name, sql, expected_rows, expected_tables):
        estimate = self._estimate(sql)

        assert estimate is not None
        assert estimate.rows == expected_rows
        assert [(table.rows, table.events) for table in estimate.tables] == expected_tables

    @parameterized.expand(
        [
            ("indexed_filter_without_a_distinct_count", "SELECT count() FROM events WHERE properties.uncounted = 'x'"),
            ("indexed_range_filter", "SELECT count() FROM events WHERE properties.duration > '100'"),
            (
                "indexed_filter_under_or",
                "SELECT count() FROM events WHERE properties.order_id = 'a1' OR event = 'signup'",
            ),
        ]
    )
    def test_reports_an_upper_bound_when_a_read_is_not_modelled(self, _name, sql):
        estimate = self._estimate(sql)

        assert estimate is not None
        assert estimate.upper_bound is True

    @parameterized.expand(
        [
            ("or_between_events", "SELECT count() FROM events WHERE event = '$pageview' OR event = 'signup'"),
            ("negated_event", "SELECT count() FROM events WHERE NOT event = '$pageview'"),
            ("negated_event_in_call_form", "SELECT count() FROM events WHERE not(event = '$pageview')"),
            ("event_compared_inside_a_function", "SELECT count() FROM events WHERE ifNull(event = '$pageview', true)"),
            ("unindexed_property_filter", "SELECT count() FROM events WHERE properties.$browser = 'Chrome'"),
            ("unparseable_bound", "SELECT count() FROM events WHERE timestamp > toStartOfMonth(now())"),
        ]
    )
    def test_predicates_it_cannot_narrow_on_widen_to_the_whole_table(self, _name, sql):
        assert self._events(sql) == _events_table(
            rows=WHOLE_TABLE_ROWS, days=float(DEFAULT_RANGE_DAYS), events=(), time_range="open"
        )

    @parameterized.expand(
        [
            (
                "join",
                "SELECT count() FROM events e JOIN persons p ON p.id = e.person_id",
                [("events", "events", "measured"), ("persons", "clickhouse", "unknown")],
            ),
            (
                "join_inside_a_subquery",
                "SELECT count() FROM (SELECT e.event FROM events e JOIN persons p ON p.id = e.person_id)",
                [("events", "events", "measured"), ("persons", "clickhouse", "unknown")],
            ),
            (
                "union_branch_on_another_table",
                "SELECT distinct_id FROM events UNION ALL SELECT toString(id) FROM persons",
                [("events", "events", "measured"), ("persons", "clickhouse", "unknown")],
            ),
            (
                "self_join_lists_each_scan",
                "SELECT count() FROM events a JOIN events b ON a.distinct_id = b.distinct_id",
                [("events", "events", "measured"), ("events", "events", "measured")],
            ),
            ("table_function", "SELECT number FROM numbers(10)", [("numbers", "static", "unknown")]),
        ]
    )
    def test_lists_every_table_in_the_from_tree(self, _name, sql, expected):
        estimate = self._estimate(sql)

        assert estimate is not None
        assert [(table.name, table.source, table.precision) for table in estimate.tables] == expected
        assert estimate.rows == sum(table.rows for table in estimate.tables if table.rows is not None)

    def test_a_query_over_other_tables_only_does_not_read_event_statistics(self):
        with patch.object(self.provider, "event_volume", wraps=self.provider.event_volume) as read_statistics:
            estimate = self._estimate("SELECT count() FROM persons")

        read_statistics.assert_not_called()
        assert estimate is not None
        assert estimate.rows == 0
        assert [table.precision for table in estimate.tables] == ["unknown"]

    def test_team_without_volume_lists_the_events_table_as_unknown(self):
        self.provider = FixedStatisticsProvider()

        estimate = self._estimate("SELECT count() FROM events")

        assert estimate is not None
        assert estimate.tables == (TableScanEstimate(name="events", source="events", precision="unknown"),)

    def test_a_query_with_no_table_has_no_estimate(self):
        assert self._estimate("SELECT 1") is None

    @parameterized.expand(
        [
            ("persons", "SELECT count() FROM persons", "persons", 2_400_000),
            ("raw_persons", "SELECT count() FROM raw_persons", "raw_persons", 2_400_000),
            ("groups", "SELECT count() FROM groups WHERE index = 0", "groups", 3_000),
            (
                "person_property_filter_does_not_narrow",
                "SELECT count() FROM persons WHERE properties.plan = 'enterprise'",
                "persons",
                2_400_000,
            ),
        ]
    )
    def test_persons_and_groups_are_sized_by_the_teams_row_count(self, _name, sql, name, expected_rows):
        self._with_table_rows(person=2_400_000, groups=3_000)

        estimate = self._estimate(sql)

        assert estimate is not None
        assert estimate.rows == expected_rows
        assert estimate.upper_bound is True
        assert estimate.tables == (
            TableScanEstimate(name=name, source="clickhouse", precision="size_only", rows=expected_rows),
        )

    @parameterized.expand(
        [
            (
                "bounded_start_time",
                "SELECT count() FROM sessions WHERE $start_timestamp > '2026-09-04' AND $start_timestamp < '2026-09-11'",
                70_000,
                7.0,
                "bounded",
            ),
            (
                "raw_table_and_relative_bound",
                "SELECT count() FROM raw_sessions WHERE min_timestamp > now() - interval 2 day",
                20_000,
                2.0,
                "open",
            ),
            ("no_bound_assumes_a_year", "SELECT count() FROM sessions", 3_650_000, float(DEFAULT_RANGE_DAYS), "open"),
            (
                "end_time_does_not_bound_the_scan",
                "SELECT count() FROM sessions WHERE $end_timestamp > now() - interval 2 day",
                3_650_000,
                float(DEFAULT_RANGE_DAYS),
                "open",
            ),
        ]
    )
    def test_sessions_scale_a_daily_rate_to_the_start_time_range(self, _name, sql, rows, days, time_range):
        self._with_sessions_per_day(10_000)

        estimate = self._estimate(sql)

        assert estimate is not None
        assert estimate.upper_bound is False
        [table] = estimate.tables
        assert (table.source, table.precision, table.rows, table.days, table.time_range) == (
            "clickhouse",
            "measured",
            rows,
            days,
            time_range,
        )

    def test_events_and_sessions_in_one_join_keep_their_own_ranges(self):
        self._with_sessions_per_day(10_000)

        estimate = self._estimate(
            "SELECT count() FROM events JOIN sessions ON events.$session_id = sessions.session_id"
            " WHERE events.timestamp > now() - interval 1 day AND events.timestamp < now()"
            " AND sessions.$start_timestamp > now() - interval 3 day AND sessions.$start_timestamp < now()"
        )

        assert estimate is not None
        assert [(table.name, table.rows, table.days) for table in estimate.tables] == [
            ("events", 100_000, 1.0),
            ("sessions", 30_000, 3.0),
        ]

    def test_a_join_to_persons_adds_the_teams_persons_to_the_ceiling(self):
        self._with_table_rows(person=2_400_000)

        estimate = self._estimate(
            "SELECT count() FROM events e JOIN persons p ON p.id = e.person_id WHERE e.event = 'signup'"
        )

        assert estimate is not None
        assert estimate.rows == 14_600_000 + 2_400_000
        assert [(table.name, table.precision) for table in estimate.tables] == [
            ("events", "measured"),
            ("persons", "size_only"),
        ]

    @parameterized.expand(
        [
            (
                "postgres",
                "Postgres",
                {"host": "localhost", "port": 5432, "schema": "public"},
                DIRECT_POSTGRES_URL_PATTERN,
                {DIRECT_POSTGRES_SCHEMA_OPTION: "public", DIRECT_POSTGRES_TABLE_OPTION: "orders"},
            ),
            (
                "mysql",
                "MySQL",
                {"host": "localhost", "port": 3306, "database": "app", "schema": "app"},
                DIRECT_MYSQL_URL_PATTERN,
                {DIRECT_MYSQL_SCHEMA_OPTION: "app", DIRECT_MYSQL_TABLE_OPTION: "orders"},
            ),
        ]
    )
    def test_a_direct_table_lists_the_catalog_estimate_as_size_only(
        self, _name, source_type, job_inputs, url_pattern, location_options
    ):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="src",
            connection_id="conn",
            destination_id="dest",
            source_type=source_type,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs=job_inputs,
        )
        DataWarehouseTable.objects.create(
            name="remote_orders",
            format="Parquet",
            team=self.team,
            url_pattern=url_pattern,
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "schema_valid": True}},
            options={**location_options, DIRECT_ESTIMATED_ROW_COUNT_OPTION: 812_000},
        )
        # A direct source's tables live only in the catalog built for that connection.
        self.context.database = Database.create_for(team=self.team, connection_id=str(source.id))

        estimate = self._estimate("SELECT count() FROM remote_orders")

        assert estimate is not None
        assert estimate.upper_bound is True
        assert estimate.tables == (
            TableScanEstimate(name="remote_orders", source="direct", precision="size_only", rows=812_000),
        )

        # The editor asks for metadata with the connection set, and a direct query used to get no estimate at all.
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=self.provider),
        ):
            response = get_hogql_metadata(
                HogQLMetadata(
                    kind="HogQLMetadata",
                    language=HogLanguage.HOG_QL,
                    query="SELECT count() FROM remote_orders",
                    connectionId=str(source.id),
                    indexUsage=True,
                ),
                self.team,
            )
        assert response.isValid is True
        assert response.scan_estimate is not None
        assert [(table.source, table.rows) for table in response.scan_estimate.tables] == [("direct", 812_000)]

    def test_a_synced_warehouse_table_counts_its_rows_as_a_ceiling(self):
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        DataWarehouseTable.objects.create(
            name="orders",
            format="Parquet",
            team=self.team,
            credential=credential,
            url_pattern="https://bucket.s3/orders/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True}},
            row_count=1_200_000,
            size_in_s3_mib=340.0,
        )
        self.context.database = Database.create_for(team=self.team)

        estimate = self._estimate(
            "SELECT count() FROM events e JOIN orders o ON o.id = e.distinct_id WHERE e.event = 'signup'"
        )

        assert estimate is not None
        assert estimate.rows == 14_600_000 + 1_200_000
        assert estimate.upper_bound is True
        assert estimate.tables[1] == TableScanEstimate(
            name="orders", source="warehouse", precision="size_only", rows=1_200_000, bytes=340 * 1024 * 1024
        )

    @parameterized.expand(
        [
            ("events_only_select", "select count() from events where event = 'signup'", ["events"]),
            (
                "join_lists_both_tables",
                "select count() from events e join persons p on p.id = e.person_id where e.event = 'signup'",
                ["events", "persons"],
            ),
        ]
    )
    def test_metadata_carries_the_estimate_when_the_flag_is_on(self, _name, sql, expected_tables):
        with (
            patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=True),
            patch("posthog.hogql.metadata.ClickHouseStatisticsProvider", return_value=self.provider),
        ):
            response = get_hogql_metadata(
                HogQLMetadata(kind="HogQLMetadata", language=HogLanguage.HOG_QL, query=sql, indexUsage=True),
                self.team,
            )

        assert response.isValid is True
        assert response.scan_estimate is not None
        assert response.scan_estimate.rows == 14_600_000
        assert [table.name for table in response.scan_estimate.tables] == expected_tables
        assert response.scan_estimate.tables[0].events == ["signup"]
        assert response.cost_plan is not None
        assert [step.table for step in response.cost_plan if step.kind == "scan"] == expected_tables

    def test_metadata_omits_the_estimate_when_the_flag_is_off(self):
        with patch("posthog.hogql.metadata.feature_enabled_or_false", return_value=False):
            response = get_hogql_metadata(
                HogQLMetadata(
                    kind="HogQLMetadata",
                    language=HogLanguage.HOG_QL,
                    query="select count() from events",
                    indexUsage=True,
                ),
                self.team,
            )

        assert response.scan_estimate is None
