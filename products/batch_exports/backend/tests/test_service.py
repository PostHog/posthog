from products.batch_exports.backend.service import (
    AzureBlobBatchExportInputs,
    BigQueryBatchExportInputs,
    DatabricksBatchExportInputs,
    PostgresBatchExportInputs,
    S3BatchExportInputs,
)


class TestTypeCoercionInBatchExportInputs:
    """EncryptedJSONField may not preserve types, so fields can arrive as strings."""

    def test_databricks_inputs_coerce_string_booleans(self):
        inputs = DatabricksBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            http_path="/sql/1.0/warehouses/abc",
            catalog="main",
            schema="default",
            table_name="events",
            use_variant_type="true",  # type: ignore
            use_automatic_schema_evolution="false",  # type: ignore
        )
        assert inputs.use_variant_type is True
        assert inputs.use_automatic_schema_evolution is False

    def test_s3_inputs_coerce_string_booleans(self):
        inputs = S3BatchExportInputs(
            batch_export_id="test",
            team_id=1,
            bucket_name="bucket",
            region="us-east-1",
            prefix="prefix/",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            use_virtual_style_addressing="true",  # type: ignore
        )
        assert inputs.use_virtual_style_addressing is True

    def test_postgres_inputs_coerce_string_booleans(self):
        inputs = PostgresBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            user="user",
            password="password",
            host="localhost",
            database="db",
            has_self_signed_cert="True",  # type: ignore
        )
        assert inputs.has_self_signed_cert is True

    def test_bigquery_inputs_coerce_string_booleans(self):
        inputs = BigQueryBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            project_id="project",
            dataset_id="dataset",
            private_key="key",
            private_key_id="key_id",
            token_uri="https://oauth2.googleapis.com/token",
            client_email="test@test.iam.gserviceaccount.com",
            use_json_type="true",  # type: ignore
        )
        assert inputs.use_json_type is True

    def test_actual_booleans_are_preserved(self):
        inputs = DatabricksBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            http_path="/sql/1.0/warehouses/abc",
            catalog="main",
            schema="default",
            table_name="events",
            use_variant_type=True,
            use_automatic_schema_evolution=False,
        )
        assert inputs.use_variant_type is True
        assert inputs.use_automatic_schema_evolution is False

    def test_string_false_coerced_correctly(self):
        inputs = DatabricksBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            http_path="/sql/1.0/warehouses/abc",
            catalog="main",
            schema="default",
            table_name="events",
            use_variant_type="False",  # type: ignore
            use_automatic_schema_evolution="TRUE",  # type: ignore
        )
        assert inputs.use_variant_type is False
        assert inputs.use_automatic_schema_evolution is True

    def test_postgres_inputs_coerce_string_port(self):
        inputs = PostgresBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            user="user",
            password="password",
            host="localhost",
            database="db",
            port="5432",  # type: ignore
        )
        assert inputs.port == 5432

    def test_s3_inputs_coerce_string_max_file_size(self):
        inputs = S3BatchExportInputs(
            batch_export_id="test",
            team_id=1,
            bucket_name="bucket",
            region="us-east-1",
            prefix="prefix/",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            max_file_size_mb="100",  # type: ignore
        )
        assert inputs.max_file_size_mb == 100

    def test_azure_blob_inputs_coerce_string_max_file_size(self):
        inputs = AzureBlobBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            container_name="container",
            max_file_size_mb="50",  # type: ignore
        )
        assert inputs.max_file_size_mb == 50

    def test_optional_int_none_is_preserved(self):
        inputs = S3BatchExportInputs(
            batch_export_id="test",
            team_id=1,
            bucket_name="bucket",
            region="us-east-1",
            prefix="prefix/",
            aws_access_key_id="key",
            aws_secret_access_key="secret",
            max_file_size_mb=None,
        )
        assert inputs.max_file_size_mb is None
