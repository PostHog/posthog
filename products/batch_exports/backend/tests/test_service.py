import uuid
import datetime as dt

import pytest

from temporalio.converter import JSONPlainPayloadConverter

from products.batch_exports.backend.facade.enums import IncrementalMode
from products.batch_exports.backend.models.batch_export import (
    BatchExport,
    BatchExportBackfill,
    BatchExportDestination,
    BatchExportOnDemand,
    BatchExportRun,
    BatchExportSource,
)
from products.batch_exports.backend.service import (
    AnyBatchExportModel,
    AWSCredentials,
    AzureBlobBatchExportInputs,
    BatchExportEventsCustomModel,
    BatchExportEventsModel,
    BatchExportHogQLModel,
    BatchExportInsertInputs,
    BatchExportModel,
    BatchExportPersonsModel,
    BatchExportSessionsModel,
    BigQueryBatchExportInputs,
    DatabricksBatchExportInputs,
    FileDownloadBatchExportInputs,
    PostgresBatchExportInputs,
    RedshiftBatchExportInputs,
    RedshiftCopyInputs,
    S3BatchExportInputs,
    S3CompatibleBatchExportInputs,
    aget_or_create_batch_export_backfill,
    align_timestamp_to_interval,
    get_batch_export_model,
    migrate_batch_export_model,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import BatchExportInsertIntoInternalStageInputs


class TestBatchExportModelMigration:
    @pytest.mark.parametrize(
        "input_type", [FileDownloadBatchExportInputs, BatchExportInsertInputs, BatchExportInsertIntoInternalStageInputs]
    )
    @pytest.mark.parametrize(
        "batch_export,expected",
        [
            (BatchExport(model=None), BatchExportEventsModel()),
            (BatchExport(model=""), BatchExportEventsModel()),
            (BatchExport(model="events", filters=None), BatchExportEventsModel()),
            (
                BatchExport(model="events", filters=[{"key": "amount", "value": [1.5, True]}]),
                BatchExportEventsModel(filters=[{"key": "amount", "value": [1.5, True]}]),
            ),
            (
                BatchExport(model="events", schema={"fields": [], "values": {"value": 1.5}}),
                BatchExportEventsCustomModel(schema={"fields": [], "values": {"value": 1.5}}),
            ),
            (BatchExport(model="persons"), BatchExportPersonsModel()),
            (BatchExport(model="sessions"), BatchExportSessionsModel()),
            (
                BatchExport(
                    model="hogql",
                    last_modified_by_id=42,
                    incremental_mode="MERGE",
                    source=BatchExportSource(
                        hogql_query="SELECT id, updated_at FROM events",
                        hogql_modifiers={"convertToProjectTimezone": False},
                        primary_key=["id"],
                        version_key=["updated_at"],
                    ),
                ),
                BatchExportHogQLModel(
                    query="SELECT id, updated_at FROM events",
                    user_id=42,
                    modifiers={"convertToProjectTimezone": False},
                    incremental_mode=IncrementalMode.MERGE,
                    primary_key=("id",),
                    version_key=("updated_at",),
                ),
            ),
            (
                BatchExportOnDemand(
                    model="hogql",
                    last_modified_by_id=42,
                    source=BatchExportSource(hogql_query="SELECT event FROM events"),
                ),
                BatchExportHogQLModel(query="SELECT event FROM events", user_id=42, modifiers={}),
            ),
        ],
    )
    def test_model_from_saved_export(
        self,
        batch_export: BatchExport | BatchExportOnDemand,
        expected: AnyBatchExportModel,
        input_type: type[
            FileDownloadBatchExportInputs | BatchExportInsertInputs | BatchExportInsertIntoInternalStageInputs
        ],
    ) -> None:
        model = get_batch_export_model(batch_export)
        assert model == expected
        inputs = input_type(
            team_id=1,
            batch_export_id="test",
            data_interval_start=None,
            data_interval_end=None,
            batch_export_model=model,
        )
        converter = JSONPlainPayloadConverter()
        payload = converter.to_payload(inputs)
        assert payload is not None
        assert converter.from_payload(payload, input_type).batch_export_model == expected

    @pytest.mark.parametrize("model_specific", [False, True])
    @pytest.mark.parametrize(
        "input_type", [FileDownloadBatchExportInputs, BatchExportInsertInputs, BatchExportInsertIntoInternalStageInputs]
    )
    @pytest.mark.parametrize(
        "legacy,expected",
        [
            (None, BatchExportEventsModel()),
            (BatchExportModel(name="events", schema=None), BatchExportEventsModel()),
            (
                BatchExportModel(name="events", schema=None, filters=[{"key": "amount", "value": [1.5, True]}]),
                BatchExportEventsModel(filters=[{"key": "amount", "value": [1.5, True]}]),
            ),
            (
                BatchExportModel(name="events", schema={"fields": [], "values": {"value": 1.5}}),
                BatchExportEventsCustomModel(schema={"fields": [], "values": {"value": 1.5}}),
            ),
            (BatchExportModel(name="persons", schema=None), BatchExportPersonsModel()),
            (BatchExportModel(name="sessions", schema=None), BatchExportSessionsModel()),
            (
                BatchExportModel(name="hogql", schema=None, hogql_query="SELECT event FROM events", user_id=42),
                BatchExportHogQLModel(query="SELECT event FROM events", user_id=42, modifiers={}),
            ),
            (
                BatchExportModel(
                    name="hogql",
                    schema=None,
                    hogql_query="SELECT event FROM events",
                    user_id=42,
                    hogql_modifiers={"convertToProjectTimezone": False},
                ),
                BatchExportHogQLModel(
                    query="SELECT event FROM events",
                    user_id=42,
                    modifiers={"convertToProjectTimezone": False},
                ),
            ),
        ],
    )
    def test_migration_preserves_legacy_payload(
        self,
        legacy: BatchExportModel | None,
        expected: AnyBatchExportModel,
        input_type: type[
            FileDownloadBatchExportInputs | BatchExportInsertInputs | BatchExportInsertIntoInternalStageInputs
        ],
        model_specific: bool,
    ) -> None:
        converter = JSONPlainPayloadConverter()
        inputs = input_type(
            team_id=1,
            batch_export_id="test",
            data_interval_start=None,
            data_interval_end=None,
            batch_export_model=expected if model_specific else legacy,
        )
        payload = converter.to_payload(inputs)
        assert payload is not None
        decoded = converter.from_payload(payload, input_type)
        migrated = migrate_batch_export_model(decoded.batch_export_model)
        assert migrated == expected
        assert migrate_batch_export_model(migrated) is migrated

    @pytest.mark.parametrize(
        "legacy,message",
        [
            (BatchExportModel(name="unknown", schema=None), "Invalid model name"),
            (BatchExportModel(name="hogql", schema=None, hogql_query="SELECT 1"), "requires user_id"),
            (BatchExportModel(name="hogql", schema=None, user_id=42), "requires a query"),
        ],
    )
    def test_invalid_legacy_model_is_rejected(self, legacy: BatchExportModel, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            migrate_batch_export_model(legacy)

    @pytest.mark.parametrize("version_key", [(), ("updated_at",)])
    def test_hogql_merge_requires_primary_key(self, version_key: tuple[str, ...]) -> None:
        with pytest.raises(ValueError, match="MERGE requires a primary key"):
            BatchExportHogQLModel(
                query="SELECT 1",
                user_id=42,
                modifiers={},
                incremental_mode=IncrementalMode.MERGE,
                primary_key=(),
                version_key=version_key,
            )

    @pytest.mark.parametrize("version_key", [(), ("updated_at",)])
    def test_migration_preserves_hogql_merge_settings(self, version_key: tuple[str, ...]) -> None:
        model = BatchExportHogQLModel(
            query="SELECT id, updated_at FROM events",
            user_id=42,
            modifiers={},
            incremental_mode=IncrementalMode.MERGE,
            primary_key=("id",),
            version_key=version_key,
        )
        assert model.incremental_mode == IncrementalMode.MERGE
        assert model.primary_key == ("id",)
        assert model.version_key == version_key
        assert migrate_batch_export_model(model) is model
        converter = JSONPlainPayloadConverter()
        payload = converter.to_payload(model)
        assert payload is not None
        assert converter.from_payload(payload, BatchExportHogQLModel) == model


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
    "S3Compatible": S3CompatibleBatchExportInputs(
        batch_export_id="test",
        team_id=1,
        bucket_name="bucket",
        region="us-east-1",
        prefix="prefix/",
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
            ("S3Compatible", "use_virtual_style_addressing", True),
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
            ("S3Compatible", "max_file_size_mb", 100),
            ("AzureBlob", "max_file_size_mb", 50),
        ],
    )
    def test_string_ints_are_coerced(self, destination, field, expected):
        assert getattr(DESTINATION_INPUTS[destination], field) == expected

    @pytest.mark.parametrize("filter_value", [True, False])
    def test_actual_booleans_are_preserved(self, filter_value: bool) -> None:
        inputs = DatabricksBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            http_path="/sql/1.0/warehouses/abc",
            catalog="main",
            schema="default",
            table_name="events",
            use_variant_type=True,
            use_automatic_schema_evolution=False,
            batch_export_model=BatchExportEventsModel(
                filters=[{"type": "hogql", "key": "event = 'example_event'", "value": filter_value}],
            ),
        )
        converter = JSONPlainPayloadConverter()
        payload = converter.to_payload(inputs)
        assert payload is not None
        inputs = converter.from_payload(payload, DatabricksBatchExportInputs)

        assert inputs.use_variant_type is True
        assert inputs.use_automatic_schema_evolution is False
        assert isinstance(inputs.batch_export_model, BatchExportEventsModel)
        assert inputs.batch_export_model.filters[0]["value"] is filter_value

    def test_optional_int_none_is_preserved(self):
        inputs = S3BatchExportInputs(
            batch_export_id="test",
            team_id=1,
            bucket_name="bucket",
            region="us-east-1",
            prefix="prefix/",
            max_file_size_mb=None,
        )
        assert inputs.max_file_size_mb is None


