import uuid

import pytest

from django.conf import settings
from django.test import override_settings

from temporalio.testing._activity import ActivityEnvironment

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    SUPPORTED_COMPRESSIONS,
    S3InsertInputs,
    insert_into_s3_activity_from_stage,
    s3_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    assert_clickhouse_records_in_s3,
    assert_files_in_s3,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


TEST_S3_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "uuid", "alias": "uuid"},
                {"expression": "event", "alias": "my_event_name"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(
        name="events",
        schema=None,
        filters=[
            {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
            {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
        ],
    ),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
    {
        "fields": [
            {"expression": "uuid", "alias": "uuid"},
            {"expression": "event", "alias": "my_event_name"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


class TestInsertIntoS3ActivityFromStage:
    async def _run_activity(self, activity_environment: ActivityEnvironment, insert_inputs: S3InsertInputs):
        with override_settings(
            BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2,
        ):
            assert insert_inputs.batch_export_id is not None
            await activity_environment.run(
                insert_into_internal_stage_activity,
                BatchExportInsertIntoInternalStageInputs(
                    team_id=insert_inputs.team_id,
                    batch_export_id=insert_inputs.batch_export_id,
                    data_interval_start=insert_inputs.data_interval_start,
                    data_interval_end=insert_inputs.data_interval_end,
                    exclude_events=insert_inputs.exclude_events,
                    include_events=None,
                    run_id=None,
                    backfill_details=None,
                    batch_export_model=insert_inputs.batch_export_model,
                    batch_export_schema=insert_inputs.batch_export_schema,
                    destination_default_fields=s3_default_fields(),
                ),
            )

            result = await activity_environment.run(insert_into_s3_activity_from_stage, insert_inputs)

        return result

    @pytest.mark.parametrize("compression", COMPRESSION_EXTENSIONS.keys(), indirect=True)
    @pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
    @pytest.mark.parametrize("model", TEST_S3_MODELS)
    @pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys())
    async def test_insert_into_s3_activity_puts_data_into_s3(
        self,
        clickhouse_client,
        bucket_name,
        minio_client,
        activity_environment: ActivityEnvironment,
        compression,
        exclude_events,
        file_format,
        data_interval_start,
        data_interval_end,
        model: BatchExportModel | BatchExportSchema | None,
        generate_test_data,
        ateam,
    ):
        """Test that the insert_into_s3_activity_from_stage function ends up with data into S3.

        We use the generate_test_events_in_clickhouse function to generate several sets
        of events. Some of these sets are expected to be exported, and others not. Expected
        events are those that:
        * Are created for the team_id of the batch export.
        * Are created in the date range of the batch export.
        * Are not duplicates of other events that are in the same batch.
        * Do not have an event name contained in the batch export's exclude_events.

        Once we have these events, we pass them to the assert_clickhouse_records_in_s3 function to check
        that they appear in the expected S3 bucket and key.
        """
        if (
            isinstance(model, BatchExportModel)
            and (model.name == "persons" or model.name == "sessions")
            and exclude_events is not None
        ):
            pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

        if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
            pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

        prefix = str(uuid.uuid4())

        batch_export_schema: BatchExportSchema | None = None
        batch_export_model: BatchExportModel | None = None
        if isinstance(model, BatchExportModel):
            batch_export_model = model
        elif model is not None:
            batch_export_schema = model

        batch_export_id = str(uuid.uuid4())

        insert_inputs = S3InsertInputs(
            bucket_name=bucket_name,
            region="us-east-1",
            prefix=prefix,
            team_id=ateam.pk,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            aws_access_key_id="object_storage_root_user",
            aws_secret_access_key="object_storage_root_password",
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            compression=compression,
            exclude_events=exclude_events,
            file_format=file_format,
            batch_export_schema=batch_export_schema,
            batch_export_model=batch_export_model,
            batch_export_id=batch_export_id,
            destination_default_fields=s3_default_fields(),
        )

        result = await self._run_activity(activity_environment, insert_inputs)
        records_exported = result.records_completed
        bytes_exported = result.bytes_exported
        assert result.error is None

        events_to_export_created, persons_to_export_created = generate_test_data
        assert (
            records_exported == len(events_to_export_created)
            or records_exported == len(persons_to_export_created)
            or records_exported == len([event for event in events_to_export_created if event["properties"] is not None])
            or (isinstance(model, BatchExportModel) and model.name == "sessions" and 1 <= records_exported <= 2)
        )

        assert isinstance(bytes_exported, int)
        assert bytes_exported > 0

        sort_key = "uuid"
        if isinstance(model, BatchExportModel) and model.name == "persons":
            sort_key = "person_id"
        elif isinstance(model, BatchExportModel) and model.name == "sessions":
            sort_key = "session_id"

        await assert_clickhouse_records_in_s3(
            s3_compatible_client=minio_client,
            clickhouse_client=clickhouse_client,
            bucket_name=bucket_name,
            key_prefix=prefix,
            team_id=ateam.pk,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            batch_export_model=model,
            exclude_events=exclude_events,
            include_events=None,
            compression=compression,
            file_format=file_format,
            backfill_details=None,
            sort_key=sort_key,
        )

    @pytest.mark.parametrize("compression", [*COMPRESSION_EXTENSIONS.keys(), None], indirect=True)
    @pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
    @pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys())
    @pytest.mark.parametrize("max_file_size_mb", [None, 6])
    async def test_insert_into_s3_activity_puts_splitted_files_into_s3(
        self,
        clickhouse_client,
        bucket_name,
        minio_client,
        activity_environment,
        compression,
        max_file_size_mb,
        exclude_events,
        file_format,
        data_interval_start,
        data_interval_end,
        model: BatchExportModel,
        ateam,
    ):
        """Test that the insert_into_s3_activity_from_stage function splits up large files into
        multiple parts based on the max file size configuration.

        If max file size is set to 0 then the file should not be split up.

        This test needs to generate a lot of data to ensure that the file is large enough to be split up.
        """

        if file_format == "JSONLines" and compression is not None:
            pytest.skip("Compressing large JSONLines files takes too long to run; skipping for now")

        if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
            pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

        prefix = str(uuid.uuid4())

        events_1, _, _ = await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=100000,
            count_outside_range=0,
            count_other_team=0,
            duplicate=False,
            properties={"$prop1": 123},
        )

        events_2, _, _ = await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=100000,
            count_outside_range=0,
            count_other_team=0,
            duplicate=False,
            properties={"$prop1": 123},
        )

        events_to_export_created = events_1 + events_2

        insert_inputs = S3InsertInputs(
            bucket_name=bucket_name,
            region="us-east-1",
            prefix=prefix,
            team_id=ateam.pk,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            aws_access_key_id="object_storage_root_user",
            aws_secret_access_key="object_storage_root_password",
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            compression=compression,
            exclude_events=exclude_events,
            file_format=file_format,
            max_file_size_mb=max_file_size_mb,
            batch_export_schema=None,
            batch_export_model=model,
            batch_export_id=str(uuid.uuid4()),
            destination_default_fields=s3_default_fields(),
        )

        result = await self._run_activity(activity_environment, insert_inputs)
        records_exported = result.records_completed
        bytes_exported = result.bytes_exported
        assert result.error is None

        assert records_exported == len(events_to_export_created)
        assert isinstance(bytes_exported, int)
        assert bytes_exported > 0

        s3_data, s3_keys = await assert_files_in_s3(
            s3_compatible_client=minio_client,
            bucket_name=bucket_name,
            key_prefix=prefix,
            file_format=file_format,
            compression=compression,
            json_columns=("properties", "person_properties", "set", "set_once"),
        )

        assert len(s3_data) == len(events_to_export_created)
        num_files = len(s3_keys)

        def expected_s3_key(
            file_number: int,
            data_interval_start,
            data_interval_end,
            file_format: str,
            compression: str,
            max_file_size_mb: int | None,
        ):
            file_extension = FILE_FORMAT_EXTENSIONS[file_format]
            base_key_name = f"{prefix}/{data_interval_start.isoformat()}-{data_interval_end.isoformat()}"
            if max_file_size_mb is None:
                key_name = base_key_name
            else:
                key_name = f"{base_key_name}-{file_number}"
            key_name = f"{key_name}.{file_extension}"
            if compression:
                compression_extension = COMPRESSION_EXTENSIONS[compression]
                key_name = f"{key_name}.{compression_extension}"
            return key_name

        if max_file_size_mb is None:
            assert num_files == 1
        else:
            assert num_files > 1

        expected_keys = [
            expected_s3_key(
                file_number=i,
                data_interval_start=data_interval_start,
                data_interval_end=data_interval_end,
                file_format=file_format,
                compression=compression,
                max_file_size_mb=max_file_size_mb,
            )
            for i in range(num_files)
        ]
        assert set(expected_keys) == set(s3_keys)

        manifest_key = f"{prefix}/{data_interval_start.isoformat()}-{data_interval_end.isoformat()}_manifest.json"
        if max_file_size_mb is None:
            with pytest.raises(minio_client.exceptions.NoSuchKey):
                from products.batch_exports.backend.tests.temporal.destinations.s3.utils import read_json_file_from_s3

                await read_json_file_from_s3(minio_client, bucket_name, manifest_key)
        else:
            from products.batch_exports.backend.tests.temporal.destinations.s3.utils import read_json_file_from_s3

            manifest_data: dict | list = await read_json_file_from_s3(minio_client, bucket_name, manifest_key)
            assert isinstance(manifest_data, dict)
            assert manifest_data["files"] == expected_keys

    @pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
    @pytest.mark.parametrize("file_format", ["invalid"])
    async def test_insert_into_s3_activity_fails_on_invalid_file_format(
        self,
        clickhouse_client,
        bucket_name,
        minio_client,
        activity_environment,
        compression,
        exclude_events,
        file_format,
        data_interval_start,
        data_interval_end,
        model: BatchExportModel,
        ateam,
    ):
        """Test the insert_into_s3_activity_from_stage_activity function returns an error when an invalid file format is requested."""

        insert_inputs = S3InsertInputs(
            bucket_name=bucket_name,
            region="us-east-1",
            prefix="any",
            team_id=ateam.pk,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
            aws_access_key_id="object_storage_root_user",
            aws_secret_access_key="object_storage_root_password",
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            compression=compression,
            exclude_events=exclude_events,
            file_format=file_format,
            batch_export_schema=None,
            batch_export_model=model,
            batch_export_id=str(uuid.uuid4()),
            destination_default_fields=s3_default_fields(),
        )

        result = await self._run_activity(activity_environment, insert_inputs)
        assert result.error is not None
        assert result.error.type == "UnsupportedFileFormatError"
        assert result.error.message == "'invalid' is not a supported format for S3 batch exports."
        assert result.error_repr is not None
        assert (
            result.error_repr == "UnsupportedFileFormatError: 'invalid' is not a supported format for S3 batch exports."
        )
