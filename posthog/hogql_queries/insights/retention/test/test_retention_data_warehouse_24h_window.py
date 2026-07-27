import csv
import tempfile
from pathlib import Path

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.hogql_queries.insights.retention.data_warehouse_24h_window"

ACTIVITY_TABLE_COLUMNS = {
    "id": "Int64",
    "person_id": "UUID",
    "activity_type": "String",
    "occurred_at": "DateTime64(3, 'UTC')",
}


def _signed_up_entity(table_name: str) -> dict:
    return {
        "id": table_name,
        "name": table_name,
        "type": "data_warehouse",
        "table_name": table_name,
        "aggregation_target_field": "person_id",
        "timestamp_field": "occurred_at",
        "properties": [{"key": "activity_type", "value": "signed_up", "operator": "exact", "type": "data_warehouse"}],
    }


def _renewed_entity(table_name: str) -> dict:
    return {
        "id": table_name,
        "name": table_name,
        "type": "data_warehouse",
        "table_name": table_name,
        "aggregation_target_field": "person_id",
        "timestamp_field": "occurred_at",
        "properties": [{"key": "activity_type", "value": "renewed", "operator": "exact", "type": "data_warehouse"}],
    }


class TestRetentionDataWarehouse24hWindow(ClickhouseTestMixin, APIBaseTest):
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

    def _create_people(self) -> dict[str, str]:
        person_ids = {
            "user-1": "00000000-0000-0000-0000-000000000001",
            "user-2": "00000000-0000-0000-0000-000000000002",
            "user-3": "00000000-0000-0000-0000-000000000003",
            "user-4": "00000000-0000-0000-0000-000000000004",
        }
        for distinct_id, person_id in person_ids.items():
            _create_person(team=self.team, distinct_ids=[distinct_id], uuid=person_id)
        flush_persons_and_events()
        return person_ids

    def _create_data_warehouse_table(
        self,
        *,
        filename: str,
        table_name: str,
        header: list[str],
        rows: list[list[object]],
        table_columns: dict[str, str],
    ) -> str:
        csv_path = self._write_csv(filename, header, rows)
        table, _source, _credential, _df, cleanup = create_data_warehouse_table_from_csv(
            csv_path=csv_path,
            table_name=table_name,
            table_columns=table_columns,
            test_bucket=TEST_BUCKET,
            team=self.team,
        )
        self.cleanup_fns.append(cleanup)
        return table.name

    def run_query(self, query: dict) -> list[dict]:
        runner = RetentionQueryRunner(team=self.team, query=query)
        return runner.calculate().model_dump()["results"]

    @staticmethod
    def _row(result: list[dict], label: str) -> dict:
        return next(row for row in result if row["label"] == label)

    @snapshot_clickhouse_queries
    def test_same_table_dwh_start_and_return_24h_window(self):
        person_ids = self._create_people()
        activity_table = self._create_data_warehouse_table(
            filename="warehouse_activity.csv",
            table_name="warehouse_activity",
            header=["id", "person_id", "activity_type", "occurred_at"],
            rows=[
                [1, person_ids["user-1"], "signed_up", "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "signed_up", "2025-01-01 10:00:00"],
                [3, person_ids["user-3"], "signed_up", "2025-01-02 09:00:00"],
                [4, person_ids["user-4"], "signed_up", "2025-01-02 10:00:00"],
                [5, person_ids["user-1"], "renewed", "2025-01-02 12:00:00"],  # 27h after t_0 -> interval 1
                [6, person_ids["user-2"], "renewed", "2025-01-03 12:00:00"],  # 50h after t_0 -> interval 2
                [7, person_ids["user-3"], "renewed", "2025-01-03 13:00:00"],  # 28h after t_0 -> interval 1
                # user-4 signs up but never renews -> must still appear in interval 0 (LEFT JOIN preservation)
            ],
            table_columns=ACTIVITY_TABLE_COLUMNS,
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "timeWindowMode": "24_hour_windows",
                    "targetEntity": _signed_up_entity(activity_table),
                    "returningEntity": _renewed_entity(activity_table),
                },
            }
        )

        # Day 0 cohort = user-1 (t_0 09:00) + user-2 (t_0 10:00), both signed up on 2025-01-01.
        day_0 = self._row(result, "Day 0")
        self.assertEqual(day_0["values"][0]["count"], 2)  # interval 0: both
        self.assertEqual(day_0["values"][1]["count"], 1)  # interval 1: user-1 (renewed +27h)
        self.assertEqual(day_0["values"][2]["count"], 1)  # interval 2: user-2 (renewed +50h)
        self.assertEqual(day_0["values"][3]["count"], 0)

        # Day 1 cohort = user-3 (t_0 09:00) + user-4 (t_0 10:00), both signed up on 2025-01-02.
        day_1 = self._row(result, "Day 1")
        self.assertEqual(day_1["values"][0]["count"], 2)  # interval 0: both (user-4 has no renewal but still counts)
        self.assertEqual(day_1["values"][1]["count"], 1)  # interval 1: user-3 (renewed +28h)
        self.assertEqual(day_1["values"][2]["count"], 0)

    def _create_events(self, rows: list[tuple[str, str, str]]) -> None:
        for distinct_id, event, timestamp in rows:
            _create_event(team=self.team, event=event, distinct_id=distinct_id, timestamp=timestamp)
        flush_persons_and_events()

    def _create_renewals_table(self, table_name: str, rows: list[list[object]]) -> str:
        # Single-purpose table (every row is a renewal), so the retention entity needs no property filter — exercises
        # the no-property data warehouse return predicate (constant True) where >= t_0 is the only join discriminator.
        return self._create_data_warehouse_table(
            filename=f"{table_name}.csv",
            table_name=table_name,
            header=["id", "person_id", "occurred_at"],
            rows=rows,
            table_columns={"id": "Int64", "person_id": "UUID", "occurred_at": "DateTime64(3, 'UTC')"},
        )

    @staticmethod
    def _renewals_entity(table_name: str) -> dict:
        return {
            "id": table_name,
            "name": table_name,
            "type": "data_warehouse",
            "table_name": table_name,
            "aggregation_target_field": "person_id",
            "timestamp_field": "occurred_at",
        }

    def test_events_start_dwh_return_24h_window(self):
        person_ids = self._create_people()
        self._create_events(
            [
                ("user-1", "$signup", "2025-01-01 09:00:00"),
                ("user-2", "$signup", "2025-01-01 10:00:00"),
            ]
        )
        renewals_table = self._create_renewals_table(
            "warehouse_renewals_a",
            rows=[
                [1, person_ids["user-1"], "2025-01-02 12:00:00"],  # 27h after t_0 -> interval 1
                # user-2 never renews -> still counts in interval 0 (no-property DWH return + LEFT JOIN)
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "timeWindowMode": "24_hour_windows",
                    "targetEntity": {"id": "$signup", "name": "$signup", "type": "events"},
                    "returningEntity": self._renewals_entity(renewals_table),
                },
            }
        )

        day_0 = self._row(result, "Day 0")
        self.assertEqual(day_0["values"][0]["count"], 2)  # interval 0: user-1 + user-2
        self.assertEqual(day_0["values"][1]["count"], 1)  # interval 1: user-1
        self.assertEqual(day_0["values"][2]["count"], 0)

    def test_dwh_start_events_return_24h_window(self):
        person_ids = self._create_people()
        signups_table = self._create_renewals_table(
            "warehouse_signups_b",
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "2025-01-02 09:00:00"],
            ],
        )
        self._create_events(
            [
                ("user-1", "$renewed", "2025-01-02 12:00:00"),  # 27h after t_0 -> interval 1
                # user-2 never renews
            ]
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "timeWindowMode": "24_hour_windows",
                    "targetEntity": self._renewals_entity(signups_table),
                    "returningEntity": {"id": "$renewed", "name": "$renewed", "type": "events"},
                },
            }
        )

        day_0 = self._row(result, "Day 0")  # user-1 signed up 2025-01-01
        self.assertEqual(day_0["values"][0]["count"], 1)
        self.assertEqual(day_0["values"][1]["count"], 1)  # renewed +27h

        day_1 = self._row(result, "Day 1")  # user-2 signed up 2025-01-02, never renews
        self.assertEqual(day_1["values"][0]["count"], 1)
        self.assertEqual(day_1["values"][1]["count"], 0)

    def test_two_different_dwh_tables_24h_window(self):
        person_ids = self._create_people()
        signups_table = self._create_renewals_table(
            "warehouse_signups_c",
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "2025-01-02 09:00:00"],
            ],
        )
        renewals_table = self._create_renewals_table(
            "warehouse_renewals_c",
            rows=[
                [1, person_ids["user-1"], "2025-01-02 12:00:00"],  # 27h after t_0 -> interval 1
            ],
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "timeWindowMode": "24_hour_windows",
                    "targetEntity": self._renewals_entity(signups_table),
                    "returningEntity": self._renewals_entity(renewals_table),
                },
            }
        )

        day_0 = self._row(result, "Day 0")  # user-1
        self.assertEqual(day_0["values"][0]["count"], 1)
        self.assertEqual(day_0["values"][1]["count"], 1)

        day_1 = self._row(result, "Day 1")  # user-2, no renewal
        self.assertEqual(day_1["values"][0]["count"], 1)
        self.assertEqual(day_1["values"][1]["count"], 0)
