import uuid
import datetime as dt
import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.ducklake import cp_teams
from posthog.sync import database_sync_to_async
from posthog.temporal.ducklake import ducklake_register_data_imports_workflow as registration_module
from posthog.temporal.ducklake.ducklake_register_data_imports_workflow import (
    DUCKLAKE_DATA_IMPORTS_REGISTRATION_WORKFLOW_FLAG,
    DuckLakeRegisterDataImportsActivityInputs,
    DuckLakeRegisterDataImportsGateInputs,
    DuckLakeRegisterDataImportsInputs,
    DuckLakeRegisterDataImportsMetadata,
    DuckLakeRegisterDataImportsWorkflow,
    build_register_data_imports_workflow_id,
    copy_and_register_ducklake_data_imports_activity,
    ducklake_register_data_imports_gate_activity,
    prepare_ducklake_data_imports_registration_activity,
)

from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)


@pytest.fixture(autouse=True)
def _cp_no_rows():
    from unittest.mock import patch

    cp_teams.clear_cache()
    with patch("posthog.ducklake.cp_teams._fetch_org_rows", return_value=[]):
        yield
    cp_teams.clear_cache()


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("flag_enabled", [True, False])
async def test_registration_gate_uses_independent_feature_flag(monkeypatch, ateam, flag_enabled):
    captured: dict[str, object] = {}

    def fake_feature_enabled(key, distinct_id, **kwargs):
        captured.update(key=key, distinct_id=distinct_id, **kwargs)
        return flag_enabled

    monkeypatch.setattr(registration_module, "feature_enabled_or_false", fake_feature_enabled)

    result = await ducklake_register_data_imports_gate_activity(DuckLakeRegisterDataImportsGateInputs(team_id=ateam.id))

    assert result is flag_enabled
    assert captured["key"] == DUCKLAKE_DATA_IMPORTS_REGISTRATION_WORKFLOW_FLAG
    assert captured["distinct_id"] == str(ateam.uuid)
    assert captured["groups"] == {
        "organization": str(ateam.organization_id),
        "project": str(ateam.id),
    }
    assert captured["only_evaluate_locally"] is True
    assert captured["send_feature_flag_events"] is False


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_registration_pins_the_import_jobs_prepared_generation(ateam):
    credential = await database_sync_to_async(DataWarehouseCredential.objects.create)(
        team=ateam,
        access_key="test_key",
        access_secret="test_secret",
    )
    source = await database_sync_to_async(ExternalDataSource.objects.create)(
        team=ateam,
        source_id="source",
        connection_id="connection",
        source_type="Postgres",
        status="Running",
    )
    prepared_queryable_folder = "customers__query_1234567890_abcdef12"
    table = await database_sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name="customers",
        format="Delta",
        url_pattern="s3://bucket/path",
        credential=credential,
        external_data_source=source,
        columns={"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}},
        queryable_folder=prepared_queryable_folder,
    )
    schema = await database_sync_to_async(ExternalDataSchema.objects.create)(
        team=ateam,
        name="customers",
        source=source,
        table=table,
    )

    metadata = await prepare_ducklake_data_imports_registration_activity(
        DuckLakeRegisterDataImportsInputs(
            team_id=ateam.id,
            job_id="job-123",
            schema_id=schema.id,
            prepared_queryable_folder=prepared_queryable_folder,
        )
    )

    assert metadata is not None
    folder_path = await database_sync_to_async(schema.folder_path)()
    assert metadata.prepared_source_uri.endswith(f"/{folder_path}/{prepared_queryable_folder}")
    assert metadata.landing_uri == (
        f"s3://ducklake-dev/posthog_data_imports_team_{ateam.id}/postgres_customers/_imports/{schema.id}/job-123"
    )
    assert metadata.ducklake_schema_name == f"posthog_data_imports_team_{ateam.id}"
    assert metadata.ducklake_table_name == "postgres_customers"


