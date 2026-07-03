from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from products.data_modeling.backend.logic.schedule_truth import extract_schedule_info
from products.data_modeling.backend.models import DAG, DataModelingJob, DataWarehouseSavedQuery, Edge, Node, NodeType
from products.data_modeling.backend.tests.api.oidc import OidcAuthTestMixin, mint_oidc_token
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class InternalOpsAPITestCase(OidcAuthTestMixin, APIBaseTest):
    def _get(self, path: str, token: str | None = None):
        base = "/api/internal/data_modeling_ops"
        if token is not None:
            return self.client.get(f"{base}{path}", HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(f"{base}{path}")

    def _token(self) -> str:
        return mint_oidc_token()


class TestInternalDataModelingOpsAPI(InternalOpsAPITestCase):
    # The client is session-logged-in (APIBaseTest), so the no-bearer row also proves
    # session auth cannot reach these routes.
    

    
    

    

    
    @parameterized.expand(
        [
            ("session_only_no_bearer", lambda: None),
            ("expired_token", lambda: mint_oidc_token(expiry_delta=timedelta(minutes=-1))),
            ("wrong_audience", lambda: mint_oidc_token(audience="some-other-client-id")),
            ("wrong_issuer", lambda: mint_oidc_token(issuer="https://evil.example.com")),
            ("unverified_email", lambda: mint_oidc_token(email_verified=False)),
            ("wrong_email_domain", lambda: mint_oidc_token(email="ops@example.com")),
            # A consumer Google account can verify an address on our domain but carries no
            # hosted-domain claim, so Workspace offboarding would never revoke it.
            ("missing_hosted_domain", lambda: mint_oidc_token(hosted_domain=None)),
            ("wrong_hosted_domain", lambda: mint_oidc_token(hosted_domain="example.com")),
        ]
    )
    def test_rejects_invalid_tokens(self, _name, token_factory):
        response = self._get(f"/teams/{self.team.id}", token_factory())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(DATA_MODELING_OPS_OIDC_SERVICE_ACCOUNT_EMAILS=["ops-bot@proj.iam.gserviceaccount.com"])
    def test_allow_listed_service_account_bypasses_domain_check(self):
        token = mint_oidc_token(email="ops-bot@proj.iam.gserviceaccount.com", email_verified=False, hosted_domain=None)
        response = self._get(f"/teams/{self.team.id}", token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_overview_counts(self):
        dag = DAG.objects.create(team=self.team, name="Default")
        materialized = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="materialized_view",
            query={"query": "select 1"},
            is_materialized=True,
            sync_frequency_interval=timedelta(hours=24),
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="failing_view",
            query={"query": "select 1"},
            status=DataWarehouseSavedQuery.Status.FAILED,
        )
        Node.objects.create(team=self.team, dag=dag, saved_query=materialized, type=NodeType.MAT_VIEW)

        response = self._get(f"/teams/{self.team.id}", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["team_id"], self.team.id)
        self.assertEqual(data["dag_count"], 1)
        self.assertEqual(data["node_count"], 1)
        self.assertEqual(data["saved_query_count"], 2)
        self.assertEqual(data["materialized_saved_query_count"], 1)
        self.assertEqual(data["failing_saved_query_count"], 1)
        self.assertEqual(data["saved_queries_with_sync_frequency_count"], 1)

    def test_saved_query_detail_surfaces_duplicate_backing_tables_and_dag_context(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select * from events"}
        )
        linked = DataWarehouseTable.objects.create(
            team=self.team, name="my_view", format="Parquet", url_pattern="s3://bucket/linked"
        )
        orphan = DataWarehouseTable.objects.create(
            team=self.team, name="my_view", format="Parquet", url_pattern="s3://bucket/orphan"
        )
        saved_query.table = linked
        saved_query.save()

        dag = DAG.objects.create(team=self.team, name="Default")
        node = Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.MAT_VIEW)
        events_table = Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)
        Edge.objects.create(team=self.team, dag=dag, source=events_table, target=node)

        response = self._get(f"/saved_queries/{saved_query.id}", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["query"], {"query": "select * from events"})
        backing_by_url = {t["url_pattern"]: t for t in data["backing_tables"]}
        self.assertEqual(len(backing_by_url), 2)
        self.assertTrue(backing_by_url["s3://bucket/linked"]["is_linked"])
        self.assertFalse(backing_by_url["s3://bucket/orphan"]["is_linked"])
        self.assertEqual(str(orphan.id), backing_by_url["s3://bucket/orphan"]["id"])
        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(data["nodes"][0]["dag_name"], "Default")
        self.assertEqual(data["nodes"][0]["upstream"], ["events"])
        self.assertFalse(data["double_materialized"])

    def test_saved_queries_rejects_unknown_status_filter(self):
        response = self._get("/saved_queries?status=Failing", self._token())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_integer_team_id_filter(self):
        response = self._get("/saved_queries?team_id=abc", self._token())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand([("saved_queries", "saved_queries", "view"), ("dags", "dags", "dag")])
    def test_team_id_filter_narrows_otherwise_fleet_wide_list(self, _name, resource, prefix):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        for team in (self.team, other_team):
            DataWarehouseSavedQuery.objects.create(team=team, name=f"view_{team.id}", query={"query": "select 1"})
            DAG.objects.create(team=team, name=f"dag_{team.id}")

        unfiltered = self._get(f"/{resource}", self._token()).json()["results"]
        filtered = self._get(f"/{resource}?team_id={self.team.id}", self._token()).json()["results"]

        self.assertEqual(len(unfiltered), 2)
        self.assertEqual([row["name"] for row in filtered], [f"{prefix}_{self.team.id}"])

    def test_jobs_expose_engine_and_storage_including_duckgres(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select 1"}
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.COMPLETED,
            engine=DataModelingJob.Engine.DUCKGRES,
            storage_delta_mib=12.5,
            rows_materialized=100,
        )

        response = self._get(f"/saved_queries/{saved_query.id}/jobs", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["engine"], "duckgres")
        self.assertEqual(results[0]["storage_delta_mib"], 12.5)

    def test_jobs_returns_404_for_malformed_saved_query_id(self):
        response = self._get("/saved_queries/not-a-uuid/jobs", self._token())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand([("detail", ""), ("jobs", "/jobs")])
    def test_soft_deleted_saved_query_is_not_readable_by_id(self, _name, suffix):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="deleted_view", query={"query": "select 1"}, deleted=True
        )
        response = self._get(f"/saved_queries/{saved_query.id}{suffix}", self._token())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_dag_detail_returns_nodes_and_edges(self):
        dag = DAG.objects.create(team=self.team, name="Default")
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select 1"}
        )
        node = Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.VIEW)
        events_table = Node.objects.create(team=self.team, dag=dag, name="events", type=NodeType.TABLE)
        Edge.objects.create(team=self.team, dag=dag, source=events_table, target=node)

        response = self._get(f"/dags/{dag.id}", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["dag"]["name"], "Default")
        self.assertEqual(data["dag"]["node_count"], 2)
        self.assertEqual({n["name"] for n in data["nodes"]}, {"events", "my_view"})
        self.assertEqual(len(data["edges"]), 1)
        self.assertEqual(data["edges"][0]["source_id"], str(events_table.id))


