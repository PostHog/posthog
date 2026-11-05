from datetime import UTC, datetime, timedelta
from uuid import UUID

import time_machine

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.presentation.views.usage import ModelUsageQuerySerializer
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin


class TestModelUsageValidation(SimpleTestCase):
    @parameterized.expand([("days", 0), ("days", 91), ("page", 0), ("page_size", 101)])
    def test_rejects_out_of_bounds(self, field: str, value: int) -> None:
        serializer = ModelUsageQuerySerializer(data={field: value})
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    @parameterized.expand([("engine", "duckgres"), ("sort_by", "saved_query__team_id"), ("sort_direction", "up")])
    def test_rejects_unknown_choice(self, field: str, value: str) -> None:
        serializer = ModelUsageQuerySerializer(data={field: value})
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    @parameterized.expand(
        [
            ({"days": 7, "date_from": "2026-10-01"},),
            ({"date_to": "2026-10-10"},),
            ({"date_from": "2026-10-10", "date_to": "2026-10-01"},),
            ({"date_from": "2025-10-01", "date_to": "2026-10-02"},),
        ]
    )
    @time_machine.travel("2026-10-16T12:00:00Z", tick=False)
    def test_rejects_invalid_custom_date_range(self, query: dict[str, object]) -> None:
        serializer = ModelUsageQuerySerializer(data=query)
        self.assertFalse(serializer.is_valid())

    @time_machine.travel("2026-10-16T12:00:00Z", tick=False)
    def test_accepts_custom_date_range(self) -> None:
        serializer = ModelUsageQuerySerializer(data={"date_from": "2026-10-01", "date_to": "2026-10-15"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"].isoformat(), "2026-10-01")
        self.assertEqual(serializer.validated_data["end_date"].isoformat(), "2026-10-16")

    @time_machine.travel("2026-10-16T12:00:00Z", tick=False)
    def test_resolves_relative_date_range(self) -> None:
        serializer = ModelUsageQuerySerializer(data={"days": 7})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"].isoformat(), "2026-10-09")
        self.assertEqual(serializer.validated_data["end_date"].isoformat(), "2026-10-16")

    @time_machine.travel("2026-10-16T12:00:00Z", tick=False)
    def test_accepts_maximum_end_date_without_overflow(self) -> None:
        serializer = ModelUsageQuerySerializer(data={"date_from": "2026-10-01", "date_to": "9999-12-31"})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_normalizes_legacy_saved_query_id(self) -> None:
        saved_query_id = UUID(int=1)
        serializer = ModelUsageQuerySerializer(data={"saved_query_id": str(saved_query_id)})

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["saved_query_ids"], [saved_query_id])

    def test_rejects_single_and_multiple_saved_query_filters(self) -> None:
        saved_query_id = UUID(int=1)
        serializer = ModelUsageQuerySerializer(
            data={"saved_query_id": str(saved_query_id), "saved_query_ids": str(saved_query_id)}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("saved_query_id", serializer.errors)


@time_machine.travel("2026-10-16T12:00:00Z", tick=False)
class TestModelUsage(WarehouseAccessControlTestMixin):
    resource = "warehouse_objects"

    def test_usage_is_scoped_and_preserves_unknown_cost(self) -> None:
        model = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="daily_orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        measured = {
            "read_bytes": 1024,
            "read_rows": 100,
            "cpu_microseconds": 2_000_000,
            "query_count": 3,
            "usage_updated_at": finished,
        }
        base = {"team": self.team, "saved_query": model, "status": "Completed", "last_run_at": finished}
        DataModelingJob.objects.create(**base, **measured)
        DataModelingJob.objects.create(
            **{**base, "status": "Failed", "last_run_at": finished + timedelta(seconds=1)}, error="Query failed"
        )
        DataModelingJob.objects.create(**{**base, "status": "Running"}, **measured)
        managed = DataModelingJob.objects.create(
            **{**base, "engine": "managed_warehouse"}, read_bytes=4096, usage_updated_at=finished
        )
        DataModelingJob.objects.create(**{**base, "last_run_at": finished + timedelta(days=1)}, **measured)
        other_team = Team.objects.create(organization=self.organization)
        DataModelingJob.objects.create(team=other_team, status="Completed", last_run_at=finished, **measured)
        result = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 7})
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(
            data["overview"],
            {
                "runs": 2,
                "measured_runs": 1,
                "read_bytes": 1024,
                "read_rows": 100,
                "cpu_microseconds": 2_000_000,
                "query_count": 3,
            },
        )
        self.assertEqual(len(data["trends"]), 7)
        self.assertIsNone(data["trends"][0]["read_bytes"])
        self.assertEqual(data["trends"][-1]["runs"], 2)
        self.assertEqual(data["trends"][-1]["engines"][0]["engine"], "clickhouse")
        self.assertEqual(data["models"][0]["name"], "daily_orders")
        self.assertEqual(data["count"], 1)
        self.assertEqual(
            data["status_breakdown"],
            [
                {
                    "engine": "clickhouse",
                    "status": "Failed",
                    "count": 1,
                    "models": [
                        {
                            "saved_query_id": str(model.id),
                            "name": "daily_orders",
                            "deleted": False,
                        }
                    ],
                }
            ],
        )

        combined = self.client.get(
            f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 7, "engine": "all"}
        ).json()
        self.assertEqual(combined["overview"]["runs"], 3)
        self.assertEqual(combined["overview"]["measured_runs"], 2)
        self.assertEqual(combined["overview"]["read_bytes"], 5120)
        self.assertEqual(
            [(item["engine"], item["runs"]) for item in combined["trends"][-1]["engines"]],
            [("clickhouse", 2), ("managed_warehouse", 1)],
        )
        self.assertEqual(
            [(item["engine"], item["read_bytes"]) for item in combined["models"][0]["engines"]],
            [("clickhouse", 1024), ("managed_warehouse", managed.read_bytes)],
        )
        self.assertEqual(
            combined["status_breakdown"],
            [
                {
                    "engine": "clickhouse",
                    "status": "Failed",
                    "count": 1,
                    "models": [
                        {
                            "saved_query_id": str(model.id),
                            "name": "daily_orders",
                            "deleted": False,
                        }
                    ],
                },
                {
                    "engine": "managed_warehouse",
                    "status": "Completed",
                    "count": 1,
                    "models": [
                        {
                            "saved_query_id": str(model.id),
                            "name": "daily_orders",
                            "deleted": False,
                        }
                    ],
                },
            ],
        )

        managed_only = self.client.get(
            f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 7, "engine": "managed_warehouse"}
        ).json()
        self.assertEqual(managed_only["overview"]["runs"], 1)
        self.assertEqual(managed_only["overview"]["read_bytes"], 4096)
        self.assertEqual([item["engine"] for item in managed_only["models"][0]["engines"]], ["managed_warehouse"])

        second_model = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="weekly_orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=second_model,
            status="Completed",
            last_run_at=finished,
            read_bytes=2048,
            usage_updated_at=finished,
        )
        filtered = self.client.get(
            f"/api/projects/{self.team.id}/data_modeling_usage/",
            {"days": 7, "engine": "all", "saved_query_ids": f"{model.id},{second_model.id}"},
        ).json()
        self.assertEqual(filtered["count"], 2)
        self.assertEqual(
            {row["saved_query_id"] for row in filtered["models"]},
            {str(model.id), str(second_model.id)},
        )
        legacy_filtered = self.client.get(
            f"/api/projects/{self.team.id}/data_modeling_usage/",
            {"days": 7, "engine": "all", "saved_query_id": str(second_model.id)},
        ).json()
        self.assertEqual(legacy_filtered["count"], 1)
        self.assertEqual(legacy_filtered["models"][0]["saved_query_id"], str(second_model.id))
        invalid = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 91})
        self.assertEqual(invalid.status_code, 400)

    def test_status_breakdown_includes_a_model_without_finished_runs(self) -> None:
        model = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="running_model", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=model,
            status="Running",
            last_run_at=datetime(2026, 10, 15, 20, tzinfo=UTC),
        )

        data = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 7}).json()

        self.assertEqual(data["overview"]["runs"], 0)
        self.assertEqual(data["status_breakdown"][0]["status"], "Running")
        self.assertEqual(data["status_breakdown"][0]["count"], 1)
        self.assertEqual(data["status_breakdown"][0]["models"][0]["name"], "running_model")

    def test_model_breakdown_paginates_without_changing_totals(self) -> None:
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        model_ids = []
        for index, value in enumerate([0, 1000, 1000, None]):
            model = DataWarehouseSavedQuery.objects.create(
                id=UUID(int=index + 1),
                team=self.team,
                name=f"model_{index}",
                query={"kind": "HogQLQuery", "query": "SELECT 1"},
                deleted=index == 1,
            )
            model_ids.append(str(model.id))
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=model,
                status="Completed",
                last_run_at=finished,
                read_bytes=value,
                usage_updated_at=finished if value is not None else None,
            )
        results = [
            self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"page": page, "page_size": 1}).json()
            for page in [1, 2, 3, 4]
        ]
        self.assertEqual([data["models"][0]["read_bytes"] for data in results], [1000, 1000, 0, None])
        self.assertEqual(
            [data["models"][0]["saved_query_id"] for data in results],
            [model_ids[index] for index in [1, 2, 0, 3]],
        )
        self.assertTrue(results[0]["models"][0]["deleted"])
        self.assertEqual([data["overview"]["read_bytes"] for data in results], [2000] * 4)
        self.assertEqual([data["count"] for data in results], [4] * 4)

    def test_sorts_all_columns_before_pagination(self) -> None:
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        for index, name in enumerate(["zebra", "Alpha", "beta", ""]):
            model = DataWarehouseSavedQuery.objects.create(team=self.team, name=name)
            for engine, read_bytes in [
                ("clickhouse", [10, 30, 20, None][index]),
                ("managed_warehouse", [60, 10, 25, None][index]),
            ]:
                DataModelingJob.objects.create(
                    team=self.team,
                    saved_query=model,
                    engine=engine,
                    status="Completed",
                    last_run_at=finished,
                    read_bytes=read_bytes,
                    cpu_microseconds=[200, 100, 300, None][index],
                    usage_updated_at=finished if read_bytes is not None else None,
                )
            for _ in range(index):
                DataModelingJob.objects.create(team=self.team, saved_query=model, status="Failed", last_run_at=finished)

        ascending = {
            "name": ["Alpha", "beta", "Deleted model", "zebra"],
            "read_bytes": ["Alpha", "beta", "zebra", "Deleted model"],
            "clickhouse_read_bytes": ["zebra", "beta", "Alpha", "Deleted model"],
            "managed_warehouse_read_bytes": ["Alpha", "beta", "zebra", "Deleted model"],
            "cpu_microseconds": ["Alpha", "zebra", "beta", "Deleted model"],
            "runs": ["zebra", "Alpha", "beta", "Deleted model"],
        }
        for sort_by, names in ascending.items():
            for direction in ["asc", "desc"]:
                expected = (
                    names
                    if direction == "asc"
                    else (
                        list(reversed(names))
                        if sort_by in ["name", "runs"]
                        else [*reversed(names[:-1]), "Deleted model"]
                    )
                )
                with self.subTest(sort_by=sort_by, direction=direction):
                    results = [
                        self.client.get(
                            f"/api/projects/{self.team.id}/data_modeling_usage/",
                            {
                                "engine": "all",
                                "sort_by": sort_by,
                                "sort_direction": direction,
                                "page_size": 2,
                                "page": page,
                            },
                        ).json()
                        for page in [1, 2]
                    ]
                    self.assertEqual([row["name"] for data in results for row in data["models"]], expected)
                    self.assertEqual(results[0]["overview"], results[1]["overview"])

    def test_custom_date_range_is_inclusive_and_excludes_today(self) -> None:
        model = DataWarehouseSavedQuery.objects.create(team=self.team, name="custom_range")
        for day in [9, 10, 12, 13, 16]:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=model,
                status="Completed",
                last_run_at=datetime(2026, 10, day, 12, tzinfo=UTC),
            )

        result = self.client.get(
            f"/api/projects/{self.team.id}/data_modeling_usage/",
            {"date_from": "2026-10-10", "date_to": "2026-10-12"},
        )

        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(data["date_from"], "2026-10-10")
        self.assertEqual(data["date_to"], "2026-10-13")
        self.assertEqual(data["overview"]["runs"], 2)
        self.assertEqual([day["runs"] for day in data["trends"]], [1, 0, 1])

    def test_denies_warehouse_access(self) -> None:
        self._create_project_default(access_level="none")
        self.client.force_login(self.no_access_user)
        result = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/")
        self.assertEqual(result.status_code, 403)

    @parameterized.expand([(False,), (True,)])
    def test_usage_totals_follow_saved_query_access(self, explicit_grant: bool) -> None:
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        visible = DataWarehouseSavedQuery.objects.create(team=self.team, name="visible_model")
        restricted = DataWarehouseSavedQuery.objects.create(team=self.team, name="restricted_model")
        if explicit_grant:
            self._create_project_default(access_level="none")
            self._create_access_control(
                self.viewer_user, resource="warehouse_view", resource_id=str(visible.id), access_level="viewer"
            )
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(restricted.id), access_level="none"
        )
        for model, read_bytes in [(visible, 100), (restricted, 900)]:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=model,
                status="Completed",
                last_run_at=finished,
                read_bytes=read_bytes,
                usage_updated_at=finished,
            )
        self.client.force_login(self.viewer_user)
        result = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/")
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(data["overview"]["read_bytes"], 100)
        self.assertEqual(data["overview"]["runs"], 1)
        self.assertEqual(data["trends"][-1]["read_bytes"], 100)
        self.assertEqual(data["count"], 1)
        self.assertEqual(
            [(group["engine"], group["status"], group["count"]) for group in data["status_breakdown"]],
            [("clickhouse", "Completed", 1)],
        )
        self.assertEqual(
            [model["saved_query_id"] for model in data["status_breakdown"][0]["models"]], [str(visible.id)]
        )
        self.assertEqual([row["saved_query_id"] for row in data["models"]], [str(visible.id)])