def test_copy_activity_uses_s3_copy_and_local_duckgres_postgres_connection(monkeypatch):
    class FakeS3:
        def __init__(self) -> None:
            self.copies: list[tuple[str, str]] = []

        def find(self, prefix: str, detail: bool = False):
            files = {
                f"{prefix}/_ph_partition_key=2026-07/a.parquet": {"Size": 100, "type": "file"},
                f"{prefix}/_ph_partition_key=2026-08/b.parquet": {"Size": 200, "type": "file"},
            }
            return files if detail else list(files)

        def copy(self, source: str, destination: str) -> None:
            self.copies.append((source, destination))

    s3 = FakeS3()
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: s3)
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: True)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: True)
    monkeypatch.setattr(registration_module, "make_duckgres_conninfo", lambda team_id: "postgresql://duckgres")

    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.transaction.return_value.__enter__ = MagicMock()
    conn.transaction.return_value.__exit__ = MagicMock(return_value=False)

    def execute(query: object) -> MagicMock:
        query_text = str(query)
        if "SELECT count(*) FROM read_parquet" in query_text:
            return MagicMock(fetchone=MagicMock(return_value=(2,)))
        if "SELECT count(*) FROM" in query_text:
            return MagicMock(fetchone=MagicMock(return_value=(2,)))
        return MagicMock()

    conn.execute.side_effect = execute
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(registration_module.psycopg, "connect", connect)
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))
    workload_metrics = _mock_activity_workload_metrics(monkeypatch)

    inputs = _activity_inputs()
    applied = copy_and_register_ducklake_data_imports_activity(inputs)

    assert applied is True
    connect.assert_called_once_with("postgresql://duckgres", autocommit=True)
    assert s3.copies == [
        (
            "source/team/customers__query/_ph_partition_key=2026-07/a.parquet",
            "ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
            "_ph_partition_key=2026-07/a.parquet",
        ),
        (
            "source/team/customers__query/_ph_partition_key=2026-08/b.parquet",
            "ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
            "_ph_partition_key=2026-08/b.parquet",
        ),
    ]
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    registration_indexes = [index for index, query in enumerate(executed) if "ducklake_add_data_files" in query]
    verification_indexes = [index for index, query in enumerate(executed) if "SELECT count(*) FROM" in query]
    drop_live_index = next(
        index for index, query in enumerate(executed) if "DROP TABLE IF EXISTS" in query and "customers" in query
    )
    rename_index = next(index for index, query in enumerate(executed) if "RENAME TO" in query)
    assert len(registration_indexes) == 2
    assert len(verification_indexes) == 2
    assert max(registration_indexes) < min(verification_indexes)
    assert max(verification_indexes) < drop_live_index < rename_index
    assert any("SET PARTITIONED BY" in query for query in executed)
    workload_metrics.files_getter.assert_called_once_with(team_id=1, schema_id="schema")
    workload_metrics.rows_getter.assert_called_once_with(team_id=1, schema_id="schema")
    workload_metrics.bytes_getter.assert_called_once_with(team_id=1, schema_id="schema")
    workload_metrics.files.record.assert_called_once_with(2.0)
    workload_metrics.rows.record.assert_called_once_with(2.0)
    workload_metrics.bytes.record.assert_called_once_with(300.0)


def test_copy_activity_does_not_touch_catalog_for_stale_generation(monkeypatch):
    monkeypatch.setattr(
        registration_module,
        "_copy_prepared_parquet_files",
        lambda source_uri, landing_uri: ([f"{landing_uri}/file.parquet"], 100),
    )
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: False)
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        MagicMock(side_effect=AssertionError("stale generations must not update the catalog")),
    )
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))
    stale_counter = MagicMock()
    stale_metric = MagicMock(return_value=stale_counter)
    monkeypatch.setattr(registration_module, "get_ducklake_register_data_imports_stale_metric", stale_metric)
    workload_metrics = _mock_activity_workload_metrics(monkeypatch)

    assert copy_and_register_ducklake_data_imports_activity(_activity_inputs()) is False
    stale_metric.assert_called_once_with(team_id=1, schema_id="schema", stage="post_copy")
    stale_counter.add.assert_called_once_with(1)
    workload_metrics.files.record.assert_not_called()
    workload_metrics.rows.record.assert_not_called()
    workload_metrics.bytes.record.assert_not_called()


def test_copy_activity_does_not_publish_a_row_count_mismatch(monkeypatch):
    monkeypatch.setattr(
        registration_module,
        "_copy_prepared_parquet_files",
        lambda source_uri, landing_uri: ([f"{landing_uri}/file.parquet"], 100),
    )
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: True)
    conn = MagicMock()
    conn.transaction.return_value.__enter__ = MagicMock()
    conn.transaction.return_value.__exit__ = MagicMock(return_value=False)
    counts = iter([(10,), (9,)])

    def execute(query: object) -> MagicMock:
        if "SELECT count(*) FROM" in str(query):
            return MagicMock(fetchone=MagicMock(return_value=next(counts)))
        return MagicMock()

    conn.execute.side_effect = execute
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        lambda team_id: contextlib.nullcontext(conn),
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))

    with pytest.raises(ApplicationError, match="row count mismatch"):
        copy_and_register_ducklake_data_imports_activity(_activity_inputs())

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert not any("DROP TABLE IF EXISTS" in query and "customers" in query for query in executed)
    assert not any("RENAME TO" in query for query in executed)


