import uuid

import pytest

from django.test import override_settings

from posthog.temporal.data_modeling import ducklake_copy_workflow as ducklake_module
from posthog.temporal.data_modeling.ducklake_copy_workflow import (
    DuckLakeCopyActivityInputs,
    DuckLakeCopyModelMetadata,
    copy_data_modeling_model_to_ducklake_activity,
    prepare_data_modeling_ducklake_metadata_activity,
)
from posthog.temporal.utils import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_modeling_ducklake_metadata_activity_returns_models(
    activity_environment, ateam, monkeypatch
):
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="ducklake_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
    )
    job_id = uuid.uuid4().hex
    table_uri = f"s3://source/team_{ateam.pk}_model_{saved_query.id.hex}/modeling/{saved_query.normalized_name}"
    file_uris = [
        f"{table_uri}/part-0.parquet",
        f"{table_uri}/chunk=1/part-1.parquet",
    ]
    inputs = DataModelingDuckLakeCopyInputs(
        team_id=ateam.pk,
        job_id=job_id,
        models=[
            DuckLakeCopyModelInput(
                model_label=saved_query.id.hex,
                saved_query_id=str(saved_query.id),
                table_uri=table_uri,
                file_uris=file_uris,
            )
        ],
    )
    monkeypatch.setenv("DUCKLAKE_DATA_BUCKET", "ducklake-test-bucket")

    metadata = await activity_environment.run(prepare_data_modeling_ducklake_metadata_activity, inputs)

    assert len(metadata) == 1
    model_metadata = metadata[0]
    assert model_metadata.model_label == saved_query.id.hex
    assert model_metadata.saved_query_name == saved_query.name
    assert model_metadata.source_glob_uri == f"{table_uri}/**/*.parquet"
    assert model_metadata.schema_name == f"data_modeling_team_{ateam.pk}"
    assert model_metadata.table_name == f"model_{saved_query.id.hex}"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_copy_data_modeling_model_to_ducklake_activity_uses_duckdb(monkeypatch, activity_environment):
    fake_conn_calls: list[tuple[str, tuple | None]] = []

    class FakeDuckDBConnection:
        def __init__(self):
            self.sql_statements: list[str] = []
            self.closed = False

        def execute(self, statement: str, params: list | None = None):
            fake_conn_calls.append((statement, tuple(params) if params else None))

        def sql(self, statement: str):
            self.sql_statements.append(statement)

        def close(self):
            self.closed = True

    fake_conn = FakeDuckDBConnection()
    monkeypatch.setattr(ducklake_module.duckdb, "connect", lambda: fake_conn)

    configure_args: dict[str, object] = {}

    def fake_configure(conn, config, install_extension):
        configure_args["install_extension"] = install_extension
        configure_args["bucket"] = config["DUCKLAKE_DATA_BUCKET"]

    monkeypatch.setattr(ducklake_module, "configure_connection", fake_configure)

    ensured: dict[str, bool] = {"called": False}

    def fake_ensure_bucket(config):
        ensured["called"] = True

    monkeypatch.setattr(ducklake_module, "_ensure_ducklake_bucket_exists", fake_ensure_bucket)

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_a",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_glob_uri="s3://source/table/**/*.parquet",
        schema_name="data_modeling_team_1",
        table_name="model_a",
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-123", model=metadata)

    with override_settings(
        AIRBYTE_BUCKET_KEY="test",
        AIRBYTE_BUCKET_SECRET="secret",
        OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000",
        USE_LOCAL_SETUP=True,
    ):
        activity_environment.run(copy_data_modeling_model_to_ducklake_activity, inputs)

    schema_calls = [
        statement for statement, _ in fake_conn_calls if statement.startswith("CREATE SCHEMA IF NOT EXISTS")
    ]
    table_calls = [statement for statement, _ in fake_conn_calls if statement.startswith("CREATE OR REPLACE TABLE")]

    assert configure_args["install_extension"] is True
    assert configure_args["bucket"] == ducklake_module.get_config()["DUCKLAKE_DATA_BUCKET"]
    assert ensured["called"] is True
    assert schema_calls and "ducklake_dev.data_modeling_team_1" in schema_calls[0]
    assert table_calls and "ducklake_dev.data_modeling_team_1.model_a" in table_calls[0]
    assert "read_parquet('s3://source/table/**/*.parquet')" in table_calls[0]
    assert any("ATTACH" in statement for statement in fake_conn.sql_statements), "Expected DuckLake catalog attach"
    assert fake_conn.closed is True
