import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock

import temporalio.worker
import temporalio.converter
from temporalio import activity as temporal_activity
from temporalio.testing import WorkflowEnvironment

from posthog.ducklake.verification import DuckLakeCopyVerificationParameter, DuckLakeCopyVerificationQuery
from posthog.sync import database_sync_to_async
from posthog.temporal.ducklake import ducklake_copy_data_imports_workflow as ducklake_module
from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsActivityInputs,
    DuckLakeCopyDataImportsMetadata,
    DuckLakeCopyDataImportsWorkflow,
    DuckLakeCopyWorkflowGateInputs,
    copy_data_imports_to_ducklake_activity,
    ducklake_copy_data_imports_gate_activity,
    prepare_data_imports_ducklake_metadata_activity,
    verify_data_imports_ducklake_copy_activity,
)

from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.table import DataWarehouseTable


@pytest.mark.asyncio
async def test_data_imports_ducklake_copy_inputs_round_trip_serialization():
    schema_id = uuid.uuid4()
    inputs = DataImportsDuckLakeCopyInputs(team_id=1, job_id="job-123", schema_ids=[schema_id])

    data_converter = temporalio.converter.default()
    encoded = await data_converter.encode([inputs])
    decoded = await data_converter.decode(encoded, [DataImportsDuckLakeCopyInputs])

    assert decoded[0].team_id == inputs.team_id
    assert decoded[0].job_id == inputs.job_id
    assert str(decoded[0].schema_ids[0]) == str(schema_id)


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
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.posthoganalytics.feature_enabled",
        fake_feature_enabled,
    )

    result = await ducklake_copy_data_imports_gate_activity(DuckLakeCopyWorkflowGateInputs(team_id=ateam.id))

    assert result is flag_enabled
    assert captured["key"] == "ducklake-data-imports-copy-workflow"
    assert captured["distinct_id"] == str(ateam.uuid)
    assert captured["groups"] == {"organization": str(ateam.organization_id), "project": str(ateam.id)}
    assert captured["only_evaluate_locally"] is True
    assert captured["send_feature_flag_events"] is False


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_imports_ducklake_metadata_activity_basic(ateam, monkeypatch):
    # Mock Delta partition detection since we can't read actual Delta metadata in tests
    monkeypatch.setattr(ducklake_module, "_fetch_delta_partition_columns", lambda table_uri: ["created_at"])

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

    inputs = DataImportsDuckLakeCopyInputs(team_id=ateam.id, job_id="job-123", schema_ids=[schema.id])

    result = await prepare_data_imports_ducklake_metadata_activity(inputs)

    assert len(result) == 1
    metadata = result[0]
    assert metadata.source_normalized_name == "customers"
    assert metadata.ducklake_schema_name == f"data_imports_team_{ateam.id}"
    assert metadata.ducklake_table_name.startswith("postgres_customers_")
    assert metadata.source_partition_column == "created_at"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_imports_ducklake_metadata_activity_no_partition(ateam, monkeypatch):
    # Mock Delta partition detection - returns empty list when no partitions
    monkeypatch.setattr(ducklake_module, "_fetch_delta_partition_columns", lambda table_uri: [])

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

    inputs = DataImportsDuckLakeCopyInputs(team_id=ateam.id, job_id="job-456", schema_ids=[schema.id])

    result = await prepare_data_imports_ducklake_metadata_activity(inputs)

    assert len(result) == 1
    metadata = result[0]
    assert metadata.source_normalized_name == "charges"
    # No partition column when Delta table has no partitions
    assert metadata.source_partition_column is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_imports_ducklake_metadata_activity_empty_schema_ids(ateam):
    inputs = DataImportsDuckLakeCopyInputs(team_id=ateam.id, job_id="job-empty", schema_ids=[])
    result = await prepare_data_imports_ducklake_metadata_activity(inputs)
    assert result == []


