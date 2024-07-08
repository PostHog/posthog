from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema
import uuid
from unittest.mock import patch
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.warehouse.data_load.service import get_sync_schedule
from django.test import override_settings
from django.conf import settings
from posthog.models import Team
import psycopg
from rest_framework import status

import datetime


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
                "sync_frequency",
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
                }
            ],
        )

    def test_delete_external_data_source(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.delete(f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}")

        self.assertEqual(response.status_code, 204)

        self.assertFalse(ExternalDataSource.objects.filter(pk=source.pk).exists())
        self.assertFalse(ExternalDataSchema.objects.filter(pk=schema.pk).exists())

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

    def test_database_schema_non_postgres_source(self):
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

    @patch("posthog.warehouse.api.external_data_source.get_postgres_schemas")
    def test_internal_postgres(self, patch_get_postgres_schemas):
        patch_get_postgres_schemas.return_value = {"table_1": [("id", "integer")]}

        with override_settings(CLOUD_DEPLOYMENT="US"):
            team_2, _ = Team.objects.get_or_create(id=2, organization=self.team.organization)
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
            self.assertEqual(response.json(), {"message": "Cannot use internal Postgres database"})

        with override_settings(CLOUD_DEPLOYMENT="EU"):
            team_1, _ = Team.objects.get_or_create(id=1, organization=self.team.organization)
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
            self.assertEqual(response.json(), {"message": "Cannot use internal Postgres database"})

    @patch("posthog.warehouse.data_load.service.sync_external_data_job_workflow")
    def test_update_source_sync_frequency(self, _patch_sync_external_data_job_workflow):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        self.assertEqual(source.sync_frequency, ExternalDataSource.SyncFrequency.DAILY)
        # test schedule
        schedule = get_sync_schedule(schema)
        self.assertEqual(
            schedule.spec.intervals[0].every,
            datetime.timedelta(days=1),
        )

        # test api
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"sync_frequency": ExternalDataSource.SyncFrequency.WEEKLY},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        source.refresh_from_db()
        schema.refresh_from_db()

        self.assertEqual(source.sync_frequency, ExternalDataSource.SyncFrequency.WEEKLY)
        self.assertEqual(_patch_sync_external_data_job_workflow.call_count, 1)

        # test schedule
        schedule = get_sync_schedule(schema)
        self.assertEqual(
            schedule.spec.intervals[0].every,
            datetime.timedelta(days=7),
        )
