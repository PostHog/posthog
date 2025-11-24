import os
import uuid

import pytest

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
from deltalake import write_deltalake

from posthog.temporal.data_modeling import ducklake_copy_workflow as ducklake_module
from posthog.temporal.data_modeling.ducklake_copy_workflow import (
    DuckLakeCopyActivityInputs,
    DuckLakeCopyModelMetadata,
    copy_model_to_ducklake_activity,
    prepare_ducklake_copy_metadata_activity,
)
from posthog.temporal.utils import DuckLakeCopyModelInput, DuckLakeCopyWorkflowInputs

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

RUN_INTEGRATION_COPY_TESTS = os.environ.get("RUN_DUCKLAKE_COPY_TESTS") == "1"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_ducklake_copy_metadata_activity_returns_models(activity_environment, ateam, monkeypatch):
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="ducklake_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
    )
    job_id = uuid.uuid4().hex
    table_uri = f"s3://source/team_{ateam.pk}_model_{saved_query.id.hex}/{saved_query.normalized_name}"
    inputs = DuckLakeCopyWorkflowInputs(
        team_id=ateam.pk,
        job_id=job_id,
        models=[
            DuckLakeCopyModelInput(
                model_label=saved_query.id.hex,
                saved_query_id=str(saved_query.id),
                table_uri=table_uri,
            )
        ],
    )
    monkeypatch.setenv("DUCKLAKE_DATA_BUCKET", "ducklake-test-bucket")

    metadata = await activity_environment.run(prepare_ducklake_copy_metadata_activity, inputs)

    assert len(metadata) == 1
    model_metadata = metadata[0]
    assert model_metadata.model_label == saved_query.id.hex
    assert model_metadata.table_uri == table_uri
    assert model_metadata.saved_query_name == saved_query.name
    assert model_metadata.destination_uri == (
        f"s3://ducklake-test-bucket/data_modeling/"
        f"team_{ateam.pk}/job_{job_id}/model_{saved_query.id.hex}/{saved_query.normalized_name}.parquet"
    )


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_copy_model_to_ducklake_activity_uses_duckdb(monkeypatch, activity_environment):
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
        table_uri="s3://source/table",
        destination_uri="s3://ducklake-target/path/to/model.parquet",
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-123", model=metadata)

    with override_settings(
        AIRBYTE_BUCKET_KEY="test",
        AIRBYTE_BUCKET_SECRET="secret",
        OBJECT_STORAGE_ENDPOINT="http://objectstorage:19000",
        USE_LOCAL_SETUP=True,
    ):
        activity_environment.run(copy_model_to_ducklake_activity, inputs)

    create_calls = [
        statement for statement, params in fake_conn_calls if "read_delta" in statement and params is not None
    ]
    copy_calls = [statement for statement, params in fake_conn_calls if statement.startswith("COPY (SELECT * FROM")]
    drop_calls = [statement for statement, _ in fake_conn_calls if statement.startswith("DROP TABLE")]

    assert configure_args["install_extension"] is True
    assert configure_args["bucket"] == ducklake_module.get_config()["DUCKLAKE_DATA_BUCKET"]
    assert ensured["called"] is True
    assert create_calls, "Expected temp table creation with read_delta"
    assert copy_calls and inputs.model.destination_uri in copy_calls[0]
    assert drop_calls, "Expected temporary table cleanup"
    assert fake_conn.closed is True


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.skipif(not RUN_INTEGRATION_COPY_TESTS, reason="Set RUN_DUCKLAKE_COPY_TESTS=1 to run this test.")
async def test_copy_model_to_ducklake_activity_with_minio(
    activity_environment,
    ateam,
    bucket_name,
    minio_client,
    monkeypatch,
):
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="ducklake_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
    )
    table_uri = f"s3://{bucket_name}/ducklake_source/{saved_query.id.hex}"

    write_deltalake(
        table_uri,
        pa.table({"event": ["test-event"], "count": [1]}),
        storage_options={
            "AWS_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "AWS_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "AWS_ENDPOINT_URL": settings.OBJECT_STORAGE_ENDPOINT,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        },
        mode="overwrite",
    )

    ducklake_bucket = f"ducklake-target-{uuid.uuid4().hex}"
    try:
        await minio_client.create_bucket(Bucket=ducklake_bucket)
    except Exception:
        pass

    monkeypatch.setenv("DUCKLAKE_DATA_BUCKET", ducklake_bucket)
    monkeypatch.setenv("DUCKLAKE_DATA_ENDPOINT", settings.OBJECT_STORAGE_ENDPOINT)
    monkeypatch.setenv("DUCKLAKE_S3_ACCESS_KEY", settings.OBJECT_STORAGE_ACCESS_KEY_ID)
    monkeypatch.setenv("DUCKLAKE_S3_SECRET_KEY", settings.OBJECT_STORAGE_SECRET_ACCESS_KEY)

    job_id = uuid.uuid4().hex
    inputs = DuckLakeCopyWorkflowInputs(
        team_id=ateam.pk,
        job_id=job_id,
        models=[
            DuckLakeCopyModelInput(
                model_label=saved_query.id.hex,
                saved_query_id=str(saved_query.id),
                table_uri=table_uri,
            )
        ],
    )
    metadata = await activity_environment.run(prepare_ducklake_copy_metadata_activity, inputs)
    activity_environment.run(
        copy_model_to_ducklake_activity,
        DuckLakeCopyActivityInputs(team_id=ateam.pk, job_id=job_id, model=metadata[0]),
    )

    prefix = f"data_modeling/team_{ateam.pk}/job_{job_id}/model_{saved_query.id.hex}/"
    objects = await minio_client.list_objects_v2(Bucket=ducklake_bucket, Prefix=prefix)

    assert objects.get("KeyCount", 0) > 0