def test_copy_data_imports_to_ducklake_activity_executes_correct_sql(monkeypatch):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_duckdb_connect = MagicMock(return_value=mock_conn)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.duckdb.connect",
        mock_duckdb_connect,
    )

    mock_heartbeater = MagicMock()
    mock_heartbeater.__enter__ = MagicMock(return_value=mock_heartbeater)
    mock_heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.HeartbeaterSync",
        MagicMock(return_value=mock_heartbeater),
    )

    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.configure_connection",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.ensure_ducklake_bucket_exists",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._attach_ducklake_catalog",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.get_config",
        MagicMock(return_value={}),
    )

    metadata = DuckLakeCopyDataImportsMetadata(
        model_label="postgres_customers",
        source_schema_id="schema-123",
        source_schema_name="customers",
        source_normalized_name="customers",
        source_table_uri="s3://bucket/team_1/customers",
        ducklake_schema_name="data_imports_team_1",
        ducklake_table_name="postgres_customers_abc12345",
    )
    inputs = DuckLakeCopyDataImportsActivityInputs(team_id=1, job_id="job-123", model=metadata)

    copy_data_imports_to_ducklake_activity(inputs)

    execute_calls = mock_conn.execute.call_args_list
    assert any("CREATE SCHEMA IF NOT EXISTS" in str(call) for call in execute_calls)
    assert any("CREATE OR REPLACE TABLE" in str(call) for call in execute_calls)
    assert any("delta_scan" in str(call) for call in execute_calls)
    mock_conn.__exit__.assert_called_once()


def test_verify_data_imports_ducklake_copy_activity_returns_empty_when_no_queries(monkeypatch):
    mock_heartbeater = MagicMock()
    mock_heartbeater.__enter__ = MagicMock(return_value=mock_heartbeater)
    mock_heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.HeartbeaterSync",
        MagicMock(return_value=mock_heartbeater),
    )

    metadata = DuckLakeCopyDataImportsMetadata(
        model_label="postgres_customers",
        source_schema_id="schema-123",
        source_schema_name="customers",
        source_normalized_name="customers",
        source_table_uri="s3://bucket/team_1/customers",
        ducklake_schema_name="data_imports_team_1",
        ducklake_table_name="postgres_customers_abc12345",
        verification_queries=[],
    )
    inputs = DuckLakeCopyDataImportsActivityInputs(team_id=1, job_id="job-123", model=metadata)

    results = verify_data_imports_ducklake_copy_activity(inputs)

    assert results == []


def test_verify_data_imports_ducklake_copy_activity_executes_configured_query(monkeypatch):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchone.return_value = (0,)
    mock_duckdb_connect = MagicMock(return_value=mock_conn)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.duckdb.connect",
        mock_duckdb_connect,
    )

    mock_heartbeater = MagicMock()
    mock_heartbeater.__enter__ = MagicMock(return_value=mock_heartbeater)
    mock_heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.HeartbeaterSync",
        MagicMock(return_value=mock_heartbeater),
    )

    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.configure_connection",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._attach_ducklake_catalog",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.get_config",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._run_data_imports_schema_verification",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._run_data_imports_partition_verification",
        MagicMock(return_value=None),
    )

    query = DuckLakeCopyVerificationQuery(
        name="row_count_check",
        sql="SELECT ABS((SELECT COUNT(*) FROM delta_scan(?)) - (SELECT COUNT(*) FROM {ducklake_table})) AS diff",
        description="Compare row counts",
        parameters=(DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI,),
        expected_value=0.0,
        tolerance=0.0,
    )

    metadata = DuckLakeCopyDataImportsMetadata(
        model_label="postgres_customers",
        source_schema_id="schema-123",
        source_schema_name="customers",
        source_normalized_name="customers",
        source_table_uri="s3://bucket/team_1/customers",
        ducklake_schema_name="data_imports_team_1",
        ducklake_table_name="postgres_customers_abc12345",
        verification_queries=[query],
    )
    inputs = DuckLakeCopyDataImportsActivityInputs(team_id=1, job_id="job-123", model=metadata)

    results = verify_data_imports_ducklake_copy_activity(inputs)

    assert len(results) == 1
    assert results[0].name == "row_count_check"
    assert results[0].passed is True
    assert results[0].observed_value == 0.0
    mock_conn.__exit__.assert_called_once()


