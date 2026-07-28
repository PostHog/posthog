import contextlib

import pytest
from unittest.mock import MagicMock

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
    copy_and_register_ducklake_data_imports_activity,
    ducklake_register_data_imports_gate_activity,
    prepare_ducklake_data_imports_registration_activity,
    verify_ducklake_data_imports_registration_activity,
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
    assert metadata.landing_uri == f"s3://ducklake-dev/data_imports/{ateam.id}/{schema.id}/job-123"
    assert metadata.ducklake_schema_name == f"posthog_data_imports_team_{ateam.id}"
    assert metadata.ducklake_table_name == "postgres_customers"


def test_copy_activity_uses_s3_copy_and_local_duckgres_postgres_connection(monkeypatch):
    class FakeS3:
        def __init__(self) -> None:
            self.copies: list[tuple[str, str]] = []

        def find(self, prefix: str) -> list[str]:
            return [
                f"{prefix}/_ph_partition_key=2026-07/a.parquet",
                f"{prefix}/_ph_partition_key=2026-08/b.parquet",
            ]

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
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(registration_module.psycopg, "connect", connect)
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))

    inputs = _activity_inputs()
    applied = copy_and_register_ducklake_data_imports_activity(inputs)

    assert applied is True
    connect.assert_called_once_with("postgresql://duckgres", autocommit=True)
    assert s3.copies == [
        (
            "source/team/customers__query/_ph_partition_key=2026-07/a.parquet",
            "ducklake/data_imports/1/schema/job/_ph_partition_key=2026-07/a.parquet",
        ),
        (
            "source/team/customers__query/_ph_partition_key=2026-08/b.parquet",
            "ducklake/data_imports/1/schema/job/_ph_partition_key=2026-08/b.parquet",
        ),
    ]
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    registration_indexes = [index for index, query in enumerate(executed) if "ducklake_add_data_files" in query]
    drop_live_index = next(
        index for index, query in enumerate(executed) if "DROP TABLE IF EXISTS" in query and "customers" in query
    )
    rename_index = next(index for index, query in enumerate(executed) if "RENAME TO" in query)
    assert len(registration_indexes) == 2
    assert max(registration_indexes) < drop_live_index < rename_index
    assert any("SET PARTITIONED BY" in query for query in executed)


def test_copy_activity_does_not_touch_catalog_for_stale_generation(monkeypatch):
    monkeypatch.setattr(
        registration_module,
        "_copy_prepared_parquet_files",
        lambda source_uri, landing_uri: [f"{landing_uri}/file.parquet"],
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

    assert copy_and_register_ducklake_data_imports_activity(_activity_inputs()) is False


def test_verification_rejects_a_row_count_mismatch(monkeypatch):
    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=(10,))),
        MagicMock(fetchone=MagicMock(return_value=(9,))),
    ]
    monkeypatch.setattr(
        registration_module, "_connect_to_duckgres_for_team", lambda team_id: contextlib.nullcontext(conn)
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())

    with pytest.raises(ApplicationError, match="row count mismatch"):
        verify_ducklake_data_imports_registration_activity(_activity_inputs())


def _activity_inputs() -> DuckLakeRegisterDataImportsActivityInputs:
    return DuckLakeRegisterDataImportsActivityInputs(
        team_id=1,
        job_id="job",
        metadata=DuckLakeRegisterDataImportsMetadata(
            source_schema_id="schema",
            prepared_queryable_folder="customers__query",
            prepared_source_uri="s3://source/team/customers__query",
            landing_uri="s3://ducklake/data_imports/1/schema/job",
            ducklake_schema_name="posthog_data_imports_team_1",
            ducklake_table_name="postgres_customers",
        ),
    )
