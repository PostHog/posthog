from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team

from products.data_modeling.backend.logic.fleet_ops import classify_migration
from products.data_modeling.backend.models import DAG, DataModelingJob, DataWarehouseSavedQuery, Node, NodeType
from products.data_modeling.backend.tests.api.oidc import OidcAuthTestMixin, mint_oidc_token

FLEET_BASE = "/api/internal/data_modeling_ops"
VIEWS = "products.data_modeling.backend.presentation.internal_fleet_views"


def _schedule(schedule_id: str, kind: str, team_id: int | None = None) -> dict:
    workflow = "data-modeling-run" if kind == "v1_saved_query" else "data-modeling-execute-dag"
    return {
        "schedule_id": schedule_id,
        "workflow_name": workflow,
        "kind": kind,
        "paused": False,
        "note": None,
        "next_run_at": None,
        "team_id": team_id,
        "search_attributes": {},
    }


class FleetOpsAPITestCase(OidcAuthTestMixin, APIBaseTest):
    def _get(self, path: str, token: str | None = None):
        if token is not None:
            return self.client.get(f"{FLEET_BASE}{path}", HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(f"{FLEET_BASE}{path}")

    def _fleet_token(self) -> str:
        return mint_oidc_token()


class TestFleetAuth(FleetOpsAPITestCase):
    # The client is session-logged-in (APIBaseTest); the no-bearer row proves a regular
    # logged-in user cannot reach the cross-team routes.
    @parameterized.expand(
        [
            ("session_only_no_bearer", lambda: None),
            ("expired_token", lambda: mint_oidc_token(expiry_delta=timedelta(minutes=-1))),
            ("wrong_domain", lambda: mint_oidc_token(email="someone@example.com")),
        ]
    )
    def test_rejects_invalid_tokens(self, _name, token_factory):
        response = self._get("/teams", token_factory())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestFleetTeams(FleetOpsAPITestCase):
    def test_teams_lists_only_modeling_activity_with_counts(self):
        DAG.objects.create(team=self.team, name="Default")
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="materialized_view",
            query={"query": "select 1"},
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=24),
        )
        Team.objects.create(organization=self.organization, name="no modeling here")

        response = self._get("/teams", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual([row["team_id"] for row in data["results"]], [self.team.id])
        row = data["results"][0]
        self.assertEqual(row["dag_count"], 1)
        self.assertEqual(row["saved_query_count"], 1)
        self.assertEqual(row["materialized_saved_query_count"], 1)
        self.assertEqual(row["saved_queries_with_sync_frequency_count"], 1)
        self.assertEqual(data["count"], 1)


class TestMigrationMatrix(FleetOpsAPITestCase):
    @patch(f"{VIEWS}._is_v2_backend_enabled_for_team", return_value=False)
    @patch(f"{VIEWS}.describe_schedules")
    def test_matrix_surfaces_v2_scheduled_flag_excluded_cohort(self, mock_describe, _mock_flag):
        dag = DAG.objects.create(team=self.team, name="Default")
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"query": "select 1"},
            sync_frequency_interval=timedelta(hours=24),
        )
        mock_describe.return_value = {
            str(dag.id): {"schedule_id": str(dag.id), "kind": "v2_dag", "exists": True},
        }

        response = self._get("/migration_matrix", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.json()["results"][0]
        self.assertFalse(row["switch_a_v2_flag_enabled"])
        self.assertTrue(row["switch_b_v2_schedule_present"])
        self.assertEqual(row["switch_c_sync_frequencies_remaining"], 1)
        self.assertEqual(row["classification"], "v2_scheduled_flag_excluded")

    @patch(f"{VIEWS}._is_v2_backend_enabled_for_team", return_value=True)
    @patch(f"{VIEWS}.describe_schedules", side_effect=RuntimeError("temporal down"))
    def test_matrix_leaves_classification_null_when_temporal_unreachable(self, _mock_describe, _mock_flag):
        DAG.objects.create(team=self.team, name="Default")
        DataWarehouseSavedQuery.objects.create(team=self.team, name="my_view", query={"query": "select 1"})

        response = self._get("/migration_matrix", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["temporal_error"], "temporal down")
        row = data["results"][0]
        self.assertIsNone(row["switch_b_v2_schedule_present"])
        self.assertIsNone(row["classification"])


class TestClassifyMigration(SimpleTestCase):
    @parameterized.expand(
        [
            (True, True, True, 0, "fully_v2"),
            (True, False, True, 0, "v2_scheduled_flag_excluded"),
            (True, True, True, 3, "v2_scheduled_cleanup_pending"),
            (True, True, False, 2, "not_migrated"),
            (True, False, False, 2, "v1_flag_excluded"),
            (False, True, False, 0, "no_dags"),
        ]
    )
    def test_labels(self, has_dags, flag, schedule, remaining, expected):
        self.assertEqual(
            classify_migration(
                has_dags=has_dags,
                v2_flag_enabled=flag,
                v2_schedule_present=schedule,
                sync_frequencies_remaining=remaining,
            ),
            expected,
        )


class TestOrphans(FleetOpsAPITestCase):
    @patch(f"{VIEWS}.list_data_modeling_schedules")
    def test_reports_both_orphan_directions(self, mock_list):
        dag = DAG.objects.create(team=self.team, name="Default")
        covered_by_dag = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="covered_view", query={"query": "select 1"}, is_materialized=True
        )
        Node.objects.create(team=self.team, dag=dag, saved_query=covered_by_dag, type=NodeType.MAT_VIEW)
        unscheduled = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="unscheduled_view", query={"query": "select 1"}, is_materialized=True
        )
        deleted = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="deleted_view", query={"query": "select 1"}, deleted=True
        )
        mock_list.return_value = [
            _schedule(str(dag.id), "v2_dag", self.team.id),
            _schedule(str(deleted.id), "v1_saved_query", self.team.id),
            _schedule("0197aaaa-0000-0000-0000-000000000000", "v2_dag"),
        ]

        response = self._get("/orphans", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        orphaned_ids = {entry["schedule_id"] for entry in data["schedules_without_entity"]}
        self.assertEqual(orphaned_ids, {str(deleted.id), "0197aaaa-0000-0000-0000-000000000000"})
        unscheduled_ids = {entry["saved_query_id"] for entry in data["entities_without_schedule"]}
        self.assertEqual(unscheduled_ids, {str(unscheduled.id)})

    @patch(f"{VIEWS}.list_data_modeling_schedules", side_effect=RuntimeError("temporal down"))
    def test_returns_503_when_temporal_unreachable(self, _mock_list):
        response = self._get("/orphans", self._fleet_token())
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


class TestFailingSchedules(FleetOpsAPITestCase):
    @patch(f"{VIEWS}.list_data_modeling_schedules")
    def test_per_engine_streaks_grouped_under_covering_schedule(self, mock_list):
        dag = DAG.objects.create(team=self.team, name="Default")
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="failing_view",
            query={"query": "select 1"},
            status=DataWarehouseSavedQuery.Status.FAILED,
            latest_error="boom",
        )
        Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.MAT_VIEW)
        # Oldest to newest: ch FAILED / ch COMPLETED / duck FAILED / ch FAILED / ch FAILED / ch RUNNING.
        for engine, job_status in [
            (DataModelingJob.Engine.CLICKHOUSE, DataModelingJob.Status.FAILED),
            (DataModelingJob.Engine.CLICKHOUSE, DataModelingJob.Status.COMPLETED),
            (DataModelingJob.Engine.DUCKGRES, DataModelingJob.Status.FAILED),
            (DataModelingJob.Engine.CLICKHOUSE, DataModelingJob.Status.FAILED),
            (DataModelingJob.Engine.CLICKHOUSE, DataModelingJob.Status.FAILED),
            (DataModelingJob.Engine.CLICKHOUSE, DataModelingJob.Status.RUNNING),
        ]:
            DataModelingJob.objects.create(team=self.team, saved_query=saved_query, engine=engine, status=job_status)
        mock_list.return_value = [_schedule(str(dag.id), "v2_dag", self.team.id)]

        response = self._get("/failing_schedules", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["failing_saved_query_count"], 1)
        group = data["results"][0]
        self.assertEqual(group["schedule_id"], str(dag.id))
        self.assertEqual(group["schedule_kind"], "v2_dag")
        affected = group["affected_saved_queries"][0]
        self.assertEqual(affected["saved_query_id"], str(saved_query.id))
        self.assertEqual(affected["latest_error"], "boom")
        self.assertEqual(affected["consecutive_failures_by_engine"], {"clickhouse": 2, "duckgres": 1})


