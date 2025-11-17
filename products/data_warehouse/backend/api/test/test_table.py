from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import ANY, MagicMock, patch

import boto3
from clickhouse_driver.errors import ServerException

from posthog.settings import settings

from products.data_warehouse.backend.models import DataWarehouseTable
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource


class TestTable(APIBaseTest):
    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns",
        return_value={
            "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
            "a_column": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
        },
    )
    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.validate_column_type",
        return_value=True,
    )
    @patch("posthog.tasks.warehouse.get_client")
    def test_create_columns(self, patch_get_columns, patch_validate_column_type, patch_get_client):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        assert response.status_code == 201
        data: dict[str, Any] = response.json()

        table = DataWarehouseTable.objects.get(id=data["id"])

        assert table.name == "whatever"
        assert table.columns == {
            "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
            "a_column": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
        }

        assert table.credential.access_key, "_accesskey"
        assert table.credential.access_secret, "_accesssecret"

    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns",
        return_value={
            "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
            "a_column": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
        },
    )
    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.validate_column_type",
        return_value=False,
    )
    @patch("posthog.tasks.warehouse.get_client")
    def test_create_columns_invalid_schema(self, patch_get_columns, patch_validate_column_type, patch_get_client):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        assert response.status_code == 201
        data: dict[str, Any] = response.json()

        table = DataWarehouseTable.objects.get(id=data["id"])

        assert table.name == "whatever"
        assert table.columns == {
            "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
            "a_column": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
        }

        assert table.credential.access_key, "_accesskey"
        assert table.credential.access_secret, "_accesssecret"

    @patch("products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns")
    def test_credentialerror(self, patch_get_columns):
        patch_get_columns.side_effect = ServerException(
            message="""DB::Exception: The AWS Access Key Id you provided does not exist in our records.: Cannot extract table structure from Parquet format file. You can specify the structure manually. Stack trace:\n\n0. DB::Exception::Exception(std::__1::basic_string<char, std::__1::char_traits<char>, std::__1::allocator<char> > const&, int, bool) @ 0x8e25488 in /u""",
            code=499,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()

    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.validate_column_type",
        return_value=True,
    )
    def test_update_schema_200_old_column_style(self, patch_validate_column_type):
        table = DataWarehouseTable.objects.create(
            name="test_table", format="Parquet", team=self.team, team_id=self.team.pk, columns={"id": "Nullable(Int64)"}
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {"id": "float"}}
        )

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns["id"] == {"clickhouse": "Nullable(Float64)", "hogql": "FloatDatabaseField", "valid": True}

    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.validate_column_type",
        return_value=True,
    )
    def test_update_schema_200_new_column_style(self, patch_validate_column_type):
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns={"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}},
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {"id": "float"}}
        )

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns["id"] == {"clickhouse": "Nullable(Float64)", "hogql": "FloatDatabaseField", "valid": True}

    def test_update_schema_200_no_updates(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {}}
        )

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns == columns

        response = self.client.post(f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {})

        table.refresh_from_db()

        assert response.status_code == 200
        assert table.columns == columns

    def test_update_schema_400_with_source(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}

        source = ExternalDataSource.objects.create(team=self.team, team_id=self.team.pk)
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
            external_data_source_id=source.pk,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema", {"updates": {"id": "float"}}
        )

        table.refresh_from_db()

        assert response.status_code == 400
        assert response.json()["message"] == "The table must be a manually linked table"
        assert table.columns == columns

    def test_update_schema_400_with_non_existing_column(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}

        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema",
            {"updates": {"some_other_column": "float"}},
        )

        table.refresh_from_db()

        assert response.status_code == 400
        assert response.json()["message"] == "Column some_other_column does not exist on table"
        assert table.columns == columns

    def test_update_schema_400_with_invalid_type(self):
        columns = {"id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"}}

        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns=columns,
        )
        response = self.client.post(
            f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}/update_schema",
            {"updates": {"id": "another_type"}},
        )

        table.refresh_from_db()

        assert response.status_code == 400
        assert response.json()["message"] == "Can not parse type another_type for column id - type does not exist"
        assert table.columns == columns

    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns",
        return_value={
            "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
            "a_column": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
        },
    )
    @patch(
        "products.data_warehouse.backend.models.table.DataWarehouseTable.validate_column_type",
        return_value=True,
    )
    @patch("posthog.tasks.warehouse.get_client")
    def test_table_name_duplicate(self, patch_get_columns, patch_validate_column_type, patch_get_client):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        assert response.status_code == 201
        data: dict[str, Any] = response.json()

        table = DataWarehouseTable.objects.get(id=data["id"])

        assert table is not None

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        assert response.status_code == 400
        assert DataWarehouseTable.objects.count() == 1

    def test_delete_table(self):
        table = DataWarehouseTable.objects.create(
            name="test_table", format="Parquet", team=self.team, team_id=self.team.pk, columns={}
        )
        response = self.client.delete(f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}")

        assert response.status_code == 204

        table.refresh_from_db()

        assert table.deleted is True

    def test_delete_table_with_source(self):
        source = ExternalDataSource.objects.create(team=self.team, team_id=self.team.pk)
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            team_id=self.team.pk,
            columns={},
            external_data_source_id=source.pk,
        )
        response = self.client.delete(f"/api/projects/{self.team.pk}/warehouse_tables/{table.id}")

        assert response.status_code == 400

        table.refresh_from_db()

        assert table.deleted is False

    def test_create_table_with_existing_name(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "events",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "format": "Parquet",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "A table with this name already exists."

    def test_update_table_name_to_existing_name(self):
        table = DataWarehouseTable.objects.create(
            name="test_table", format="Parquet", team=self.team, team_id=self.team.pk, columns={}
        )
        DataWarehouseTable.objects.create(
            name="test_table2", format="Parquet", team=self.team, team_id=self.team.pk, columns={}
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_tables/{table.id}",
            {
                "name": "test_table2",
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "A table with this name already exists."

    def test_update_table_name_to_same_name(self):
        table = DataWarehouseTable.objects.create(
            name="test_table", format="Parquet", team=self.team, team_id=self.team.pk, columns={}
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_tables/{table.id}",
            {
                "name": "test_table",
            },
        )
        assert response.status_code == 200
        assert response.json()["name"] == "test_table"

    def test_update_table_name(self):
        table = DataWarehouseTable.objects.create(
            name="test_table", format="Parquet", team=self.team, team_id=self.team.pk, columns={}
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_tables/{table.id}",
            {
                "name": "test_table2",
            },
        )
        assert response.status_code == 200
        assert response.json()["name"] == "test_table2"

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("boto3.client")
    def test_file_upload_creates_new_table(self, mock_boto3_client, mock_feature_enabled):
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3

        from django.core.files.uploadedfile import SimpleUploadedFile

        file_content = b"id,name,value\n1,Test,100\n2,Test2,200"
        test_file = SimpleUploadedFile("test_file.csv", file_content, content_type="text/csv")

        with patch("products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
            mock_get_columns.return_value = {
                "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
                "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
                "value": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
            }

            with self.settings(
                AIRBYTE_BUCKET_KEY="test_key",
                AIRBYTE_BUCKET_SECRET="test_secret",
                AIRBYTE_BUCKET_DOMAIN="test-bucket.s3.amazonaws.com",
                DATAWAREHOUSE_BUCKET="test-warehouse-bucket",
            ):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/warehouse_tables/file/",
                    {"file": test_file, "name": "test_csv_table", "format": "CSVWithNames"},
                    format="multipart",
                )

        assert response.status_code == 201
        assert response.json()["name"] == "test_csv_table"
        assert response.json()["format"] == "CSVWithNames"

        # Verify the table was created
        table = DataWarehouseTable.objects.get(name="test_csv_table")
        assert table is not None

        # Verify S3 client was called to upload the file
        mock_s3.upload_fileobj.assert_called_once_with(
            ANY, "test-warehouse-bucket", f"managed/team_{self.team.id}/test_file.csv"
        )

        # Verify URL pattern was set correctly
        assert table.url_pattern == f"https://test-bucket.s3.amazonaws.com/managed/team_{self.team.id}/test_file.csv"

    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_file_upload_api_disabled(self, mock_feature_enabled):
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_content = b"id,name,value\n1,Test,100\n2,Test2,200"
        test_file = SimpleUploadedFile("test_file", file_content, content_type="text/csv")

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/file/",
            {"file": test_file, "name": "test_csv_table", "format": "CSVWithNames"},
            format="multipart",
        )

        assert response.status_code == 400
        assert response.json()["message"] == "Warehouse API is not enabled for this organization"

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("boto3.client")
    def test_file_upload_invalid_table_name(self, mock_boto3_client, mock_feature_enabled):
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3

        from django.core.files.uploadedfile import SimpleUploadedFile

        file_content = b"id,name,value\n1,Test,100\n2,Test2,200"
        test_file = SimpleUploadedFile("test-file.csv", file_content, content_type="text/csv")

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/file/",
            {"file": test_file, "name": "test-table", "format": "CSVWithNames"},
            format="multipart",
        )

        assert response.status_code == 400
        assert "Table names must start with a letter or underscore" in response.json()["message"]

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("boto3.client")
    def test_file_upload_updates_existing_table(self, mock_boto3_client, mock_feature_enabled):
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3

        # Create an existing table
        existing_table = DataWarehouseTable.objects.create(
            name="existing_table", format="CSVWithNames", team=self.team, team_id=self.team.pk, columns={}
        )

        from django.core.files.uploadedfile import SimpleUploadedFile

        file_content = b"id,new_name,value\n1,Test,100\n2,Test2,200"
        test_file = SimpleUploadedFile("updated_file.csv", file_content, content_type="text/csv")

        with patch("products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
            mock_get_columns.return_value = {
                "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
                "new_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
                "value": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": True},
            }

            with self.settings(
                AIRBYTE_BUCKET_KEY="test_key",
                AIRBYTE_BUCKET_SECRET="test_secret",
                AIRBYTE_BUCKET_DOMAIN="test-bucket.s3.amazonaws.com",
                DATAWAREHOUSE_BUCKET="test-warehouse-bucket",
            ):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/warehouse_tables/file/",
                    {"file": test_file, "name": "existing_table", "format": "CSVWithNames"},
                    format="multipart",
                )

        assert response.status_code == 201

        # Verify the table was updated
        existing_table.refresh_from_db()
        assert (
            existing_table.url_pattern
            == f"https://test-bucket.s3.amazonaws.com/managed/team_{self.team.id}/updated_file.csv"
        )

        # columns will be false as validation doesn't work for mocked fields
        assert existing_table.columns == {
            "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
            "new_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
            "value": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
        }

        # Verify S3 client was called to upload the file
        mock_s3.upload_fileobj.assert_called_once_with(
            ANY, "test-warehouse-bucket", f"managed/team_{self.team.id}/updated_file.csv"
        )

    def _delete_all_from_s3(self, s3_client, bucket_name, prefix=""):
        """Helper to delete all objects in a bucket with a given prefix."""
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        if "Contents" in response:
            for obj in response["Contents"]:
                if "Key" in obj:
                    s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])

    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_file_upload_with_minio(self, mock_feature_enabled):
        """Test file upload using actual MinIO bucket instead of mocking."""

        # Create a unique bucket name for testing
        test_bucket_name = f"test-warehouse"

        # Setup real S3 client
        s3_client = boto3.client(
            "s3",
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id="object_storage_root_user",
            aws_secret_access_key="object_storage_root_password",
            region_name="us-east-1",
        )

        s3_client.create_bucket(Bucket=test_bucket_name)

        # Create a test file
        from django.core.files.uploadedfile import SimpleUploadedFile

        file_content = b"id,name,value\n1,Test,100\n2,Test2,200"
        test_file = SimpleUploadedFile("test_file.csv", file_content, content_type="text/csv")

        # Patch get_columns to return test columns
        with patch("products.data_warehouse.backend.models.table.DataWarehouseTable.get_columns") as mock_get_columns:
            mock_get_columns.return_value = {
                "id": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
                "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
                "value": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField", "valid": False},
            }
            # Patch the settings to use our test bucket
            with self.settings(
                AIRBYTE_BUCKET_KEY="object_storage_root_user",
                AIRBYTE_BUCKET_SECRET="object_storage_root_password",
                AIRBYTE_BUCKET_DOMAIN="test-bucket.s3.amazonaws.com",
                BUCKET_URL=f"s3://{test_bucket_name}",
                DATAWAREHOUSE_BUCKET=test_bucket_name,
            ):
                # Make the API request
                response = self.client.post(
                    f"/api/projects/{self.team.id}/warehouse_tables/file/",
                    {"file": test_file, "name": "minio_csv_table", "format": "CSVWithNames"},
                    format="multipart",
                )

        # Assert the response is successful
        self.assertEqual(response.status_code, 201)

        # Verify the table was created
        table = DataWarehouseTable.objects.get(name="minio_csv_table")
        self.assertIsNotNone(table)

        # Check that the file was actually uploaded to MinIO
        objects = s3_client.list_objects_v2(
            Bucket=test_bucket_name, Prefix=f"managed/team_{self.team.id}/test_file.csv"
        )
        self.assertIn("Contents", objects, "No objects found in the bucket")

        # TODO: DRY
        self._delete_all_from_s3(s3_client, test_bucket_name)
        s3_client.delete_bucket(Bucket=test_bucket_name)