@pytest.mark.asyncio
async def test_workflow_does_not_record_duration_when_disabled(monkeypatch):
    execute_activity = AsyncMock(return_value=False)
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "now", MagicMock(return_value=dt.datetime(2026, 7, 30)))

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    metrics.started_getter.assert_not_called()
    metrics.duration_getter.assert_not_called()
    metrics.finished_getter.assert_not_called()
    metrics.last_success_getter.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_records_end_to_end_duration_after_gate(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    finished_at = started_at + dt.timedelta(minutes=7, seconds=12)
    execute_activity = AsyncMock(side_effect=[True, _activity_inputs().metadata, True])
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "now", MagicMock(side_effect=[started_at, finished_at]))

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    metric_identifiers = {"team_id": 1, "schema_id": str(_workflow_inputs().schema_id)}
    metrics.started_getter.assert_called_once_with(**metric_identifiers)
    metrics.started.add.assert_called_once_with(1)
    metrics.finished_getter.assert_called_once_with(**metric_identifiers, status="completed")
    metrics.finished.add.assert_called_once_with(1)
    metrics.duration_getter.assert_called_once_with(**metric_identifiers, status="completed")
    metrics.duration.record.assert_called_once_with(432.0)
    metrics.last_success_getter.assert_called_once_with(**metric_identifiers)
    metrics.last_success.set.assert_called_once_with(finished_at.timestamp())


@pytest.mark.asyncio
async def test_workflow_records_end_to_end_duration_on_post_gate_failure(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    failed_at = started_at + dt.timedelta(seconds=5)
    execute_activity = AsyncMock(side_effect=[True, RuntimeError("prepare failed")])
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "now", MagicMock(side_effect=[started_at, failed_at]))

    with pytest.raises(RuntimeError, match="prepare failed"):
        await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    metric_identifiers = {"team_id": 1, "schema_id": str(_workflow_inputs().schema_id)}
    metrics.started_getter.assert_called_once_with(**metric_identifiers)
    metrics.started.add.assert_called_once_with(1)
    metrics.finished_getter.assert_called_once_with(**metric_identifiers, status="failed")
    metrics.finished.add.assert_called_once_with(1)
    metrics.duration_getter.assert_called_once_with(**metric_identifiers, status="failed")
    metrics.duration.record.assert_called_once_with(5.0)
    metrics.last_success_getter.assert_not_called()


def _mock_workflow_metrics(monkeypatch):
    metrics = MagicMock()
    metrics.duration_getter = MagicMock(return_value=metrics.duration)
    metrics.finished_getter = MagicMock(return_value=metrics.finished)
    metrics.started_getter = MagicMock(return_value=metrics.started)
    metrics.last_success_getter = MagicMock(return_value=metrics.last_success)
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_duration_metric",
        metrics.duration_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_finished_metric",
        metrics.finished_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_started_metric",
        metrics.started_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_last_success_metric",
        metrics.last_success_getter,
    )
    return metrics


def _mock_activity_workload_metrics(monkeypatch):
    metrics = MagicMock()
    metrics.files_getter = MagicMock(return_value=metrics.files)
    metrics.rows_getter = MagicMock(return_value=metrics.rows)
    metrics.bytes_getter = MagicMock(return_value=metrics.bytes)
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_files_metric",
        metrics.files_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_rows_metric",
        metrics.rows_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_bytes_metric",
        metrics.bytes_getter,
    )
    return metrics


def _activity_inputs() -> DuckLakeRegisterDataImportsActivityInputs:
    return DuckLakeRegisterDataImportsActivityInputs(
        team_id=1,
        job_id="job",
        metadata=DuckLakeRegisterDataImportsMetadata(
            source_schema_id="schema",
            prepared_queryable_folder="customers__query",
            prepared_source_uri="s3://source/team/customers__query",
            landing_uri="s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job",
            ducklake_schema_name="posthog_data_imports_team_1",
            ducklake_table_name="postgres_customers",
        ),
    )


def _workflow_inputs() -> DuckLakeRegisterDataImportsInputs:
    return DuckLakeRegisterDataImportsInputs(
        team_id=1,
        job_id="job",
        schema_id=uuid.UUID("019ef5df-e4c7-0000-b543-8ef7f13b5f15"),
        prepared_queryable_folder="customers__query",
    )


def _workflow_id(prepared_queryable_folder: str) -> str:
    return build_register_data_imports_workflow_id(
        team_id=473662,
        schema_id="019ef5df-e4c7-0000-b543-8ef7f13b5f15",
        job_id="019fb012-26e7-0000-2959-704b254131bd",
        prepared_queryable_folder=prepared_queryable_folder,
    )


@parameterized.expand(
    [
        (
            "timestamped",
            "customer_balance_transaction__query_1785365519_02076d94",
            "customer_balance_transaction__query_1785365530_d3277966",
        ),
        (
            "untimestamped",
            "customer_balance_transaction__query",
            "customer_balance_transaction__query_legacy",
        ),
    ]
)
def test_workflow_id_differs_per_prepared_generation(_name, earlier_folder, later_folder):
    earlier = _workflow_id(earlier_folder)
    later = _workflow_id(later_folder)

    assert earlier != later


def test_workflow_id_is_stable_for_one_prepared_generation():
    folder = "customer_balance_transaction__query_1785365530_d3277966"

    first = _workflow_id(folder)
    second = _workflow_id(folder)

    assert first == second
