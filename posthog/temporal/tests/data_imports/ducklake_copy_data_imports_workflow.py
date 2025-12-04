import uuid

import pytest

import temporalio.converter

from posthog.sync import database_sync_to_async
from posthog.temporal.data_imports.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsModelInput,
    DuckLakeCopyWorkflowGateInputs,
    ducklake_copy_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
)

from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable


@pytest.mark.asyncio
async def test_data_imports_ducklake_copy_inputs_round_trip_serialization():
    model_input = DuckLakeCopyDataImportsModelInput(
        schema_id=uuid.uuid4(),
        schema_name="customers",
        source_type="postgres",
        normalized_name="customers",
        table_uri="s3://bucket/team_1/table",
        job_id="job-123",
        team_id=1,
    )
    inputs = DataImportsDuckLakeCopyInputs(team_id=1, job_id="job-123", models=[model_input])

    data_converter = temporalio.converter.default()
    encoded = await data_converter.encode([inputs])
    decoded = await data_converter.decode(encoded, [DataImportsDuckLakeCopyInputs])

    assert decoded[0].team_id == inputs.team_id
    assert decoded[0].job_id == inputs.job_id
    assert decoded[0].models[0].normalized_name == model_input.normalized_name
    assert str(decoded[0].models[0].schema_id) == str(model_input.schema_id)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("flag_enabled", [True, False])
async def test_ducklake_copy_data_imports_gate_respects_feature_flag(monkeypatch, ateam, flag_enabled):
    captured = {}

    def fake_feature_enabled(
        key,
        distinct_id,
        *,
        groups=None,
        group_properties=None,
        only_evaluate_locally=False,
        send_feature_flag_events=True,
    ):
        captured["key"] = key
        captured["distinct_id"] = distinct_id
        captured["groups"] = groups
        captured["group_properties"] = group_properties
        captured["only_evaluate_locally"] = only_evaluate_locally
        captured["send_feature_flag_events"] = send_feature_flag_events
        return flag_enabled

    monkeypatch.setattr(
        "posthog.temporal.data_imports.ducklake_copy_data_imports_workflow.posthoganalytics.feature_enabled",
        fake_feature_enabled,
    )

    result = await ducklake_copy_data_imports_gate_activity(DuckLakeCopyWorkflowGateInputs(team_id=ateam.id))

    assert result is flag_enabled
    assert captured["key"] == "ducklake-copy-data-imports"
    assert captured["distinct_id"] == str(ateam.uuid)
    assert captured["groups"] == {"organization": str(ateam.organization_id), "project": str(ateam.id)}
    assert captured["only_evaluate_locally"] is True
    assert captured["send_feature_flag_events"] is False


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_imports_ducklake_metadata_activity_basic(ateam):
    credential = await database_sync_to_async(DataWarehouseCredential.objects.create)(
        team=ateam, access_key="test_key", access_secret="test_secret"
    )
    source = await database_sync_to_async(ExternalDataSource.objects.create)(
        team=ateam,
        source_id="test_source",
        connection_id="test_connection",
        source_type="Postgres",
        status="Running",
    )
    table = await database_sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name="test_table",
        format="Delta",
        url_pattern="s3://bucket/path",
        credential=credential,
        external_data_source=source,
        columns={
            "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
            "created_at": {"clickhouse": "DateTime64", "hogql": "DateTimeDatabaseField"},
            "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
        },
    )
    schema = await database_sync_to_async(ExternalDataSchema.objects.create)(
        team=ateam,
        name="customers",
        source=source,
        table=table,
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={
            "incremental_field": "created_at",
            "incremental_field_type": "DateTime",
            "partitioning_enabled": True,
            "partitioning_keys": ["created_at"],
        },
    )

    model_input = DuckLakeCopyDataImportsModelInput(
        schema_id=schema.id,
        schema_name=schema.name,
        source_type=source.source_type,
        normalized_name=schema.normalized_name,
        table_uri=f"s3://bucket/{schema.folder_path()}/{schema.normalized_name}",
        job_id="job-123",
        team_id=ateam.id,
    )
    inputs = DataImportsDuckLakeCopyInputs(team_id=ateam.id, job_id="job-123", models=[model_input])

    result = await prepare_data_imports_ducklake_metadata_activity(inputs)

    assert len(result) == 1
    metadata = result[0]
    assert metadata.normalized_name == "customers"
    assert metadata.ducklake_schema_name == f"data_imports_team_{ateam.id}"
    assert metadata.ducklake_table_name.startswith("postgres_customers_")
    assert metadata.partition_column == "created_at"
    assert "created_at" in metadata.key_columns
    assert "id" in metadata.key_columns
    assert "id" in metadata.non_nullable_columns
    assert "created_at" in metadata.non_nullable_columns
    assert "name" not in metadata.non_nullable_columns


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_imports_ducklake_metadata_activity_no_partition(ateam):
    credential = await database_sync_to_async(DataWarehouseCredential.objects.create)(
        team=ateam, access_key="test_key", access_secret="test_secret"
    )
    source = await database_sync_to_async(ExternalDataSource.objects.create)(
        team=ateam,
        source_id="test_source",
        connection_id="test_connection",
        source_type="Stripe",
        status="Running",
    )
    table = await database_sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name="test_table",
        format="Delta",
        url_pattern="s3://bucket/path",
        credential=credential,
        external_data_source=source,
        columns={
            "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            "amount": {"clickhouse": "Nullable(Float64)", "hogql": "FloatDatabaseField"},
        },
    )
    schema = await database_sync_to_async(ExternalDataSchema.objects.create)(
        team=ateam,
        name="charges",
        source=source,
        table=table,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
    )

    model_input = DuckLakeCopyDataImportsModelInput(
        schema_id=schema.id,
        schema_name=schema.name,
        source_type=source.source_type,
        normalized_name=schema.normalized_name,
        table_uri=f"s3://bucket/{schema.folder_path()}/{schema.normalized_name}",
        job_id="job-456",
        team_id=ateam.id,
    )
    inputs = DataImportsDuckLakeCopyInputs(team_id=ateam.id, job_id="job-456", models=[model_input])

    result = await prepare_data_imports_ducklake_metadata_activity(inputs)

    assert len(result) == 1
    metadata = result[0]
    assert metadata.normalized_name == "charges"
    assert metadata.partition_column is None
    assert metadata.partition_column_type is None
    assert "id" in metadata.key_columns
    assert "id" in metadata.non_nullable_columns
    assert "amount" not in metadata.non_nullable_columns


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_imports_ducklake_metadata_activity_empty_models(ateam):
    inputs = DataImportsDuckLakeCopyInputs(team_id=ateam.id, job_id="job-empty", models=[])
    result = await prepare_data_imports_ducklake_metadata_activity(inputs)
    assert result == []