class TestDuplicates(FleetOpsAPITestCase):
    def test_reports_multi_dag_saved_queries(self):
        dag_a = DAG.objects.create(team=self.team, name="A")
        dag_b = DAG.objects.create(team=self.team, name="B")
        doubled = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="doubled_view", query={"query": "select 1"}, is_materialized=True
        )
        single = DataWarehouseSavedQuery.objects.create(team=self.team, name="single_view", query={"query": "select 1"})
        Node.objects.create(team=self.team, dag=dag_a, saved_query=doubled, type=NodeType.MAT_VIEW)
        Node.objects.create(team=self.team, dag=dag_b, saved_query=doubled, type=NodeType.MAT_VIEW)
        Node.objects.create(team=self.team, dag=dag_a, saved_query=single, type=NodeType.VIEW)

        response = self._get("/duplicates", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual([entry["saved_query_id"] for entry in data["multi_dag_saved_queries"]], [str(doubled.id)])
        self.assertEqual(
            {dag_entry["dag_name"] for dag_entry in data["multi_dag_saved_queries"][0]["dags"]}, {"A", "B"}
        )

    def test_reports_duplicate_backing_tables_with_linked_flag(self):
        from products.warehouse_sources.backend.facade.models import DataWarehouseTable

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select 1"}
        )
        linked = DataWarehouseTable.objects.create(
            team=self.team, name="my_view", format="Parquet", url_pattern="s3://bucket/linked"
        )
        DataWarehouseTable.objects.create(
            team=self.team, name="my_view", format="Parquet", url_pattern="s3://bucket/orphan"
        )
        saved_query.table = linked
        saved_query.save()

        response = self._get("/duplicates", self._fleet_token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        groups = response.json()["duplicate_backing_tables"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["saved_query_id"], str(saved_query.id))
        by_url = {table["url_pattern"]: table for table in groups[0]["tables"]}
        self.assertTrue(by_url["s3://bucket/linked"]["is_linked"])
        self.assertFalse(by_url["s3://bucket/orphan"]["is_linked"])
