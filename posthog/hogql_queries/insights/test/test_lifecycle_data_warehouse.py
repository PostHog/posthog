import csv
import tempfile
from pathlib import Path
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActorsQuery,
    DateRange,
    EventsNode,
    InsightActorsQuery,
    IntervalType,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
)

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.lifecycle_query_runner import LifecycleQueryRunner
from posthog.hogql_queries.legacy_compatibility.clean_properties import clean_entity_properties
from posthog.models.group.util import create_group
from posthog.test.test_utils import create_group_type_mapping_without_created_at

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

    def _setup_group_data_warehouse(self) -> str:
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        for group_key, group_name in [
            ("org:new", "org-new"),
            ("org:returning", "org-returning"),
            ("org:resurrecting", "org-resurrecting"),
            ("org:dormant", "org-dormant"),
        ]:
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=group_key,
                properties={"name": group_name},
            )

        sent_messages_path = self._write_csv(
            "organization_sent_messages.csv",
            ["organization_id", "sent_at", "text"],
            [
                [1, "2025-11-07 09:00:00", "new"],
                [2, "2025-11-06 09:00:00", "returning previous"],
                [2, "2025-11-07 09:00:00", "returning current"],
                [3, "2025-11-07 09:00:00", "resurrecting"],
                [4, "2025-11-06 09:00:00", "dormant"],
            ],
        )

        organizations_path = self._write_csv(
            "organizations.csv",
            ["id", "group_key", "created_at"],
            [
                [1, "org:new", "2025-11-07 08:00:00"],
                [2, "org:returning", "2025-11-06 08:00:00"],
                [3, "org:resurrecting", "2025-11-06 08:00:00"],
                [4, "org:dormant", "2025-11-06 08:00:00"],
            ],
        )

        sent_messages_table, source, credential, _df, sent_messages_cleanup = create_data_warehouse_table_from_csv(
            csv_path=sent_messages_path,
            table_name="organization_sent_messages",
            table_columns={
                "organization_id": "Int64",
                "sent_at": "DateTime64(3, 'UTC')",
                "text": "String",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )
        self.cleanup_fns.append(sent_messages_cleanup)

        organizations_table, _source, _credential, _df, organizations_cleanup = create_data_warehouse_table_from_csv(
            csv_path=organizations_path,
            table_name="organizations",
            table_columns={
                "id": "Int64",
                "group_key": "String",
                "created_at": "DateTime64(3, 'UTC')",
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
            source=source,
            credential=credential,
        )
        self.cleanup_fns.append(organizations_cleanup)

        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=sent_messages_table.name,
            source_table_key="organization_id",
            joining_table_name=organizations_table.name,
            joining_table_key="id",
            field_name="organizations",
        )

        return sent_messages_table.name

    def test_lifecycle_data_warehouse(self):
        """Data warehouse source matching a person aggregation target."""
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
                "id": "posthog_test_sent_messages",
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

    def test_lifecycle_data_warehouse_group_aggregation_target(self):
        """Data warehouse source matching a group aggregation target."""
        table_name = self._setup_group_data_warehouse()

        with freeze_time("2025-11-07T12:00:00Z"):
            query = LifecycleQuery(
                dateRange=DateRange(date_from="-1d"),
                interval=IntervalType.DAY,
                aggregation_group_type_index=0,
                series=[
                    LifecycleDataWarehouseNode(
                        id=table_name,
                        table_name=table_name,
                        timestamp_field="sent_at",
                        aggregation_target_field="organizations.group_key",
                        created_at_field="organizations.created_at",
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

        with freeze_time("2025-11-07T12:00:00Z"):
            for status, expected_name in {
                "new": "org-new",
                "returning": "org-returning",
                "resurrecting": "org-resurrecting",
                "dormant": "org-dormant",
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

    def test_lifecycle_data_warehouse_series_properties(self):
        """Series-level data warehouse properties filter lifecycle results."""
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
                        properties=clean_entity_properties(
                            [{"key": "text", "value": "resurrecting", "operator": "exact", "type": "data_warehouse"}]
                        ),
                    )
                ],
            )
            response = LifecycleQueryRunner(team=self.team, query=query).calculate()

        self.assertEqual(
            ["new", "returning", "resurrecting", "dormant"], [result["status"] for result in response.results]
        )

        results_by_status = {result["status"]: result for result in response.results}

        self.assertEqual(["2025-11-06", "2025-11-07"], results_by_status["new"]["days"])
        self.assertEqual([0.0, 0.0], results_by_status["new"]["data"])
        self.assertEqual([0.0, 0.0], results_by_status["returning"]["data"])
        self.assertEqual([0.0, 1.0], results_by_status["resurrecting"]["data"])
        self.assertEqual([0.0, 0.0], results_by_status["dormant"]["data"])

        with freeze_time("2025-11-07T12:00:00Z"):
            actors_response = ActorsQueryRunner(
                team=self.team,
                query=ActorsQuery(
                    select=["properties.name"],
                    orderBy=["properties.name ASC"],
                    source=InsightActorsQuery(
                        day="2025-11-07",
                        status="resurrecting",
                        source=query,
                    ),
                ),
            ).calculate()

        self.assertEqual([["user-3"]], actors_response.results)

    @parameterized.expand(
        [
            (
                "filters",
                {"properties": clean_entity_properties([{"key": "text", "value": "new", "type": "data_warehouse"}])},
                "Filters are not supported",
            ),
            ("test_account_filters", {"filterTestAccounts": True}, "Test account filters are not supported"),
            ("sampling", {"samplingFactor": 0.1}, "Sampling is not supported"),
            (
                "test_account_filters_and_sampling",
                {"filterTestAccounts": True, "samplingFactor": 0.1},
                "Test account filters and sampling are not supported",
            ),
            (
                "custom_aggregation_target_without_data_warehouse",
                {
                    "customAggregationTarget": True,
                    "series": [EventsNode(event="$pageview")],
                },
                "Custom entity aggregation target is not supported for lifecycle insights without a data warehouse series",
            ),
        ]
    )
    def test_lifecycle_data_warehouse_rejects_unsupported_settings(
        self, _name: str, extra_query_kwargs: dict, expected_error: str
    ) -> None:
        table_name = self._setup_data_warehouse()

        default_series = [
            LifecycleDataWarehouseNode(
                id=table_name,
                table_name=table_name,
                timestamp_field="sent_at",
                aggregation_target_field="users.person_id",
                created_at_field="users.signed_up",
            )
        ]
        query_kwargs = {
            "dateRange": DateRange(date_from="-1d"),
            "interval": IntervalType.DAY,
            "series": default_series,
            **extra_query_kwargs,
        }

        with freeze_time("2025-11-07T12:00:00Z"):
            with self.assertRaises(ValidationError) as context:
                LifecycleQueryRunner(
                    team=self.team,
                    query=LifecycleQuery(**query_kwargs),
                ).calculate()

        self.assertIn(expected_error, str(context.exception))

    def test_lifecycle_data_warehouse_invalid_aggregation_target(self):
        """Data warehouse source matching no aggregation target. Counts compute, but no actors are returned."""
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
                        aggregation_target_field="toUUID(md5(toString(user_id)))",  # create a synthetic uuid from the user_id, which won't match the person_id in the users table
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

        with freeze_time("2025-11-07T12:00:00Z"):
            for status in ["new", "returning", "resurrecting", "dormant"]:
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

                    # returns an empty actors response
                    self.assertEqual([], actors_response.results)
