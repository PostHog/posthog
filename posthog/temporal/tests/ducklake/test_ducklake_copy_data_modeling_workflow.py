import uuid
import datetime as dt
from typing import cast

import pytest
import unittest.mock

from django.test import override_settings

import duckdb
import temporalio.worker
from temporalio import activity as temporal_activity
from temporalio.testing import WorkflowEnvironment

import posthog.ducklake.verification.config as verification_config
from posthog.ducklake.verification import DuckLakeCopyVerificationParameter, DuckLakeCopyVerificationQuery
from posthog.temporal.ducklake import ducklake_copy_data_modeling_workflow as ducklake_module
from posthog.temporal.ducklake.ducklake_copy_data_modeling_workflow import (
    DuckLakeCopyActivityInputs,
    DuckLakeCopyModelMetadata,
    DuckLakeCopyVerificationResult,
    copy_data_modeling_model_to_ducklake_activity,
    prepare_data_modeling_ducklake_metadata_activity,
    verify_ducklake_copy_activity,
)
from posthog.temporal.ducklake.types import DataModelingDuckLakeCopyInputs, DuckLakeCopyModelInput

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
    inputs = DataModelingDuckLakeCopyInputs(
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
    monkeypatch.setenv("DUCKLAKE_BUCKET", "ducklake-test-bucket")
    # Mock Delta partition column detection
    monkeypatch.setattr(ducklake_module, "_fetch_delta_partition_columns", lambda table_uri: ["timestamp"])

    metadata = await activity_environment.run(prepare_data_modeling_ducklake_metadata_activity, inputs)

    assert len(metadata) == 1
    model_metadata = metadata[0]
    assert model_metadata.model_label == saved_query.id.hex
    assert model_metadata.saved_query_name == saved_query.name
    assert model_metadata.source_table_uri == table_uri
    assert model_metadata.schema_name == f"data_modeling_team_{ateam.pk}"
    assert model_metadata.table_name == f"model_{saved_query.id.hex}"
    assert model_metadata.verification_queries
    assert model_metadata.verification_queries[0].name == "row_count_delta_vs_ducklake"
    assert model_metadata.partition_column == "timestamp"


def test_detect_partition_column_name_returns_first_partition(monkeypatch):
    monkeypatch.setattr(
        ducklake_module, "_fetch_delta_partition_columns", lambda table_uri: ["partition_ts", "timestamp"]
    )

    column = ducklake_module._detect_partition_column_name("s3://source/table")

    assert column == "partition_ts"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_data_modeling_ducklake_metadata_activity_applies_yaml_overrides(
    activity_environment, ateam, monkeypatch, request
):
    override_label = "override_only_model"
    inherited_label = "inherits_defaults_model"
    override_config = {
        "defaults": {
            "queries": [
                {
                    "name": "default_row_check",
                    "sql": "SELECT COUNT(*) FROM {ducklake_table}",
                    "tolerance": 0,
                }
            ]
        },
        "models": {
            override_label: {
                "inherit_defaults": False,
                "queries": [
                    {"name": "override_only_check", "sql": "SELECT 1", "tolerance": 5},
                ],
            },
            inherited_label: {
                "queries": [
                    {"name": "inherited_extra_check", "sql": "SELECT 2", "tolerance": 2},
                ],
            },
        },
    }
    monkeypatch.setattr(verification_config, "_load_verification_yaml", lambda filename: override_config)
    verification_config._get_data_modeling_verification_config.cache_clear()
    request.addfinalizer(verification_config._get_data_modeling_verification_config.cache_clear)

    override_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="override_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
    )
    inherit_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="inherit_model",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
    )

    def _table_uri(saved_query):
        return f"s3://source/team_{ateam.pk}_model_{saved_query.id.hex}/modeling/{saved_query.normalized_name}"

    override_table_uri = _table_uri(override_query)
    inherit_table_uri = _table_uri(inherit_query)

    inputs = DataModelingDuckLakeCopyInputs(
        team_id=ateam.pk,
        job_id=uuid.uuid4().hex,
        models=[
            DuckLakeCopyModelInput(
                model_label=override_label,
                saved_query_id=str(override_query.id),
                table_uri=override_table_uri,
            ),
            DuckLakeCopyModelInput(
                model_label=inherited_label,
                saved_query_id=str(inherit_query.id),
                table_uri=inherit_table_uri,
            ),
        ],
    )

    metadata = await activity_environment.run(prepare_data_modeling_ducklake_metadata_activity, inputs)

    assert len(metadata) == 2
    override_metadata = next(item for item in metadata if item.model_label == override_label)
    inherit_metadata = next(item for item in metadata if item.model_label == inherited_label)

    assert [query.name for query in override_metadata.verification_queries] == ["override_only_check"]
    assert override_metadata.verification_queries[0].tolerance == 5.0
    assert [query.name for query in inherit_metadata.verification_queries] == [
        "default_row_check",
        "inherited_extra_check",
    ]


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

    configured: dict[str, bool] = {"called": False}

    def fake_configure(conn):
        configured["called"] = True

    monkeypatch.setattr(ducklake_module, "configure_connection", fake_configure)

    ensured: dict[str, bool] = {"called": False}

    def fake_ensure_bucket(storage_config=None, config=None):
        ensured["called"] = True

    monkeypatch.setattr(ducklake_module, "ensure_ducklake_bucket_exists", fake_ensure_bucket)

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_a",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_a",
        verification_queries=[],
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
    table_calls = [
        (statement, params) for statement, params in fake_conn_calls if statement.startswith("CREATE OR REPLACE TABLE")
    ]

    assert configured["called"] is True
    assert ensured["called"] is True
    assert schema_calls and "ducklake.data_modeling_team_1" in schema_calls[0]
    assert table_calls and "ducklake.data_modeling_team_1.model_a" in table_calls[0][0]
    assert "delta_scan(?)" in table_calls[0][0]
    assert table_calls[0][1] == (metadata.source_table_uri,)
    assert any("ATTACH" in statement for statement in fake_conn.sql_statements), "Expected DuckLake catalog attach"
    assert fake_conn.closed is True


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_verify_ducklake_copy_activity_runs_queries(monkeypatch, activity_environment):
    class FakeDuckDBConnection:
        def __init__(self, rows: list[tuple]):
            self.rows = rows
            self.closed = False
            self.executed: list[tuple[str, tuple]] = []
            self.sql_statements: list[str] = []

        def execute(self, statement: str, params: list | None = None):
            self.executed.append((statement, tuple(params or [])))
            return self

        def sql(self, statement: str):
            self.sql_statements.append(statement)

        def fetchone(self):
            return self.rows.pop(0) if self.rows else None

        def close(self):
            self.closed = True

    fake_conn = FakeDuckDBConnection(rows=[(0,)])
    monkeypatch.setattr(ducklake_module.duckdb, "connect", lambda: fake_conn)
    monkeypatch.setattr(ducklake_module, "_run_schema_verification", lambda *args, **kwargs: None)
    monkeypatch.setattr(ducklake_module, "_run_partition_verification", lambda *args, **kwargs: None)

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_a",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_a",
        verification_queries=[
            DuckLakeCopyVerificationQuery(
                name="row_count",
                sql="SELECT COUNT(*) FROM delta_scan(?)",
                parameters=(DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI,),
                tolerance=0,
            )
        ],
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-verify", model=metadata)

    results = activity_environment.run(verify_ducklake_copy_activity, inputs)

    assert len(results) == 1
    assert results[0].passed is True
    assert fake_conn.closed is True
    ducklake_call = next((call for call in fake_conn.executed if "delta_scan" in call[0]), None)
    assert ducklake_call is not None
    assert ducklake_call[1][0] == metadata.source_table_uri


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_ducklake_copy_workflow_skips_when_feature_flag_disabled(monkeypatch, ateam):
    call_counts = {"metadata": 0, "copy": 0}

    @temporal_activity.defn
    async def metadata_stub(inputs: DataModelingDuckLakeCopyInputs):
        call_counts["metadata"] += 1
        return [
            DuckLakeCopyModelMetadata(
                model_label="model",
                saved_query_id=str(uuid.uuid4()),
                saved_query_name="model",
                normalized_name="model",
                source_table_uri="s3://source/table",
                schema_name="data_modeling_team_1",
                table_name="model",
            )
        ]

    @temporal_activity.defn
    async def copy_stub(inputs: DuckLakeCopyActivityInputs):
        call_counts["copy"] += 1

    monkeypatch.setattr(
        ducklake_module.posthoganalytics,
        "feature_enabled",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(ducklake_module, "prepare_data_modeling_ducklake_metadata_activity", metadata_stub)
    monkeypatch.setattr(ducklake_module, "copy_data_modeling_model_to_ducklake_activity", copy_stub)

    inputs = DataModelingDuckLakeCopyInputs(
        team_id=ateam.pk,
        job_id="job",
        models=[
            DuckLakeCopyModelInput(
                model_label="model",
                saved_query_id=str(uuid.uuid4()),
                table_uri="s3://source/table",
            )
        ],
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with temporalio.worker.Worker(
            env.client,
            task_queue="ducklake-test",
            workflows=[ducklake_module.DuckLakeCopyDataModelingWorkflow],
            activities=[
                ducklake_module.ducklake_copy_workflow_gate_activity,
                ducklake_module.prepare_data_modeling_ducklake_metadata_activity,
                ducklake_module.copy_data_modeling_model_to_ducklake_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ducklake_module.DuckLakeCopyDataModelingWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue="ducklake-test",
                execution_timeout=dt.timedelta(seconds=30),
            )

    assert call_counts["metadata"] == 0
    assert call_counts["copy"] == 0


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_verify_ducklake_copy_activity_reports_failures(monkeypatch, activity_environment):
    class FakeDuckDBConnection:
        def __init__(self, rows: list[tuple]):
            self.rows = rows
            self.closed = False
            self.sql_statements: list[str] = []

        def execute(self, statement: str, params: list | None = None):
            return self

        def sql(self, statement: str):
            self.sql_statements.append(statement)

        def fetchone(self):
            return self.rows.pop(0) if self.rows else None

        def close(self):
            self.closed = True

    fake_conn = FakeDuckDBConnection(rows=[(10,)])
    monkeypatch.setattr(ducklake_module.duckdb, "connect", lambda: fake_conn)
    monkeypatch.setattr(ducklake_module, "_run_schema_verification", lambda *args, **kwargs: None)
    monkeypatch.setattr(ducklake_module, "_run_partition_verification", lambda *args, **kwargs: None)

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_b",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_b",
        verification_queries=[
            DuckLakeCopyVerificationQuery(
                name="row_count",
                sql="SELECT COUNT(*) FROM delta_scan(?)",
                parameters=(DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI,),
                tolerance=0,
            )
        ],
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-verify", model=metadata)

    results = activity_environment.run(verify_ducklake_copy_activity, inputs)

    assert len(results) == 1
    assert results[0].passed is False
    assert fake_conn.closed is True


def test_run_partition_verification_without_temporal_type():
    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConn:
        def __init__(self):
            self.statements: list[str] = []

        def execute(self, statement: str, params: list | None = None):
            self.statements.append(statement)
            return FakeCursor()

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_partition_string",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_partition_string",
        verification_queries=[],
        partition_column="event_id",
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-partition", model=metadata)
    fake_conn = FakeConn()
    conn = cast(duckdb.DuckDBPyConnection, fake_conn)

    with unittest.mock.patch.object(ducklake_module, "_fetch_delta_schema", return_value=[("event_id", "String")]):
        result = ducklake_module._run_partition_verification(conn, "ducklake.schema.table", inputs)

    assert result is not None and result.passed is True
    assert fake_conn.statements and "date_trunc" not in fake_conn.statements[0]


def test_run_partition_verification_with_temporal_type():
    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConn:
        def __init__(self):
            self.statements: list[str] = []

        def execute(self, statement: str, params: list | None = None):
            self.statements.append(statement)
            return FakeCursor()

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_partition_time",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_partition_time",
        verification_queries=[],
        partition_column="timestamp",
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-partition", model=metadata)
    fake_conn = FakeConn()
    conn = cast(duckdb.DuckDBPyConnection, fake_conn)

    with unittest.mock.patch.object(ducklake_module, "_fetch_delta_schema", return_value=[("timestamp", "DateTime64")]):
        result = ducklake_module._run_partition_verification(conn, "ducklake.schema.table", inputs)

    assert result is not None and result.passed is True
    assert fake_conn.statements and "date_trunc" in fake_conn.statements[0]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    ("observed", "expected", "tolerance", "should_pass"),
    [
        (101.0, 100.0, 2.0, True),
        (110.0, 100.0, 5.0, False),
    ],
)
async def test_verify_ducklake_copy_activity_respects_tolerance(
    monkeypatch, activity_environment, observed, expected, tolerance, should_pass
):
    class FakeDuckDBConnection:
        def __init__(self, value: float):
            self.value = value
            self.closed = False
            self.sql_statements: list[str] = []

        def execute(self, statement: str, params: list | None = None):
            self.sql_statements.append(statement)
            return self

        def sql(self, statement: str):
            self.sql_statements.append(statement)

        def fetchone(self):
            return (self.value,)

        def close(self):
            self.closed = True

    fake_conn = FakeDuckDBConnection(observed)
    monkeypatch.setattr(ducklake_module.duckdb, "connect", lambda: fake_conn)
    monkeypatch.setattr(ducklake_module, "_run_schema_verification", lambda *args, **kwargs: None)
    monkeypatch.setattr(ducklake_module, "_run_partition_verification", lambda *args, **kwargs: None)

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_tolerance",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_tolerance",
        verification_queries=[
            DuckLakeCopyVerificationQuery(
                name="row_difference",
                sql="SELECT 1",
                tolerance=tolerance,
                expected_value=expected,
            )
        ],
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-tolerance", model=metadata)

    results = activity_environment.run(verify_ducklake_copy_activity, inputs)

    assert len(results) == 1
    assert results[0].passed is should_pass
    assert results[0].tolerance == tolerance
    assert results[0].expected_value == expected
    assert fake_conn.closed is True


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_verify_ducklake_copy_activity_includes_additional_checks(monkeypatch, activity_environment):
    class FakeDuckDBConnection:
        def __init__(self):
            self.closed = False
            self.sql_statements: list[str] = []

        def execute(self, statement: str, params: list | None = None):
            self.sql_statements.append(statement)
            return self

        def sql(self, statement: str):
            self.sql_statements.append(statement)

        def fetchone(self):
            return (0, 0)

        def fetchall(self):
            return []

        def close(self):
            self.closed = True

    fake_conn = FakeDuckDBConnection()
    monkeypatch.setattr(ducklake_module.duckdb, "connect", lambda: fake_conn)

    schema_result = DuckLakeCopyVerificationResult(name="model.schema_hash", passed=True)
    partition_result = DuckLakeCopyVerificationResult(name="model.partition_counts", passed=True)

    monkeypatch.setattr(ducklake_module, "_run_schema_verification", lambda *args, **kwargs: schema_result)
    monkeypatch.setattr(ducklake_module, "_run_partition_verification", lambda *args, **kwargs: partition_result)

    metadata = DuckLakeCopyModelMetadata(
        model_label="model_c",
        saved_query_id=str(uuid.uuid4()),
        saved_query_name="ducklake_model",
        normalized_name="ducklake_model",
        source_table_uri="s3://source/table",
        schema_name="data_modeling_team_1",
        table_name="model_c",
        verification_queries=[
            DuckLakeCopyVerificationQuery(
                name="noop",
                sql="SELECT 0",
                tolerance=0,
            )
        ],
        partition_column="timestamp",
    )
    inputs = DuckLakeCopyActivityInputs(team_id=1, job_id="job-verify", model=metadata)

    results = activity_environment.run(verify_ducklake_copy_activity, inputs)

    assert schema_result in results
    assert partition_result in results


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_ducklake_copy_workflow_runs_when_feature_flag_enabled(monkeypatch, ateam):
    call_counts = {"metadata": 0, "copy": 0}

    @temporal_activity.defn
    async def metadata_stub(inputs: DataModelingDuckLakeCopyInputs):
        call_counts["metadata"] += 1

        return [
            DuckLakeCopyModelMetadata(
                model_label="model",
                saved_query_id=str(uuid.uuid4()),
                saved_query_name="model",
                normalized_name="model",
                source_table_uri="s3://source/table",
                schema_name="data_modeling_team_1",
                table_name="model",
            )
        ]

    @temporal_activity.defn
    async def copy_stub(inputs: DuckLakeCopyActivityInputs):
        call_counts["copy"] += 1

    @temporal_activity.defn
    async def verify_stub(inputs: DuckLakeCopyActivityInputs):
        return []

    monkeypatch.setattr(
        ducklake_module.posthoganalytics,
        "feature_enabled",
        lambda *args, **kwargs: True,
    )

    monkeypatch.setattr(ducklake_module, "prepare_data_modeling_ducklake_metadata_activity", metadata_stub)

    monkeypatch.setattr(ducklake_module, "copy_data_modeling_model_to_ducklake_activity", copy_stub)

    monkeypatch.setattr(ducklake_module, "verify_ducklake_copy_activity", verify_stub)

    inputs = DataModelingDuckLakeCopyInputs(
        team_id=ateam.pk,
        job_id="job",
        models=[
            DuckLakeCopyModelInput(
                model_label="model",
                saved_query_id=str(uuid.uuid4()),
                table_uri="s3://source/table",
            )
        ],
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with temporalio.worker.Worker(
            env.client,
            task_queue="ducklake-test",
            workflows=[ducklake_module.DuckLakeCopyDataModelingWorkflow],
            activities=[
                ducklake_module.ducklake_copy_workflow_gate_activity,
                ducklake_module.prepare_data_modeling_ducklake_metadata_activity,
                ducklake_module.copy_data_modeling_model_to_ducklake_activity,
                ducklake_module.verify_ducklake_copy_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ducklake_module.DuckLakeCopyDataModelingWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue="ducklake-test",
                execution_timeout=dt.timedelta(seconds=30),
            )

    assert call_counts["metadata"] == 1

    assert call_counts["copy"] == 1
