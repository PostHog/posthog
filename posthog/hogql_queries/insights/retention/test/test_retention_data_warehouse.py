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
from posthog.hogql_queries.insights.retention.test.utils import pad, pluck

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.hogql_queries.insights.retention.data_warehouse"


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

    @snapshot_clickhouse_queries
    def test_retention_data_warehouse_same_table(self):
        person_ids = self._create_people()
        activity_table_name = self._create_data_warehouse_table(
            filename="warehouse_activity.csv",
            table_name="warehouse_activity",
            header=["id", "person_id", "activity_type", "occurred_at"],
            rows=[
                [1, person_ids["user-1"], "signed_up", "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "signed_up", "2025-01-01 10:00:00"],
                [3, person_ids["user-3"], "signed_up", "2025-01-02 09:00:00"],
                [4, person_ids["user-4"], "signed_up", "2025-01-02 10:00:00"],
                [5, person_ids["user-1"], "renewed", "2025-01-02 12:00:00"],
                [6, person_ids["user-2"], "renewed", "2025-01-03 12:00:00"],
                [7, person_ids["user-3"], "renewed", "2025-01-03 13:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
            },
        )

        result = self.run_query(
            query={
                "dateRange": {
                    "date_from": "2025-01-01T00:00:00Z",
                    "date_to": "2025-01-05T00:00:00Z",
                },
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "targetEntity": {
                        "id": activity_table_name,
                        "name": activity_table_name,
                        "type": "data_warehouse",
                        "table_name": activity_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "occurred_at",
                        "properties": [
                            {
                                "key": "activity_type",
                                "value": "signed_up",
                                "operator": "exact",
                                "type": "data_warehouse",
                            }
                        ],
                    },
                    "returningEntity": {
                        "id": activity_table_name,
                        "name": activity_table_name,
                        "type": "data_warehouse",
                        "table_name": activity_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "occurred_at",
                        "properties": [
                            {"key": "activity_type", "value": "renewed", "operator": "exact", "type": "data_warehouse"}
                        ],
                    },
                },
            }
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 1, 1, 0],
                    [2, 1, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )

    @snapshot_clickhouse_queries
    def test_retention_data_warehouse_different_tables(self):
        person_ids = self._create_people()
        signups_table_name = self._create_data_warehouse_table(
            filename="warehouse_signups.csv",
            table_name="warehouse_signups",
            header=["id", "person_id", "signed_up_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "2025-01-01 10:00:00"],
                [3, person_ids["user-3"], "2025-01-02 09:00:00"],
                [4, person_ids["user-4"], "2025-01-02 10:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "signed_up_at": "DateTime64(3, 'UTC')",
            },
        )
        renewals_table_name = self._create_data_warehouse_table(
            filename="warehouse_renewals.csv",
            table_name="warehouse_renewals",
            header=["id", "person_id", "renewed_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-02 12:00:00"],
                [2, person_ids["user-2"], "2025-01-03 12:00:00"],
                [3, person_ids["user-3"], "2025-01-03 13:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "renewed_at": "DateTime64(3, 'UTC')",
            },
        )

        result = self.run_query(
            query={
                "dateRange": {
                    "date_from": "2025-01-01T00:00:00Z",
                    "date_to": "2025-01-05T00:00:00Z",
                },
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "targetEntity": {
                        "id": signups_table_name,
                        "name": signups_table_name,
                        "type": "data_warehouse",
                        "table_name": signups_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "signed_up_at",
                    },
                    "returningEntity": {
                        "id": renewals_table_name,
                        "name": renewals_table_name,
                        "type": "data_warehouse",
                        "table_name": renewals_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "renewed_at",
                    },
                },
            }
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 1, 1, 0],
                    [2, 1, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )

    @snapshot_clickhouse_queries
    def test_retention_data_warehouse_and_events(self):
        person_ids = self._create_people()
        signups_table_name = self._create_data_warehouse_table(
            filename="warehouse_event_mix_signups.csv",
            table_name="warehouse_event_mix_signups",
            header=["id", "person_id", "signed_up_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "2025-01-01 10:00:00"],
                [3, person_ids["user-3"], "2025-01-02 09:00:00"],
                [4, person_ids["user-4"], "2025-01-02 10:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "signed_up_at": "DateTime64(3, 'UTC')",
            },
        )

        for distinct_id, timestamp in [
            ("user-1", "2025-01-02T12:00:00Z"),
            ("user-2", "2025-01-03T12:00:00Z"),
            ("user-3", "2025-01-03T13:00:00Z"),
        ]:
            _create_event(team=self.team, event="paid", distinct_id=distinct_id, timestamp=timestamp)
        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {
                    "date_from": "2025-01-01T00:00:00Z",
                    "date_to": "2025-01-05T00:00:00Z",
                },
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "targetEntity": {
                        "id": signups_table_name,
                        "name": signups_table_name,
                        "type": "data_warehouse",
                        "table_name": signups_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "signed_up_at",
                    },
                    "returningEntity": {
                        "id": "paid",
                        "name": "paid",
                        "type": "events",
                    },
                },
            }
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 1, 1, 0],
                    [2, 1, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )
