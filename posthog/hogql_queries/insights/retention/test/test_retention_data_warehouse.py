import csv
import tempfile
from pathlib import Path

from freezegun import freeze_time
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DateRange,
    RetentionEntity,
    RetentionEntityKind,
    RetentionFilter,
    RetentionPeriod,
    RetentionQuery,
)

from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.hogql_queries.insights.retention.retention_data_warehouse"


class TestRetentionDataWarehouse(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.cleanup_fns = []
        self.temp_dirs = []

    def tearDown(self):
        for cleanup in self.cleanup_fns:
            cleanup()
        for temp_dir in self.temp_dirs:
            temp_dir.cleanup()
        super().tearDown()

    def _write_csv(self, filename: str, header: list[str], rows: list[list[object]]) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.temp_dirs.append(temp_dir)
        path = Path(temp_dir.name) / filename

        with open(path, "w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(header)
            writer.writerows(rows)

        return path

    def _setup_events_table(self) -> str:
        # Four users over four days — classic retention shape:
        # user-1: day 1, 2, 3, 4 — stays every day
        # user-2: day 1, 3      — returns on day 3 only
        # user-3: day 1         — never returns
        # user-4: day 2, 3, 4   — cohorted on day 2
        rows: list[list[object]] = [
            ["user-1", "2025-11-04 08:00:00"],
            ["user-1", "2025-11-05 08:00:00"],
            ["user-1", "2025-11-06 08:00:00"],
            ["user-1", "2025-11-07 08:00:00"],
            ["user-2", "2025-11-04 08:00:00"],
            ["user-2", "2025-11-06 08:00:00"],
            ["user-3", "2025-11-04 08:00:00"],
            ["user-4", "2025-11-05 08:00:00"],
            ["user-4", "2025-11-06 08:00:00"],
            ["user-4", "2025-11-07 08:00:00"],
        ]

        csv_path = self._write_csv(
            "dw_events.csv",
            ["user_id", "event_time"],
            rows,
        )

        table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
            csv_path=csv_path,
            table_name="dw_events",
            table_columns={
                "user_id": "String",
                "event_time": "DateTime64(3, 'UTC')",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )
        self.cleanup_fns.append(cleanup)
        return table.name

    def _dw_entity(self, table_name: str) -> RetentionEntity:
        return RetentionEntity(
            kind=RetentionEntityKind.DATA_WAREHOUSE_NODE,
            id=table_name,
            name=table_name,
            type=None,
            table_name=table_name,
            timestamp_field="event_time",
            distinct_id_field="user_id",
            id_field="user_id",
        )

    def test_retention_data_warehouse_basic(self) -> None:
        table_name = self._setup_events_table()

        with freeze_time("2025-11-07T12:00:00Z"):
            query = RetentionQuery(
                dateRange=DateRange(date_from="2025-11-04", date_to="2025-11-07"),
                retentionFilter=RetentionFilter(
                    period=RetentionPeriod.DAY,
                    totalIntervals=4,
                    targetEntity=self._dw_entity(table_name),
                    returningEntity=self._dw_entity(table_name),
                ),
            )

            response = RetentionQueryRunner(team=self.team, query=query).calculate()

        # Count users cohorted on the first day (2025-11-04): user-1, user-2, user-3 -> 3
        day_0 = next(row for row in response.results if row["date"].strftime("%Y-%m-%d") == "2025-11-04")
        self.assertEqual(day_0["values"][0]["count"], 3)  # day 0 cohort size
        # Users from day 0 who returned on day 1 (2025-11-05): only user-1
        self.assertEqual(day_0["values"][1]["count"], 1)
        # Day 2 (2025-11-06) returners from day-0 cohort: user-1 and user-2
        self.assertEqual(day_0["values"][2]["count"], 2)
        # Day 3 (2025-11-07) returners from day-0 cohort: user-1
        self.assertEqual(day_0["values"][3]["count"], 1)

        day_1 = next(row for row in response.results if row["date"].strftime("%Y-%m-%d") == "2025-11-05")
        # Cohort for 2025-11-05: user-1, user-4 -> 2
        self.assertEqual(day_1["values"][0]["count"], 2)

    @parameterized.expand(
        [
            ("24_hour_windows", {"timeWindowMode": "24_hour_windows"}, "24 hour windows"),
            ("first_time", {"retentionType": "retention_first_time"}, "First-time"),
            ("first_ever", {"retentionType": "retention_first_ever_occurrence"}, "First-time"),
            ("custom_brackets", {"retentionCustomBrackets": [1, 2, 3]}, "Custom retention brackets"),
            ("sum_aggregation", {"aggregationType": "sum", "aggregationProperty": "x"}, "Sum/avg"),
        ]
    )
    def test_validation_rejects_unsupported(self, _name: str, extra: dict, expected_message_fragment: str) -> None:
        with self.assertRaises(ValidationError) as cm:
            RetentionQueryRunner(
                team=self.team,
                query=RetentionQuery(
                    dateRange=DateRange(date_from="2025-11-04", date_to="2025-11-07"),
                    retentionFilter=RetentionFilter(
                        period=RetentionPeriod.DAY,
                        totalIntervals=4,
                        targetEntity=self._dw_entity("any_table"),
                        returningEntity=self._dw_entity("any_table"),
                        **extra,
                    ),
                ),
            )

        self.assertIn(expected_message_fragment, str(cm.exception))

    def test_validation_rejects_mixed_entity_kinds(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            RetentionQueryRunner(
                team=self.team,
                query=RetentionQuery(
                    dateRange=DateRange(date_from="2025-11-04", date_to="2025-11-07"),
                    retentionFilter=RetentionFilter(
                        period=RetentionPeriod.DAY,
                        totalIntervals=4,
                        targetEntity=self._dw_entity("any_table"),
                        returningEntity=RetentionEntity(
                            kind=RetentionEntityKind.EVENTS_NODE,
                            id="$pageview",
                            type="events",
                        ),
                    ),
                ),
            )

        self.assertIn("data warehouse nodes", str(cm.exception))

    def test_validation_rejects_mismatched_tables(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            RetentionQueryRunner(
                team=self.team,
                query=RetentionQuery(
                    dateRange=DateRange(date_from="2025-11-04", date_to="2025-11-07"),
                    retentionFilter=RetentionFilter(
                        period=RetentionPeriod.DAY,
                        totalIntervals=4,
                        targetEntity=self._dw_entity("table_one"),
                        returningEntity=self._dw_entity("table_two"),
                    ),
                ),
            )

        self.assertIn("same table", str(cm.exception))
