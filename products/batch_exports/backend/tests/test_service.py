import pytest

from products.batch_exports.backend.service import (
    AzureBlobBatchExportInputs,
    BigQueryBatchExportInputs,
    DatabricksBatchExportInputs,
    PostgresBatchExportInputs,
    RedshiftBatchExportInputs,
    S3BatchExportInputs,
)

DESTINATION_INPUTS = {
    "Databricks": DatabricksBatchExportInputs(
        batch_export_id="test",
        team_id=1,
        http_path="/sql/1.0/warehouses/abc",
        catalog="main",
        schema="default",
        table_name="events",
        use_variant_type="true",  # type: ignore
        use_automatic_schema_evolution="false",  # type: ignore
    ),
    "S3": S3BatchExportInputs(
        batch_export_id="test",
        team_id=1,
        bucket_name="bucket",
        region="us-east-1",
        prefix="prefix/",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        use_virtual_style_addressing="true",  # type: ignore
        max_file_size_mb="100",  # type: ignore
    ),
    "Postgres": PostgresBatchExportInputs(
        batch_export_id="test",
        team_id=1,
        user="user",
        password="password",
        host="localhost",
        database="db",
        has_self_signed_cert="true",  # type: ignore
        port="5432",  # type: ignore
    ),
    "Redshift": RedshiftBatchExportInputs(
        batch_export_id="test",
        team_id=1,
        user="user",
        password="password",
        host="localhost",
        database="db",
        port="5439",  # type: ignore
    ),
    "BigQuery": BigQueryBatchExportInputs(
        batch_export_id="test",
        team_id=1,
        project_id="project",
        dataset_id="dataset",
        private_key="key",
        private_key_id="key_id",
        token_uri="https://oauth2.googleapis.com/token",
        client_email="test@test.iam.gserviceaccount.com",
        use_json_type="true",  # type: ignore
    ),
    "AzureBlob": AzureBlobBatchExportInputs(
        batch_export_id="test",
        team_id=1,
        container_name="container",
        max_file_size_mb="50",  # type: ignore
    ),
}


class TestTypeCoercionInBatchExportInputs:
    """EncryptedJSONField may not preserve types, so fields can arrive as strings."""

    @pytest.mark.parametrize(
        "destination,field,expected",
        [
            ("Databricks", "use_variant_type", True),
            ("Databricks", "use_automatic_schema_evolution", False),
            ("S3", "use_virtual_style_addressing", True),
            ("Postgres", "has_self_signed_cert", True),
            ("BigQuery", "use_json_type", True),
        ],
    )
    def test_string_booleans_are_coerced(self, destination, field, expected):
        assert getattr(DESTINATION_INPUTS[destination], field) is expected

    @pytest.mark.parametrize(
        "destination,field,expected",
        [
            ("Postgres", "port", 5432),
            ("Redshift", "port", 5439),
            ("S3", "max_file_size_mb", 100),
            ("AzureBlob", "max_file_size_mb", 50),
        ],
    )
    def test_string_ints_are_coerced(self, destination, field, expected):
        assert getattr(DESTINATION_INPUTS[destination], field) == expected

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