def _fake_schedule_description(workflow: str, dag_attr: str | None = None):
    spec = SimpleNamespace(
        intervals=[SimpleNamespace(every=timedelta(hours=24))],
        cron_expressions=[],
        calendars=[],
        jitter=None,
        time_zone_name=None,
    )
    attrs = []
    if dag_attr:
        attrs.append(SimpleNamespace(key=SimpleNamespace(name="PostHogDagId"), value=dag_attr))
    return SimpleNamespace(
        schedule=SimpleNamespace(
            action=SimpleNamespace(workflow=workflow),
            spec=spec,
            state=SimpleNamespace(paused=True, note="paused by ops"),
        ),
        info=SimpleNamespace(
            next_action_times=[datetime(2026, 7, 4, 12, 0, tzinfo=UTC)],
            recent_actions=[
                SimpleNamespace(
                    scheduled_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
                    started_at=datetime(2026, 7, 3, 12, 0, 5, tzinfo=UTC),
                    action=SimpleNamespace(workflow_id="data-modeling-run-abc", first_execution_run_id="run-1"),
                )
            ],
        ),
        typed_search_attributes=SimpleNamespace(search_attributes=attrs),
    )


class TestExtractScheduleInfo(SimpleTestCase):
    def test_classifies_by_workflow_name_even_when_dag_attribute_present(self):
        description = _fake_schedule_description("data-modeling-run", dag_attr="0198-some-dag")

        info = extract_schedule_info("0197-some-saved-query", description)

        self.assertEqual(info["kind"], "v1_saved_query")
        self.assertEqual(info["search_attributes"], {"PostHogDagId": "0198-some-dag"})
        self.assertTrue(info["paused"])
        self.assertEqual(info["note"], "paused by ops")
        self.assertEqual(info["next_run_at"], "2026-07-04T12:00:00+00:00")
        self.assertEqual(info["spec"]["intervals"], ["1 day, 0:00:00"])
        self.assertEqual(info["recent_actions"][0]["workflow_id"], "data-modeling-run-abc")