@pytest.fixture
async def batch_export(ateam):
    destination = await BatchExportDestination.objects.acreate(
        type="AwsS3",
        config={
            "bucket_name": "test",
            "region": "us-east-1",
            "prefix": "test",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        },
    )
    batch_export = await BatchExport.objects.acreate(
        team=ateam,
        destination=destination,
        interval="hour",
        name="Test Export",
    )
    yield batch_export
    await batch_export.adelete()
    await destination.adelete()


async def test_creates_new_backfill(ateam, batch_export):
    backfill = await aget_or_create_batch_export_backfill(
        batch_export_id=batch_export.id,
        team_id=ateam.id,
        start_at="2024-01-01T00:00:00+00:00",
        end_at="2024-01-02T00:00:00+00:00",
    )

    assert backfill.batch_export_id == batch_export.id
    assert backfill.team_id == ateam.id
    assert backfill.status == BatchExportRun.Status.RUNNING
    assert await BatchExportBackfill.objects.filter(id=backfill.id).aexists()


async def test_creates_new_backfill_with_preset_id(ateam, batch_export):
    backfill_id = str(uuid.uuid4())
    backfill = await aget_or_create_batch_export_backfill(
        batch_export_id=batch_export.id,
        team_id=ateam.id,
        start_at="2024-01-01T00:00:00+00:00",
        end_at="2024-01-02T00:00:00+00:00",
        backfill_id=backfill_id,
    )

    assert str(backfill.id) == backfill_id


