from freezegun import freeze_time
from posthog.models.project import Project
from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema
import uuid
from unittest.mock import patch
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from django.test import override_settings
from django.conf import settings
from posthog.models import Team
import psycopg
from rest_framework import status


from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import sync_frequency_interval_to_sync_frequency


class TestExternalDataSource(APIBaseTest):
    def _create_external_data_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="test",
            job_inputs={
                "stripe_secret_key": "sk_test_123",
            },
        )

    def _create_external_data_schema(self, source_id) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source_id, table=None
        )

    def test_create_external_data_source(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Charge", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        payload = response.json()

        self.assertEqual(response.status_code, 201)
        # number of schemas should match default schemas for Stripe
        self.assertEqual(
            ExternalDataSchema.objects.filter(source_id=payload["id"]).count(),
            len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[ExternalDataSource.Type.STRIPE]),
        )

    def test_create_external_data_source_delete_on_missing_schemas(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": False,
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    def test_create_external_data_source_delete_on_bad_schema(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "SomeOtherSchema", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    def test_prefix_external_data_source(self):
        # Create no prefix

        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Charge", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 201)

        # Try to create same type without prefix again

        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Charge", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Source type already exists. Prefix is required"})

        # Create with prefix
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Charge", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
                "prefix": "test_",
            },
        )

        self.assertEqual(response.status_code, 201)

        # Try to create same type with same prefix again
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Subscription", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Customer", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Product", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Price", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Invoice", "should_sync": True, "sync_type": "full_refresh"},
                        {"name": "Charge", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
                "prefix": "test_",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Prefix already exists"})

    def test_create_external_data_source_incremental(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": "BalanceTransaction",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Subscription",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Customer",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Product",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Price",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Invoice",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Charge",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_create_external_data_source_incremental_missing_field(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": "BalanceTransaction",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Subscription",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Customer",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Product",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Price",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Invoice",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": "Charge",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                    ],
                },
            },
        )
        assert response.status_code == 400
        assert len(ExternalDataSource.objects.all()) == 0

    def test_create_external_data_source_incremental_missing_type(self):
        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": "BalanceTransaction",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": "Subscription",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": "Customer",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": "Product",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": "Price",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": "Invoice",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": "Charge",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                    ],
                },
            },
        )
        assert response.status_code == 400
        assert len(ExternalDataSource.objects.all()) == 0

    def test_list_external_data_source(self):
        self._create_external_data_source()
        self._create_external_data_source()

        with self.assertNumQueries(17):
            response = self.client.get(f"/api/projects/{self.team.pk}/external_data_sources/")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 2)

    def test_get_external_data_source_with_schema(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.get(f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertListEqual(
            list(payload.keys()),
            [
                "id",
                "created_at",
                "created_by",
                "status",
                "source_type",
                "prefix",
                "last_run_at",
                "schemas",
            ],
        )
        self.assertEqual(
            payload["schemas"],
            [
                {
                    "id": str(schema.pk),
                    "incremental": False,
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "last_synced_at": schema.last_synced_at,
                    "name": schema.name,
                    "should_sync": schema.should_sync,
                    "latest_error": schema.latest_error,
                    "status": schema.status,
                    "sync_type": schema.sync_type,
                    "table": schema.table,
                    "sync_frequency": sync_frequency_interval_to_sync_frequency(schema),
                }
            ],
        )

    def test_delete_external_data_source(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.delete(f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204

        assert ExternalDataSource.objects.filter(pk=source.pk, deleted=True).exists()
        assert ExternalDataSchema.objects.filter(pk=schema.pk, deleted=True).exists()

    # TODO: update this test
    @patch("posthog.warehouse.api.external_data_source.trigger_external_data_source_workflow")
    def test_reload_external_data_source(self, mock_trigger):
        source = self._create_external_data_source()

        response = self.client.post(f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}/reload/")

        source.refresh_from_db()

        self.assertEqual(mock_trigger.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(source.status, "Running")

    def test_database_schema(self):
        postgres_connection = psycopg.connect(
            host=settings.PG_HOST,
            port=settings.PG_PORT,
            dbname=settings.PG_DATABASE,
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
        )

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS posthog_test (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(50)
                );
                """
            )

            postgres_connection.commit()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_sources/database_schema/",
            data={
                "source_type": "Postgres",
                "host": settings.PG_HOST,
                "port": int(settings.PG_PORT),
                "dbname": settings.PG_DATABASE,
                "user": settings.PG_USER,
                "password": settings.PG_PASSWORD,
                "schema": "public",
            },
        )
        results = response.json()

        self.assertEqual(response.status_code, 200)

        table_names = [table["table"] for table in results]
        self.assertTrue("posthog_test" in table_names)

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                DROP TABLE posthog_test;
                """
            )
            postgres_connection.commit()

        postgres_connection.close()

    def test_database_schema_stripe_credentials(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True

            response = self.client.post(
                f"/api/projects/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "client_secret": "blah",
                    "account_id": "blah",
                },
            )

            assert response.status_code == 200

    def test_database_schema_stripe_credentials_sad_path(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = False

            response = self.client.post(
                f"/api/projects/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "client_secret": "blah",
                    "account_id": "blah",
                },
            )

            assert response.status_code == 400

    def test_database_schema_zendesk_credentials(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_zendesk_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True

            response = self.client.post(
                f"/api/projects/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Zendesk",
                    "subdomain": "blah",
                    "api_key": "blah",
                    "email_address": "blah",
                },
            )

            assert response.status_code == 200

    def test_database_schema_zendesk_credentials_sad_path(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_zendesk_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = False

            response = self.client.post(
                f"/api/projects/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Zendesk",
                    "subdomain": "blah",
                    "api_key": "blah",
                    "email_address": "blah",
                },
            )

            assert response.status_code == 400

    def test_database_schema_non_postgres_source(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True
            response = self.client.post(
                f"/api/projects/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                },
            )
            results = response.json()

            self.assertEqual(response.status_code, 200)

            table_names = [table["table"] for table in results]
            for table in ENDPOINTS:
                assert table in table_names

    @patch(
        "posthog.warehouse.api.external_data_source.get_sql_schemas_for_source_type",
        return_value={"table_1": [("id", "integer")]},
    )
    def test_internal_postgres(self, patch_get_sql_schemas_for_source_type):
        # This test checks handling of project ID 2 in Cloud US and project ID 1 in Cloud EU,
        # so let's make sure there are no projects with these IDs in the test DB
        Project.objects.filter(id__in=[1, 2]).delete()
        Team.objects.filter(id__in=[1, 2]).delete()

        with override_settings(CLOUD_DEPLOYMENT="US"):
            team_2 = Team.objects.create(id=2, organization=self.team.organization)
            response = self.client.post(
                f"/api/projects/{team_2.id}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "dbname": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )
            assert response.status_code == 200
            assert response.json() == [
                {
                    "table": "table_1",
                    "should_sync": False,
                    "incremental_fields": [{"label": "id", "type": "integer", "field": "id", "field_type": "integer"}],
                    "incremental_available": True,
                    "incremental_field": "id",
                    "sync_type": None,
                }
            ]

            new_team = Team.objects.create(name="new_team", organization=self.team.organization)

            response = self.client.post(
                f"/api/projects/{new_team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "dbname": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"message": "Cannot use internal database"})

        with override_settings(CLOUD_DEPLOYMENT="EU"):
            team_1 = Team.objects.create(id=1, organization=self.team.organization)
            response = self.client.post(
                f"/api/projects/{team_1.id}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "dbname": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )

            assert response.status_code == 200
            assert response.json() == [
                {
                    "table": "table_1",
                    "should_sync": False,
                    "incremental_fields": [{"label": "id", "type": "integer", "field": "id", "field_type": "integer"}],
                    "incremental_available": True,
                    "incremental_field": "id",
                    "sync_type": None,
                }
            ]

            new_team = Team.objects.create(name="new_team", organization=self.team.organization)

            response = self.client.post(
                f"/api/projects/{new_team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "dbname": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"message": "Cannot use internal database"})

    def test_source_jobs(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            workflow_run_id="test_run_id",
        )

        response = self.client.get(
            f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}/jobs",
        )

        data = response.json()

        assert response.status_code, status.HTTP_200_OK
        assert len(data) == 1
        assert data[0]["id"] == str(job.pk)
        assert data[0]["status"] == "Completed"
        assert data[0]["rows_synced"] == 100
        assert data[0]["schema"]["id"] == str(schema.pk)
        assert data[0]["workflow_run_id"] is not None

    def test_source_jobs_pagination(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)
        with freeze_time("2024-07-01T12:00:00.000Z"):
            job1 = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=100,
                workflow_run_id="test_run_id",
            )

            response = self.client.get(
                f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}/jobs",
            )

            data = response.json()

            assert response.status_code, status.HTTP_200_OK
            assert len(data) == 1
            assert data[0]["id"] == str(job1.pk)

        # Query newer jobs
        with freeze_time("2024-07-01T18:00:00.000Z"):
            job2 = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=100,
                workflow_run_id="test_run_id",
            )

            response = self.client.get(
                f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}/jobs?after=2024-07-01T12:00:00.000Z",
            )

            data = response.json()

            assert response.status_code, status.HTTP_200_OK
            assert len(data) == 1
            assert data[0]["id"] == str(job2.pk)

        # Query older jobs
        with freeze_time("2024-07-01T09:00:00.000Z"):
            job3 = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=100,
                workflow_run_id="test_run_id",
            )

            response = self.client.get(
                f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}/jobs?before=2024-07-01T12:00:00.000Z",
            )

            data = response.json()

            assert response.status_code, status.HTTP_200_OK
            assert len(data) == 1
            assert data[0]["id"] == str(job3.pk)
