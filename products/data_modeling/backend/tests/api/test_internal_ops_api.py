from datetime import timedelta

from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from products.data_modeling.backend.models import DAG, DataModelingJob, DataWarehouseSavedQuery, Edge, Node, NodeType
from products.data_modeling.backend.tests.api.oidc import OidcAuthTestMixin, mint_oidc_token
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestInternalDataModelingOpsAPI(OidcAuthTestMixin, APIBaseTest):
    def _get(self, path: str, token: str | None = None):
        base = f"/api/projects/{self.team.id}/internal/data_modeling_ops"
        if token is not None:
            return self.client.get(f"{base}{path}", HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get(f"{base}{path}")

    def _token(self) -> str:
        return mint_oidc_token()

    # The client is session-logged-in (APIBaseTest), so the no-bearer row also proves
    # session auth cannot reach these routes.
    @parameterized.expand(
        [
            ("session_only_no_bearer", lambda: None),
            ("expired_token", lambda: mint_oidc_token(expiry_delta=timedelta(minutes=-1))),
            ("wrong_audience", lambda: mint_oidc_token(audience="some-other-client-id")),
            ("wrong_issuer", lambda: mint_oidc_token(issuer="https://evil.example.com")),
            ("unverified_email", lambda: mint_oidc_token(email_verified=False)),
            ("wrong_domain", lambda: mint_oidc_token(email="ops@example.com")),
        ]
    )
    def test_rejects_invalid_tokens(self, _name, token_factory):
        response = self._get("/overview", token_factory())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(DATA_MODELING_OPS_OIDC_SERVICE_ACCOUNT_EMAILS=["ops-bot@proj.iam.gserviceaccount.com"])
    def test_allow_listed_service_account_bypasses_domain_check(self):
        token = mint_oidc_token(email="ops-bot@proj.iam.gserviceaccount.com", email_verified=False)
        response = self._get("/overview", token)
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

        response = self._get("/overview", self._token())

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