class TestInternalSchedulesAPI(InternalOpsAPITestCase):
    @patch("products.data_modeling.backend.presentation.internal_views.describe_schedules")
    def test_schedules_keeps_unscheduled_materialized_entities_visible(self, mock_describe):
        dag = DAG.objects.create(team=self.team, name="Default")
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select 1"}, is_materialized=True
        )
        mock_describe.return_value = {
            str(dag.id): extract_schedule_info(str(dag.id), _fake_schedule_description("data-modeling-execute-dag")),
            str(saved_query.id): None,
        }

        response = self._get("/schedules", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_entity = {r["entity_id"]: r for r in response.json()["results"]}
        self.assertEqual(set(by_entity), {str(dag.id), str(saved_query.id)})
        self.assertEqual(by_entity[str(dag.id)]["schedule"]["kind"], "v2_dag")
        self.assertIsNone(by_entity[str(saved_query.id)]["schedule"])
        self.assertFalse(response.json()["truncated"])

    @patch("products.data_modeling.backend.presentation.internal_views.describe_schedules")
    def test_detail_reports_v2_coverage_from_dag_schedule(self, mock_describe):
        dag = DAG.objects.create(team=self.team, name="Default")
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select 1"}, is_materialized=True
        )
        Node.objects.create(team=self.team, dag=dag, saved_query=saved_query, type=NodeType.MAT_VIEW)
        mock_describe.return_value = {
            str(saved_query.id): None,
            str(dag.id): extract_schedule_info(str(dag.id), _fake_schedule_description("data-modeling-execute-dag")),
        }

        response = self._get(f"/saved_queries/{saved_query.id}", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        truth = response.json()["schedule_truth"]
        self.assertEqual(truth["covered_by"], "v2")
        self.assertIsNone(truth["v1_schedule"])
        self.assertEqual(truth["dag_schedules"][0]["schedule"]["kind"], "v2_dag")

    @patch("products.data_modeling.backend.presentation.internal_views.describe_schedules")
    def test_detail_survives_temporal_outage(self, mock_describe):
        mock_describe.side_effect = RuntimeError("temporal unreachable")
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="my_view", query={"query": "select 1"}
        )

        response = self._get(f"/saved_queries/{saved_query.id}", self._token())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["schedule_truth"], {"error": "temporal unreachable"})