def test_verify_data_imports_ducklake_copy_activity_handles_query_failure(monkeypatch):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.side_effect = Exception("Query execution failed")
    mock_duckdb_connect = MagicMock(return_value=mock_conn)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.duckdb.connect",
        mock_duckdb_connect,
    )

    mock_heartbeater = MagicMock()
    mock_heartbeater.__enter__ = MagicMock(return_value=mock_heartbeater)
    mock_heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.HeartbeaterSync",
        MagicMock(return_value=mock_heartbeater),
    )

    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.configure_connection",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._attach_ducklake_catalog",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.get_config",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._run_data_imports_schema_verification",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._run_data_imports_partition_verification",
        MagicMock(return_value=None),
    )

    query = DuckLakeCopyVerificationQuery(
        name="failing_query",
        sql="SELECT 1",
        description="A query that fails",
        parameters=(),
        expected_value=0.0,
        tolerance=0.0,
    )

    metadata = DuckLakeCopyDataImportsMetadata(
        model_label="postgres_customers",
        source_schema_id="schema-123",
        source_schema_name="customers",
        source_normalized_name="customers",
        source_table_uri="s3://bucket/team_1/customers",
        ducklake_schema_name="data_imports_team_1",
        ducklake_table_name="postgres_customers_abc12345",
        verification_queries=[query],
    )
    inputs = DuckLakeCopyDataImportsActivityInputs(team_id=1, job_id="job-123", model=metadata)

    results = verify_data_imports_ducklake_copy_activity(inputs)

    assert len(results) == 1
    assert results[0].name == "failing_query"
    assert results[0].passed is False
    assert results[0].error == "Query execution failed"
    mock_conn.__exit__.assert_called_once()


def test_verify_data_imports_ducklake_copy_activity_tolerance_comparison(monkeypatch):
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchone.return_value = (5,)
    mock_duckdb_connect = MagicMock(return_value=mock_conn)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.duckdb.connect",
        mock_duckdb_connect,
    )

    mock_heartbeater = MagicMock()
    mock_heartbeater.__enter__ = MagicMock(return_value=mock_heartbeater)
    mock_heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.HeartbeaterSync",
        MagicMock(return_value=mock_heartbeater),
    )

    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.configure_connection",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._attach_ducklake_catalog",
        MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow.get_config",
        MagicMock(return_value={}),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._run_data_imports_schema_verification",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "posthog.temporal.ducklake.ducklake_copy_data_imports_workflow._run_data_imports_partition_verification",
        MagicMock(return_value=None),
    )

    query_pass = DuckLakeCopyVerificationQuery(
        name="within_tolerance",
        sql="SELECT 5",
        description="Should pass with tolerance",
        parameters=(),
        expected_value=0.0,
        tolerance=10.0,
    )

    query_fail = DuckLakeCopyVerificationQuery(
        name="outside_tolerance",
        sql="SELECT 5",
        description="Should fail outside tolerance",
        parameters=(),
        expected_value=0.0,
        tolerance=2.0,
    )

    metadata = DuckLakeCopyDataImportsMetadata(
        model_label="postgres_customers",
        source_schema_id="schema-123",
        source_schema_name="customers",
        source_normalized_name="customers",
        source_table_uri="s3://bucket/team_1/customers",
        ducklake_schema_name="data_imports_team_1",
        ducklake_table_name="postgres_customers_abc12345",
        verification_queries=[query_pass, query_fail],
    )
    inputs = DuckLakeCopyDataImportsActivityInputs(team_id=1, job_id="job-123", model=metadata)

    results = verify_data_imports_ducklake_copy_activity(inputs)

    assert len(results) == 2
    assert results[0].name == "within_tolerance"
    assert results[0].passed is True
    assert results[1].name == "outside_tolerance"
    assert results[1].passed is False