async def test_returns_existing_backfill_on_retry_with_same_id(ateam, batch_export):
    backfill_id = str(uuid.uuid4())
    kwargs = {
        "batch_export_id": batch_export.id,
        "team_id": ateam.id,
        "start_at": "2024-01-01T00:00:00+00:00",
        "end_at": "2024-01-02T00:00:00+00:00",
        "backfill_id": backfill_id,
    }

    first = await aget_or_create_batch_export_backfill(**kwargs)
    second = await aget_or_create_batch_export_backfill(**kwargs)

    assert str(first.id) == str(second.id)
    assert await BatchExportBackfill.objects.filter(id=backfill_id).acount() == 1


async def test_creates_backfill_without_id_does_not_deduplicate(ateam, batch_export):
    kwargs = {
        "batch_export_id": batch_export.id,
        "team_id": ateam.id,
        "start_at": "2024-01-01T00:00:00+00:00",
        "end_at": "2024-01-02T00:00:00+00:00",
    }

    first = await aget_or_create_batch_export_backfill(**kwargs)
    second = await aget_or_create_batch_export_backfill(**kwargs)

    assert first.id != second.id


@pytest.mark.parametrize(
    "timestamp,interval,interval_offset,timezone,expected",
    [
        # Hourly interval — 10:37 aligns to 10:00
        (
            dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC),
            "hour",
            None,
            "UTC",
            dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC),
        ),
        # 5-minute interval — 10:37 aligns to 10:35
        (
            dt.datetime(2021, 1, 15, 10, 37, 45, tzinfo=dt.UTC),
            "every 5 minutes",
            None,
            "UTC",
            dt.datetime(2021, 1, 15, 10, 35, 0, tzinfo=dt.UTC),
        ),
        # Daily with offset_hour=5 — 10:30 aligns to 5am same day
        (
            dt.datetime(2021, 1, 15, 10, 30, 0, tzinfo=dt.UTC),
            "day",
            5 * 3600,
            "UTC",
            dt.datetime(2021, 1, 15, 5, 0, 0, tzinfo=dt.UTC),
        ),
        # Daily with offset_hour=5 — 4:30am aligns to 5am previous day
        (
            dt.datetime(2021, 1, 15, 4, 30, 0, tzinfo=dt.UTC),
            "day",
            5 * 3600,
            "UTC",
            dt.datetime(2021, 1, 14, 5, 0, 0, tzinfo=dt.UTC),
        ),
        # Weekly starting Monday at 5am — Thursday 10am aligns to Monday 5am
        (
            dt.datetime(2021, 1, 14, 10, 0, 0, tzinfo=dt.UTC),
            "week",
            1 * 86400 + 5 * 3600,
            "UTC",
            dt.datetime(2021, 1, 11, 5, 0, 0, tzinfo=dt.UTC),
        ),
        # Daily at 1am US/Pacific — 10:00 UTC (2am PST) aligns to 9:00 UTC (1am PST)
        (
            dt.datetime(2021, 1, 15, 10, 0, 0, tzinfo=dt.UTC),
            "day",
            1 * 3600,
            "US/Pacific",
            dt.datetime(2021, 1, 15, 9, 0, 0, tzinfo=dt.UTC),
        ),
        # Daily at 1am US/Pacific — 8:30 UTC (0:30am PST) aligns to previous day's 1am PST
        (
            dt.datetime(2021, 1, 15, 8, 30, 0, tzinfo=dt.UTC),
            "day",
            1 * 3600,
            "US/Pacific",
            dt.datetime(2021, 1, 14, 9, 0, 0, tzinfo=dt.UTC),
        ),
    ],
)
def test_align_timestamp_to_interval(timestamp, interval, interval_offset, timezone, expected):
    batch_export = BatchExport(interval=interval, interval_offset=interval_offset, timezone=timezone)
    assert align_timestamp_to_interval(timestamp, batch_export) == expected


