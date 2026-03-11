import csv
import tempfile
from pathlib import Path
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from posthog.schema import (
    ActorsQuery,
    DateRange,
    InsightActorsQuery,
    IntervalType,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
)

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner

from products.data_warehouse.backend.models import DataWarehouseJoin
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.hogql_queries.insights.lifecycle.lifecycle_data_warehouse"


class TestLifecycleDataWarehouse(ClickhouseTestMixin, APIBaseTest):
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

    def _create_persons(self) -> dict[int, str]:
        person_ids = {index: str(uuid4()) for index in range(1, 5)}

        for user_id, person_id in person_ids.items():
            _create_person(
                team=self.team,
                distinct_ids=[f"user-{user_id}"],
                uuid=person_id,
                properties={"name": f"user-{user_id}"},
            )

        flush_persons_and_events()
        return person_ids

    def _setup_data_warehouse(self) -> str:
        person_ids = self._create_persons()

        sent_messages_path = self._write_csv(
            "sent_messages.csv",
            ["user_id", "sent_at", "text"],
            [
                [1, "2025-11-07 09:00:00", "new"],
                [2, "2025-11-06 09:00:00", "returning previous"],
                [2, "2025-11-07 09:00:00", "returning current"],
                [3, "2025-11-07 09:00:00", "resurrecting"],
                [4, "2025-11-06 09:00:00", "dormant"],
            ],
        )

        users_path = self._write_csv(
            "users.csv",
            ["id", "signed_up", "person_id"],
            [
                [1, "2025-11-07 08:00:00", person_ids[1]],
                [2, "2025-11-06 08:00:00", person_ids[2]],
                [3, "2025-11-06 08:00:00", person_ids[3]],
                [4, "2025-11-06 08:00:00", person_ids[4]],
            ],
        )

        sent_messages_table, source, credential, _df, sent_messages_cleanup = create_data_warehouse_table_from_csv(
            csv_path=sent_messages_path,
            table_name="sent_messages",
            table_columns={
                "user_id": "Int64",
                "sent_at": "DateTime64(3, 'UTC')",
                "text": "String",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )
        self.cleanup_fns.append(sent_messages_cleanup)

        users_table, _source, _credential, _df, users_cleanup = create_data_warehouse_table_from_csv(
            csv_path=users_path,
            table_name="users",
            table_columns={
                "id": "Int64",
                "signed_up": "DateTime64(3, 'UTC')",
                "person_id": "UUID",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
            source=source,
            credential=credential,
        )
        self.cleanup_fns.append(users_cleanup)

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=sent_messages_table.name,
            source_table_key="user_id",
            joining_table_name=users_table.name,
            joining_table_key="id",
            field_name="users",
        )

        return sent_messages_table.name

    def test_lifecycle_data_warehouse(self):
        table_name = self._setup_data_warehouse()

        with freeze_time("2025-11-07T12:00:00Z"):
            query = LifecycleQuery(
                dateRange=DateRange(date_from="-1d"),
                interval=IntervalType.DAY,
                series=[
                    LifecycleDataWarehouseNode(
                        id=table_name,
                        table_name=table_name,
                        timestamp_field="sent_at",
                        aggregation_target_field="users.person_id",
                        created_at_field="users.signed_up",
                    )
                ],
            )
            response = LifecycleQueryRunner(team=self.team, query=query).calculate()

        self.assertEqual(
            ["new", "returning", "resurrecting", "dormant"], [result["status"] for result in response.results]
        )

        results_by_status = {result["status"]: result for result in response.results}

        self.assertEqual(["2025-11-06", "2025-11-07"], results_by_status["new"]["days"])
        self.assertEqual([2.0, 1.0], results_by_status["new"]["data"])
        self.assertEqual([0.0, 1.0], results_by_status["returning"]["data"])
        self.assertEqual([0.0, 1.0], results_by_status["resurrecting"]["data"])
        self.assertEqual([0.0, -1.0], results_by_status["dormant"]["data"])
        self.assertEqual(
            {
                "name": table_name,
                "type": "data_warehouse",
                "order": 0,
                "math": "total",
                "table_name": table_name,
                "timestamp_field": "sent_at",
                "aggregation_target_field": "users.person_id",
                "created_at_field": "users.signed_up",
            },
            results_by_status["new"]["action"],
        )

        with freeze_time("2025-11-07T12:00:00Z"):
            for status, expected_name in {
                "new": "user-1",
                "returning": "user-2",
                "resurrecting": "user-3",
                "dormant": "user-4",
            }.items():
                with self.subTest(status=status):
                    actors_response = ActorsQueryRunner(
                        team=self.team,
                        query=ActorsQuery(
                            select=["properties.name"],
                            orderBy=["properties.name ASC"],
                            source=InsightActorsQuery(
                                day="2025-11-07",
                                status=status,
                                source=query,
                            ),
                        ),
                    ).calculate()

                    self.assertEqual([[expected_name]], actors_response.results)
