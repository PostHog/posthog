import csv
import tempfile
from pathlib import Path
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner
from posthog.hogql_queries.insights.retention.test.utils import pad, pluck
from posthog.models.group.util import create_group
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.cohorts.backend.models.cohort import Cohort
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

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

    def run_actors_query(self, interval: int, query: dict[str, Any], actor: str = "person") -> list[list[Any]]:
        query["kind"] = "RetentionQuery"
        runner = ActorsQueryRunner(
            team=self.team,
            query={
                "select": [actor, "appearances"],
                "orderBy": ["length(appearances) DESC", "actor_id"],
                "source": {
                    "kind": "InsightActorsQuery",
                    "interval": interval,
                    "source": query,
                },
            },
        )
        return runner.calculate().model_dump()["results"]

    def _create_groups(self) -> dict[str, str]:
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        group_keys = {
            "user-1": "org:1",
            "user-2": "org:2",
            "user-3": "org:3",
            "user-4": "org:4",
        }

        for label, group_key in group_keys.items():
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=group_key,
                properties={"name": label},
            )

        return group_keys

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

    def _activity_breakdown_table(self) -> tuple[str, dict[str, str]]:
        person_ids = self._create_people()
        table = self._create_data_warehouse_table(
            filename="warehouse_activity_breakdown.csv",
            table_name="warehouse_activity_breakdown",
            header=["id", "person_id", "activity_type", "plan", "occurred_at"],
            rows=[
                [1, person_ids["user-1"], "signed_up", "pro", "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "signed_up", "free", "2025-01-01 10:00:00"],
                [3, person_ids["user-1"], "renewed", "pro", "2025-01-02 12:00:00"],
                [4, person_ids["user-2"], "renewed", "free", "2025-01-03 12:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "plan": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
            },
        )
        return table, person_ids

    def _activity_retention_filter(self, table: str) -> dict[str, Any]:
        def entity(activity: str) -> dict[str, Any]:
            return {
                "id": table,
                "name": table,
                "type": "data_warehouse",
                "table_name": table,
                "aggregation_target_field": "person_id",
                "timestamp_field": "occurred_at",
                "properties": [
                    {"key": "activity_type", "value": activity, "operator": "exact", "type": "data_warehouse"}
                ],
            }

        return {
            "period": "Day",
            "totalIntervals": 4,
            "targetEntity": entity("signed_up"),
            "returningEntity": entity("renewed"),
        }

    @snapshot_clickhouse_queries
    def test_retention_data_warehouse_breakdown_by_warehouse_column(self):
        table, _person_ids = self._activity_breakdown_table()

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": self._activity_retention_filter(table),
                "breakdownFilter": {"breakdown": "plan", "breakdown_type": "hogql"},
            }
        )

        self.assertEqual({c.get("breakdown_value") for c in result}, {"pro", "free"})
        pro = pluck([c for c in result if c.get("breakdown_value") == "pro"], "values", "count")
        free = pluck([c for c in result if c.get("breakdown_value") == "free"], "values", "count")
        self.assertEqual(pro[0][:2], [1, 1])  # user-1 day 0, renewed day 1
        self.assertEqual(free[0][:3], [1, 0, 1])  # user-2 day 0, renewed day 2

    def test_retention_data_warehouse_breakdown_by_cohort(self):
        table, person_ids = self._activity_breakdown_table()
        cohort = Cohort.objects.create(
            team=self.team,
            name="pro_users",
            groups=[{"properties": [{"key": "id", "value": [person_ids["user-1"]], "type": "person"}]}],
        )
        cohort.calculate_people_ch(pending_version=0)

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": self._activity_retention_filter(table),
                "breakdownFilter": {"breakdown_type": "cohort", "breakdown": [cohort.pk]},
            }
        )

        self.assertEqual({c.get("breakdown_value") for c in result}, {str(cohort.pk)})

    def test_retention_data_warehouse_breakdown_by_person_property(self):
        # Person-property breakdown on a DWH series resolves through a configured
        # DWH-table -> persons join; the variant passes the person.* extract through
        # unchanged, so it composes once that join exists.
        person_ids = {
            "user-1": "00000000-0000-0000-0000-000000000001",
            "user-2": "00000000-0000-0000-0000-000000000002",
        }
        _create_person(team=self.team, distinct_ids=["user-1"], uuid=person_ids["user-1"], properties={"plan": "pro"})
        _create_person(team=self.team, distinct_ids=["user-2"], uuid=person_ids["user-2"], properties={"plan": "free"})
        flush_persons_and_events()

        table = self._create_data_warehouse_table(
            filename="warehouse_activity_person_bd.csv",
            table_name="warehouse_activity_person_bd",
            header=["id", "person_id", "activity_type", "occurred_at"],
            rows=[
                [1, person_ids["user-1"], "signed_up", "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "signed_up", "2025-01-01 10:00:00"],
                [3, person_ids["user-1"], "renewed", "2025-01-02 12:00:00"],
                [4, person_ids["user-2"], "renewed", "2025-01-03 12:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
            },
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=table,
            source_table_key="person_id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="person",
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": self._activity_retention_filter(table),
                "breakdownFilter": {"breakdowns": [{"property": "plan", "type": "person"}]},
            }
        )

        self.assertEqual({c.get("breakdown_value") for c in result}, {"pro", "free"})

    def test_retention_data_warehouse_event_property_breakdown_degrades_to_empty_bucket(self):
        table, _person_ids = self._activity_breakdown_table()

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": self._activity_retention_filter(table),
                "breakdownFilter": {"breakdowns": [{"property": "category", "type": "event"}]},
            }
        )

        # Event-property extracts can't resolve against a data-warehouse-table arm, so the
        # whole series degrades to the empty bucket rather than raising.
        self.assertEqual({c.get("breakdown_value") for c in result}, {""})

    def test_retention_first_ever_dwh_start_events_return_event_breakdown_degrades_to_empty_bucket(self):
        # Cross-table first-ever retention: data warehouse start entity, events return entity,
        # breakdown on an events-table property. The first-ever breakdown value must come from
        # the actor's first START event, but the start event lives in the DWH table and carries
        # no $browser. The return arm therefore must NOT fall back to the return event's $browser
        # (which would happen because start_entity_expr_no_props collapses to a truthy constant
        # for a DWH start); every actor degrades to the empty bucket instead.
        person_ids = self._create_people()
        signups_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_ever_breakdown_signups.csv",
            table_name="warehouse_first_ever_breakdown_signups",
            header=["id", "person_id", "signed_up_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "2025-01-01 10:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "signed_up_at": "DateTime64(3, 'UTC')",
            },
        )

        for distinct_id, browser in [("user-1", "Chrome"), ("user-2", "Firefox")]:
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                timestamp="2025-01-02T12:00:00Z",
                properties={"$browser": browser},
            )
        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "retentionType": "retention_first_ever_occurrence",
                    "targetEntity": {
                        "id": signups_table_name,
                        "name": signups_table_name,
                        "type": "data_warehouse",
                        "table_name": signups_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "signed_up_at",
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
                "breakdownFilter": {"breakdowns": [{"property": "$browser", "type": "event"}]},
            }
        )

        # The breakdown value isn't available on the DWH start side, so both actors land in the
        # empty bucket — never bucketed by the return event's $browser (Chrome / Firefox).
        self.assertEqual({c.get("breakdown_value") for c in result}, {""})

        # Sanity: both users cohort day 0 and return day 1 — they still retain in the empty bucket.
        empty_bucket = [c for c in result if c.get("breakdown_value") == ""]
        self.assertEqual(
            pluck(empty_bucket, "values", "count"),
            pad([[2, 2, 0, 0], [0, 0, 0], [0, 0], [0], [0]]),
        )

    @parameterized.expand([("person",), ("group",)])
    def test_retention_data_warehouse_actor_query_maps_back_to_actors(self, actor_type: str) -> None:
        actor_ids = self._create_people() if actor_type == "person" else self._create_groups()
        actor_column_name = "person_id" if actor_type == "person" else "organization_id"
        actor_column_type = "UUID" if actor_type == "person" else "String"
        actor_query_type = "person" if actor_type == "person" else "group"

        signups_table_name = self._create_data_warehouse_table(
            filename=f"warehouse_signups_{actor_type}.csv",
            table_name=f"warehouse_signups_{actor_type}",
            header=["id", actor_column_name, "signed_up_at"],
            rows=[
                [1, actor_ids["user-1"], "2025-01-01 09:00:00"],
                [2, actor_ids["user-2"], "2025-01-01 10:00:00"],
                [3, actor_ids["user-3"], "2025-01-02 09:00:00"],
                [4, actor_ids["user-4"], "2025-01-02 10:00:00"],
            ],
            table_columns={
                "id": "Int64",
                actor_column_name: actor_column_type,
                "signed_up_at": "DateTime64(3, 'UTC')",
            },
        )
        renewals_table_name = self._create_data_warehouse_table(
            filename=f"warehouse_renewals_{actor_type}.csv",
            table_name=f"warehouse_renewals_{actor_type}",
            header=["id", actor_column_name, "renewed_at"],
            rows=[
                [1, actor_ids["user-1"], "2025-01-02 12:00:00"],
                [2, actor_ids["user-2"], "2025-01-03 12:00:00"],
                [3, actor_ids["user-3"], "2025-01-03 13:00:00"],
            ],
            table_columns={
                "id": "Int64",
                actor_column_name: actor_column_type,
                "renewed_at": "DateTime64(3, 'UTC')",
            },
        )

        query: dict[str, Any] = {
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
                    "aggregation_target_field": actor_column_name,
                    "timestamp_field": "signed_up_at",
                },
                "returningEntity": {
                    "id": renewals_table_name,
                    "name": renewals_table_name,
                    "type": "data_warehouse",
                    "table_name": renewals_table_name,
                    "aggregation_target_field": actor_column_name,
                    "timestamp_field": "renewed_at",
                },
            },
        }

        if actor_type == "group":
            query["aggregation_group_type_index"] = 0

        result = self.run_query(query=query)

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

        actor_result = self.run_actors_query(interval=0, query=query, actor=actor_query_type)

        self.assertEqual(len(actor_result), 2)

        appearances_by_actor_id = {str(actor[0]["id"]): actor[1] for actor in actor_result}
        self.assertEqual(appearances_by_actor_id[str(actor_ids["user-1"])], [0, 1])
        self.assertEqual(appearances_by_actor_id[str(actor_ids["user-2"])], [0, 2])

        if actor_type == "person":
            self.assertCountEqual(
                [tuple(actor[0]["distinct_ids"]) for actor in actor_result],
                [("user-1",), ("user-2",)],
            )
        else:
            self.assertCountEqual([actor[0]["id"] for actor in actor_result], ["org:1", "org:2"])

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

    def test_retention_data_warehouse_return_event_with_minimum_occurrences(self):
        # Same cohorts as test_retention_data_warehouse_different_tables, but the data warehouse return entity now
        # only counts an interval when the user renewed at least twice that day. user-1 (two renewals on 01-02) and
        # user-3 (two renewals on 01-03) qualify; user-2's single renewal on 01-03 falls below the threshold and is
        # dropped — the one cell that differs from the minimumOccurrences = 1 result.
        person_ids = self._create_people()
        signups_table_name = self._create_data_warehouse_table(
            filename="warehouse_min_occ_signups.csv",
            table_name="warehouse_min_occ_signups",
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
            filename="warehouse_min_occ_renewals.csv",
            table_name="warehouse_min_occ_renewals",
            header=["id", "person_id", "renewed_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-02 09:00:00"],
                [2, person_ids["user-1"], "2025-01-02 15:00:00"],  # second renewal same day → qualifies interval 1
                [3, person_ids["user-2"], "2025-01-03 12:00:00"],  # only one renewal → below threshold, dropped
                [4, person_ids["user-3"], "2025-01-03 08:00:00"],
                [5, person_ids["user-3"], "2025-01-03 20:00:00"],  # second renewal same day → qualifies interval 1
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
                    "minimumOccurrences": 2,
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
                    [2, 1, 0, 0],
                    [2, 1, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )

    def test_retention_data_warehouse_property_aggregation_different_tables(self) -> None:
        person_ids = self._create_people()
        signups_table_name = self._create_data_warehouse_table(
            filename="warehouse_property_aggregation_signups.csv",
            table_name="warehouse_property_aggregation_signups",
            header=["id", "person_id", "signed_up_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00"],
                [2, person_ids["user-2"], "2025-01-01 10:00:00"],
                [3, person_ids["user-3"], "2025-01-02 09:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "signed_up_at": "DateTime64(3, 'UTC')",
            },
        )
        payments_table_name = self._create_data_warehouse_table(
            filename="warehouse_property_aggregation_payments.csv",
            table_name="warehouse_property_aggregation_payments",
            header=["id", "person_id", "paid_at", "amount"],
            rows=[
                [1, person_ids["user-1"], "2025-01-01 12:00:00", 50],
                [2, person_ids["user-1"], "2025-01-02 12:00:00", 100],
                [3, person_ids["user-2"], "2025-01-01 08:00:00", 999],
                [4, person_ids["user-2"], "2025-01-01 11:00:00", 30],
                [5, person_ids["user-3"], "2025-01-03 13:00:00", 200],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "paid_at": "DateTime64(3, 'UTC')",
                "amount": "Float64",
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
                        "id": payments_table_name,
                        "name": payments_table_name,
                        "type": "data_warehouse",
                        "table_name": payments_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "paid_at",
                    },
                    "aggregationType": "sum",
                    "aggregationProperty": "amount",
                    "aggregationPropertyType": "data_warehouse",
                },
            }
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 1, 0, 0],
                    [1, 1, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )
        self.assertEqual(
            pluck(result, "values", "aggregation_value"),
            pad(
                [
                    [80, 100, 0, 0],
                    [0, 200, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )

    def test_retention_data_warehouse_property_aggregation_same_table_different_events(self) -> None:
        person_ids = self._create_people()
        activity_table_name = self._create_data_warehouse_table(
            filename="warehouse_property_aggregation_activity.csv",
            table_name="warehouse_property_aggregation_activity",
            header=["id", "person_id", "activity_type", "occurred_at", "amount"],
            rows=[
                [1, person_ids["user-1"], "signup", "2025-01-01 09:00:00", 0],
                [2, person_ids["user-1"], "payment", "2025-01-01 12:00:00", 50],
                [3, person_ids["user-1"], "payment", "2025-01-02 12:00:00", 100],
                [4, person_ids["user-2"], "payment", "2025-01-01 08:00:00", 999],
                [5, person_ids["user-2"], "signup", "2025-01-01 10:00:00", 0],
                [6, person_ids["user-2"], "payment", "2025-01-01 11:00:00", 30],
                [7, person_ids["user-3"], "signup", "2025-01-02 09:00:00", 0],
                [8, person_ids["user-3"], "payment", "2025-01-03 13:00:00", 200],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
                "amount": "Float64",
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
                                "value": "signup",
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
                            {
                                "key": "activity_type",
                                "value": "payment",
                                "operator": "exact",
                                "type": "data_warehouse",
                            }
                        ],
                    },
                    "aggregationType": "sum",
                    "aggregationProperty": "amount",
                    "aggregationPropertyType": "data_warehouse",
                },
            }
        )

        self.assertEqual(
            pluck(result, "values", "count"),
            pad(
                [
                    [2, 1, 0, 0],
                    [1, 1, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )
        self.assertEqual(
            pluck(result, "values", "aggregation_value"),
            pad(
                [
                    [80, 100, 0, 0],
                    [0, 200, 0],
                    [0, 0],
                    [0],
                    [0],
                ]
            ),
        )

    @parameterized.expand(
        [
            ("sum", [40, 120]),
            ("avg", [20, 60]),
        ]
    )
    def test_retention_data_warehouse_property_aggregation_same_table(
        self, aggregation_type: str, expected_aggregation_values: list[float]
    ) -> None:
        person_ids = self._create_people()
        video_watches_table_name = self._create_data_warehouse_table(
            filename="warehouse_video_watches.csv",
            table_name="warehouse_video_watches",
            header=["id", "person_id", "watched_at", "watch_duration"],
            rows=[
                [1, person_ids["user-1"], "2025-01-01 09:00:00", 10],
                [2, person_ids["user-2"], "2025-01-01 10:00:00", 30],
                [3, person_ids["user-1"], "2025-01-02 09:00:00", 20],
                [4, person_ids["user-1"], "2025-01-02 10:00:00", 30],
                [5, person_ids["user-2"], "2025-01-02 11:00:00", 70],
                [6, person_ids["user-3"], "2025-01-02 12:00:00", 100],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "watched_at": "DateTime64(3, 'UTC')",
                "watch_duration": "Float64",
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
                        "id": video_watches_table_name,
                        "name": video_watches_table_name,
                        "type": "data_warehouse",
                        "table_name": video_watches_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "watched_at",
                    },
                    "returningEntity": {
                        "id": video_watches_table_name,
                        "name": video_watches_table_name,
                        "type": "data_warehouse",
                        "table_name": video_watches_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "watched_at",
                    },
                    "aggregationType": aggregation_type,
                    "aggregationProperty": "watch_duration",
                    "aggregationPropertyType": "data_warehouse",
                },
            }
        )

        self.assertEqual(result[0]["values"][0]["count"], 2)
        self.assertEqual(result[0]["values"][0]["aggregation_value"], expected_aggregation_values[0])
        self.assertEqual(result[0]["values"][1]["count"], 2)
        self.assertEqual(result[0]["values"][1]["aggregation_value"], expected_aggregation_values[1])

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

    def _first_time_dwh_query(self, *, table_name: str, retention_type: str) -> dict[str, Any]:
        return {
            "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
            "retentionFilter": {
                "period": "Day",
                "totalIntervals": 4,
                "retentionType": retention_type,
                "targetEntity": {
                    "id": table_name,
                    "name": table_name,
                    "type": "data_warehouse",
                    "table_name": table_name,
                    "aggregation_target_field": "person_id",
                    "timestamp_field": "occurred_at",
                    "properties": [
                        {"key": "activity_type", "value": "signed_up", "operator": "exact", "type": "data_warehouse"}
                    ],
                },
                "returningEntity": {
                    "id": table_name,
                    "name": table_name,
                    "type": "data_warehouse",
                    "table_name": table_name,
                    "aggregation_target_field": "person_id",
                    "timestamp_field": "occurred_at",
                    "properties": [
                        {"key": "activity_type", "value": "renewed", "operator": "exact", "type": "data_warehouse"}
                    ],
                },
            },
        }

    def test_retention_first_time_vs_first_ever_dwh_same_table(self):
        # user-1's first row in the table ("browsed") does not match the start filter ("signed_up"); a later
        # row does. So under first_time (first occurrence matching filters) user-1 cohorts on the first signed_up
        # row, but under first_ever_occurrence user-1 is excluded because their first-ever row isn't a match.
        person_ids = self._create_people()
        activity_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_time_activity.csv",
            table_name="warehouse_first_time_activity",
            header=["id", "person_id", "activity_type", "occurred_at"],
            rows=[
                [1, person_ids["user-1"], "browsed", "2025-01-01 09:00:00"],
                [2, person_ids["user-1"], "signed_up", "2025-01-02 09:00:00"],
                [3, person_ids["user-1"], "renewed", "2025-01-03 12:00:00"],
                [4, person_ids["user-2"], "signed_up", "2025-01-01 10:00:00"],
                [5, person_ids["user-2"], "renewed", "2025-01-02 12:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
            },
        )

        first_time_result = self.run_query(
            query=self._first_time_dwh_query(table_name=activity_table_name, retention_type="retention_first_time")
        )
        # user-2 cohorts on day 0 (first signed_up), user-1 on day 1 (first signed_up, after the non-matching
        # "browsed" row); each renews one interval later.
        self.assertEqual(
            pluck(first_time_result, "values", "count"),
            pad([[1, 1, 0, 0], [1, 1, 0], [0, 0], [0], [0]]),
        )

        first_ever_result = self.run_query(
            query=self._first_time_dwh_query(
                table_name=activity_table_name, retention_type="retention_first_ever_occurrence"
            )
        )
        # user-1's first-ever row is "browsed", not "signed_up", so they are excluded entirely; only user-2
        # (whose first-ever row is "signed_up") is cohorted, on day 0.
        self.assertEqual(
            pluck(first_ever_result, "values", "count"),
            pad([[1, 1, 0, 0], [0, 0, 0], [0, 0], [0], [0]]),
        )

    def test_retention_first_time_dwh_excludes_anchor_before_window(self):
        # The first-time anchor scans the whole table (all time), so a user whose first matching row is before
        # date_from is cohorted on that out-of-window interval and therefore excluded — even though they have a
        # later matching row inside the window. (Reading the recurring within-window set would wrongly cohort
        # them on the in-window row.)
        person_ids = self._create_people()
        activity_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_time_before_window.csv",
            table_name="warehouse_first_time_before_window",
            header=["id", "person_id", "activity_type", "occurred_at"],
            rows=[
                [1, person_ids["user-1"], "signed_up", "2024-12-30 09:00:00"],  # before window — the true anchor
                [2, person_ids["user-1"], "signed_up", "2025-01-02 09:00:00"],  # in window, but not the first
                [3, person_ids["user-1"], "renewed", "2025-01-03 12:00:00"],
                [4, person_ids["user-2"], "signed_up", "2025-01-01 10:00:00"],
                [5, person_ids["user-2"], "renewed", "2025-01-02 12:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
            },
        )

        result = self.run_query(
            query=self._first_time_dwh_query(table_name=activity_table_name, retention_type="retention_first_time")
        )
        # user-1's first signed_up is before date_from, so they are excluded; only user-2 cohorts (day 0).
        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[1, 1, 0, 0], [0, 0, 0], [0, 0], [0], [0]]),
        )

    def test_retention_first_ever_dwh_start_events_return(self):
        # Cross-table: data warehouse start entity, events return entity. The first-ever anchor is resolved on the
        # data warehouse table (all time), so user-1 — whose first signup row is before the window — is excluded.
        person_ids = self._create_people()
        signups_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_ever_signups.csv",
            table_name="warehouse_first_ever_signups",
            header=["id", "person_id", "signed_up_at"],
            rows=[
                [1, person_ids["user-1"], "2024-12-29 09:00:00"],  # before window — first-ever anchor, excludes user-1
                [2, person_ids["user-1"], "2025-01-01 09:00:00"],
                [3, person_ids["user-2"], "2025-01-01 10:00:00"],
                [4, person_ids["user-3"], "2025-01-02 09:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "signed_up_at": "DateTime64(3, 'UTC')",
            },
        )

        for distinct_id, timestamp in [
            ("user-1", "2025-01-02T12:00:00Z"),  # user-1 is excluded by the anchor, regardless of returns
            ("user-2", "2025-01-02T12:00:00Z"),
            ("user-3", "2025-01-03T12:00:00Z"),
        ]:
            _create_event(team=self.team, event="$pageview", distinct_id=distinct_id, timestamp=timestamp)
        flush_persons_and_events()

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "retentionType": "retention_first_ever_occurrence",
                    "targetEntity": {
                        "id": signups_table_name,
                        "name": signups_table_name,
                        "type": "data_warehouse",
                        "table_name": signups_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "signed_up_at",
                    },
                    "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                },
            }
        )
        # user-2 cohorts day 0 (returns day 1), user-3 cohorts day 1 (returns day 2); user-1 excluded.
        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[1, 1, 0, 0], [1, 1, 0], [0, 0], [0], [0]]),
        )

    def test_retention_first_ever_events_start_dwh_return(self):
        # Cross-table: events start entity, data warehouse return entity. The first-ever anchor is resolved on the
        # events table (all time), so user-1 — whose first signup event is before the window — is excluded.
        person_ids = self._create_people()
        for distinct_id, timestamp in [
            ("user-1", "2024-12-29T09:00:00Z"),  # before window — first-ever anchor, excludes user-1
            ("user-1", "2025-01-01T09:00:00Z"),
            ("user-2", "2025-01-01T10:00:00Z"),
            ("user-3", "2025-01-02T09:00:00Z"),
        ]:
            _create_event(team=self.team, event="$user_signed_up", distinct_id=distinct_id, timestamp=timestamp)
        flush_persons_and_events()

        renewals_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_ever_renewals.csv",
            table_name="warehouse_first_ever_renewals",
            header=["id", "person_id", "renewed_at"],
            rows=[
                [1, person_ids["user-1"], "2025-01-02 12:00:00"],  # user-1 excluded by the anchor, regardless
                [2, person_ids["user-2"], "2025-01-02 12:00:00"],
                [3, person_ids["user-3"], "2025-01-03 12:00:00"],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "renewed_at": "DateTime64(3, 'UTC')",
            },
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "retentionType": "retention_first_ever_occurrence",
                    "targetEntity": {"id": "$user_signed_up", "name": "$user_signed_up", "type": "events"},
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
        # user-2 cohorts day 0 (returns day 1), user-3 cohorts day 1 (returns day 2); user-1 excluded.
        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[1, 1, 0, 0], [1, 1, 0], [0, 0], [0], [0]]),
        )

    def test_retention_first_time_vs_first_ever_dwh_property_aggregation_same_entity(self):
        # Property aggregation × first-time on a single data warehouse entity. user-1's first-ever purchase is
        # "basic" (not the "pro" the filter requires), so first_ever excludes them while first_time cohorts them
        # on their first "pro" purchase — and the per-interval aggregated amounts follow the chosen anchor.
        person_ids = self._create_people()
        purchases_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_time_purchases.csv",
            table_name="warehouse_first_time_purchases",
            header=["id", "person_id", "tier", "occurred_at", "amount"],
            rows=[
                [1, person_ids["user-1"], "basic", "2025-01-01 09:00:00", 10],  # first-ever row excludes user-1
                [2, person_ids["user-1"], "pro", "2025-01-02 09:00:00", 100],
                [3, person_ids["user-1"], "pro", "2025-01-03 09:00:00", 50],
                [4, person_ids["user-2"], "pro", "2025-01-01 10:00:00", 30],
                [5, person_ids["user-2"], "pro", "2025-01-02 10:00:00", 70],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "tier": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
                "amount": "Float64",
            },
        )

        def query_for(retention_type: str) -> dict[str, Any]:
            pro_entity = {
                "id": purchases_table_name,
                "name": purchases_table_name,
                "type": "data_warehouse",
                "table_name": purchases_table_name,
                "aggregation_target_field": "person_id",
                "timestamp_field": "occurred_at",
                "properties": [{"key": "tier", "value": "pro", "operator": "exact", "type": "data_warehouse"}],
            }
            return {
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "retentionType": retention_type,
                    "targetEntity": pro_entity,
                    "returningEntity": pro_entity,
                    "aggregationType": "sum",
                    "aggregationProperty": "amount",
                    "aggregationPropertyType": "data_warehouse",
                },
            }

        first_time_result = self.run_query(query=query_for("retention_first_time"))
        # user-2 cohorts day 0 (start value 30, returns 70 on day 1); user-1 cohorts day 1 (start value 100,
        # returns 50 on day 2).
        self.assertEqual(
            pluck(first_time_result, "values", "count"),
            pad([[1, 1, 0, 0], [1, 1, 0], [0, 0], [0], [0]]),
        )
        self.assertEqual(
            pluck(first_time_result, "values", "aggregation_value"),
            pad([[30, 70, 0, 0], [100, 50, 0], [0, 0], [0], [0]]),
        )

        first_ever_result = self.run_query(query=query_for("retention_first_ever_occurrence"))
        # user-1's first-ever purchase is "basic", so they are excluded; only user-2 cohorts (day 0).
        self.assertEqual(
            pluck(first_ever_result, "values", "count"),
            pad([[1, 1, 0, 0], [0, 0, 0], [0, 0], [0], [0]]),
        )
        self.assertEqual(
            pluck(first_ever_result, "values", "aggregation_value"),
            pad([[30, 70, 0, 0], [0, 0, 0], [0, 0], [0], [0]]),
        )

    def test_retention_first_time_dwh_property_aggregation_different_events(self):
        # first-time × property aggregation across two different events in the same table. Each user signs up
        # once, so first_time cohorts on that signup (identical cohorts to recurring) while the start event
        # contributes a zero-valued interval-0 marker and aggregated amounts come from the "payment" return rows.
        person_ids = self._create_people()
        activity_table_name = self._create_data_warehouse_table(
            filename="warehouse_first_time_agg_activity.csv",
            table_name="warehouse_first_time_agg_activity",
            header=["id", "person_id", "activity_type", "occurred_at", "amount"],
            rows=[
                [1, person_ids["user-1"], "signup", "2025-01-01 09:00:00", 0],
                [2, person_ids["user-1"], "payment", "2025-01-01 12:00:00", 50],
                [3, person_ids["user-1"], "payment", "2025-01-02 12:00:00", 100],
                [4, person_ids["user-2"], "payment", "2025-01-01 08:00:00", 999],
                [5, person_ids["user-2"], "signup", "2025-01-01 10:00:00", 0],
                [6, person_ids["user-2"], "payment", "2025-01-01 11:00:00", 30],
                [7, person_ids["user-3"], "signup", "2025-01-02 09:00:00", 0],
                [8, person_ids["user-3"], "payment", "2025-01-03 13:00:00", 200],
            ],
            table_columns={
                "id": "Int64",
                "person_id": "UUID",
                "activity_type": "String",
                "occurred_at": "DateTime64(3, 'UTC')",
                "amount": "Float64",
            },
        )

        result = self.run_query(
            query={
                "dateRange": {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-01-05T00:00:00Z"},
                "retentionFilter": {
                    "period": "Day",
                    "totalIntervals": 4,
                    "retentionType": "retention_first_time",
                    "targetEntity": {
                        "id": activity_table_name,
                        "name": activity_table_name,
                        "type": "data_warehouse",
                        "table_name": activity_table_name,
                        "aggregation_target_field": "person_id",
                        "timestamp_field": "occurred_at",
                        "properties": [
                            {"key": "activity_type", "value": "signup", "operator": "exact", "type": "data_warehouse"}
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
                            {"key": "activity_type", "value": "payment", "operator": "exact", "type": "data_warehouse"}
                        ],
                    },
                    "aggregationType": "sum",
                    "aggregationProperty": "amount",
                    "aggregationPropertyType": "data_warehouse",
                },
            }
        )
        # Each user signs up once → first_time cohorts identically to recurring (same values as the recurring
        # different-events aggregation test).
        self.assertEqual(
            pluck(result, "values", "count"),
            pad([[2, 1, 0, 0], [1, 1, 0], [0, 0], [0], [0]]),
        )
        self.assertEqual(
            pluck(result, "values", "aggregation_value"),
            pad([[80, 100, 0, 0], [0, 200, 0], [0, 0], [0], [0]]),
        )