def test_ducklake_copy_data_imports_workflow_parse_inputs():
    schema_id = uuid.uuid4()
    json_input = f"""{{
        "team_id": 1,
        "job_id": "job-123",
        "schema_ids": ["{schema_id}"]
    }}"""

    inputs = DuckLakeCopyDataImportsWorkflow.parse_inputs([json_input])

    assert inputs.team_id == 1
    assert inputs.job_id == "job-123"
    assert len(inputs.schema_ids) == 1
    assert inputs.schema_ids[0] == schema_id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_ducklake_copy_data_imports_workflow_skips_when_feature_flag_disabled(monkeypatch, ateam):
    call_counts = {"metadata": 0, "copy": 0}

    @temporal_activity.defn
    async def metadata_stub(inputs: DataImportsDuckLakeCopyInputs):
        call_counts["metadata"] += 1
        return [
            DuckLakeCopyDataImportsMetadata(
                model_label="postgres_customers",
                source_schema_id="schema-123",
                source_schema_name="customers",
                source_normalized_name="customers",
                source_table_uri="s3://bucket/team_1/customers",
                ducklake_schema_name="data_imports_team_1",
                ducklake_table_name="postgres_customers_abc12345",
            )
        ]

    @temporal_activity.defn
    async def copy_stub(inputs: DuckLakeCopyDataImportsActivityInputs):
        call_counts["copy"] += 1

    monkeypatch.setattr(
        ducklake_module.posthoganalytics,
        "feature_enabled",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(ducklake_module, "prepare_data_imports_ducklake_metadata_activity", metadata_stub)
    monkeypatch.setattr(ducklake_module, "copy_data_imports_to_ducklake_activity", copy_stub)

    inputs = DataImportsDuckLakeCopyInputs(
        team_id=ateam.pk,
        job_id="job",
        schema_ids=[uuid.uuid4()],
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with temporalio.worker.Worker(
            env.client,
            task_queue="ducklake-data-imports-test",
            workflows=[DuckLakeCopyDataImportsWorkflow],
            activities=[
                ducklake_copy_data_imports_gate_activity,
                ducklake_module.prepare_data_imports_ducklake_metadata_activity,
                ducklake_module.copy_data_imports_to_ducklake_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DuckLakeCopyDataImportsWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue="ducklake-data-imports-test",
                execution_timeout=dt.timedelta(seconds=30),
            )

    assert call_counts["metadata"] == 0
    assert call_counts["copy"] == 0


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_ducklake_copy_data_imports_workflow_runs_when_feature_flag_enabled(monkeypatch, ateam):
    call_counts = {"metadata": 0, "copy": 0, "verify": 0}

    @temporal_activity.defn
    async def metadata_stub(inputs: DataImportsDuckLakeCopyInputs):
        call_counts["metadata"] += 1
        return [
            DuckLakeCopyDataImportsMetadata(
                model_label="postgres_customers",
                source_schema_id="schema-123",
                source_schema_name="customers",
                source_normalized_name="customers",
                source_table_uri="s3://bucket/team_1/customers",
                ducklake_schema_name="data_imports_team_1",
                ducklake_table_name="postgres_customers_abc12345",
            )
        ]

    @temporal_activity.defn
    async def copy_stub(inputs: DuckLakeCopyDataImportsActivityInputs):
        call_counts["copy"] += 1

    @temporal_activity.defn
    async def verify_stub(inputs: DuckLakeCopyDataImportsActivityInputs):
        call_counts["verify"] += 1
        return []

    monkeypatch.setattr(
        ducklake_module.posthoganalytics,
        "feature_enabled",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(ducklake_module, "prepare_data_imports_ducklake_metadata_activity", metadata_stub)
    monkeypatch.setattr(ducklake_module, "copy_data_imports_to_ducklake_activity", copy_stub)
    monkeypatch.setattr(ducklake_module, "verify_data_imports_ducklake_copy_activity", verify_stub)

    inputs = DataImportsDuckLakeCopyInputs(
        team_id=ateam.pk,
        job_id="job",
        schema_ids=[uuid.uuid4()],
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with temporalio.worker.Worker(
            env.client,
            task_queue="ducklake-data-imports-test",
            workflows=[DuckLakeCopyDataImportsWorkflow],
            activities=[
                ducklake_copy_data_imports_gate_activity,
                ducklake_module.prepare_data_imports_ducklake_metadata_activity,
                ducklake_module.copy_data_imports_to_ducklake_activity,
                ducklake_module.verify_data_imports_ducklake_copy_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                DuckLakeCopyDataImportsWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue="ducklake-data-imports-test",
                execution_timeout=dt.timedelta(seconds=30),
            )

    assert call_counts["metadata"] == 1
    assert call_counts["copy"] == 1
    assert call_counts["verify"] == 1