class TestRedshiftCopyInputsCredentials:
    # EncryptedJSONField stringifies scalar leaves on the decrypt round trip, so an
    # integration id saved as an int can read back as a numeric string.
    @pytest.mark.parametrize(
        "authorization,bucket_credentials,expected_authorization,expected_bucket_credentials",
        [
            (123, 456, 123, 456),
            ("123", "456", 123, 456),
            (
                "arn:aws:iam::123456789012:role/my-role",
                {"aws_access_key_id": "key", "aws_secret_access_key": "secret"},
                "arn:aws:iam::123456789012:role/my-role",
                AWSCredentials(aws_access_key_id="key", aws_secret_access_key="secret"),
            ),
        ],
    )
    def test_copy_credentials_are_parsed(
        self, authorization, bucket_credentials, expected_authorization, expected_bucket_credentials
    ):
        inputs = RedshiftBatchExportInputs(
            batch_export_id="test",
            team_id=1,
            database="db",
            mode="COPY",
            copy_inputs={  # type: ignore
                "s3_bucket": "bucket",
                "region_name": "us-east-1",
                "s3_key_prefix": "prefix/",
                "authorization": authorization,
                "bucket_credentials": bucket_credentials,
            },
        )

        assert isinstance(inputs.copy_inputs, RedshiftCopyInputs)
        assert inputs.copy_inputs.authorization == expected_authorization
        assert inputs.copy_inputs.bucket_credentials == expected_bucket_credentials
