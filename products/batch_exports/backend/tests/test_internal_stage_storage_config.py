import datetime as dt

import pytest
from unittest.mock import AsyncMock, patch

from django.test.utils import override_settings

from posthog.credentials import AWSKeyPair
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.errors import MissingRequiredInputsError
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    _get_s3_credentials,
    _get_s3_endpoint_url,
    _write_batch_export_record_batches_to_internal_stage,
    get_base_s3_staging_folder,
    get_s3_staging_folder,
)

OBJECT_STORAGE_ENDPOINT = "http://objectstorage:19000"
OBJECT_STORAGE_BUCKET = "posthog-test"
OBJECT_STORAGE_REGION = "us-east-2"
OBJECT_STORAGE_ACCESS_KEY_ID = "object-storage-key"
OBJECT_STORAGE_SECRET_ACCESS_KEY = "object-storage-secret"
EXPECTED_STAGE_FOLDER = "batch-exports/batch-export/2026-01-01-2026-01-02/attempt_1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "team_ids,compression,expected_settings",
    [
        ([], "zstd", {}),
        (["2"], "zstd", {}),
        (["2", "1"], "zstd", {"output_format_arrow_compression_method": "zstd"}),
        (["1"], "lz4_frame", {"output_format_arrow_compression_method": "lz4_frame"}),
        (["1"], "none", {"output_format_arrow_compression_method": "none"}),
    ],
)
async def test_staging_arrow_compression_is_scoped_to_allowed_teams(
    team_ids: list[str], compression: str, expected_settings: dict[str, str]
) -> None:
    interval_end = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    interval_start = interval_end - dt.timedelta(hours=1)
    client = AsyncMock(spec=ClickHouseClient)
    client.is_alive.return_value = True
    client.execute_query_with_summary.return_value = {"written_rows": "1"}

    with (
        override_settings(
            BATCH_EXPORT_ARROW_COMPRESSION_METHOD=compression,
            BATCH_EXPORT_ARROW_COMPRESSION_TEAM_IDS=team_ids,
        ),
        patch("products.batch_exports.backend.temporal.pipeline.internal_stage.get_client") as get_client,
        patch("products.batch_exports.backend.temporal.pipeline.internal_stage.get_s3_client") as get_s3_client,
    ):
        get_client.return_value.__aenter__.return_value = client
        get_s3_client.return_value.__aenter__.return_value.list_objects_v2.return_value = {}
        written_rows = await _write_batch_export_record_batches_to_internal_stage(
            query_or_model="SELECT 1",
            full_range=(interval_start, interval_end),
            query_parameters={},
            team_id=1,
            batch_export_id="00000000-0000-4000-8000-000000000001",
            data_interval_start=interval_start.isoformat(),
            data_interval_end=interval_end.isoformat(),
            s3_staging_folder_url="s3://bucket/folder",
        )

    assert written_rows == 1
    assert client.execute_query_with_summary.call_args.kwargs["settings"] == expected_settings


def _get_test_s3_staging_folder_url() -> str:
    return get_s3_staging_folder(
        batch_export_id="batch-export",
        data_interval_start="2026-01-01",
        data_interval_end="2026-01-02",
        attempt_number=1,
    ).url


@pytest.mark.parametrize(
    ("cloud_deployment", "is_debug", "is_test"),
    [
        (None, False, False),
        (None, True, False),
        (None, False, True),
    ],
)
def test_internal_stage_uses_object_storage_endpoint_for_self_hosted_local_and_test(
    cloud_deployment: str | None, is_debug: bool, is_test: bool
) -> None:
    with override_settings(
        CLOUD_DEPLOYMENT=cloud_deployment,
        DEBUG=is_debug,
        TEST=is_test,
        BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT=OBJECT_STORAGE_ENDPOINT,
        BATCH_EXPORT_INTERNAL_STAGING_BUCKET=OBJECT_STORAGE_BUCKET,
        OBJECT_STORAGE_ACCESS_KEY_ID=OBJECT_STORAGE_ACCESS_KEY_ID,
        OBJECT_STORAGE_SECRET_ACCESS_KEY=OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ):
        assert (
            _get_test_s3_staging_folder_url()
            == f"{OBJECT_STORAGE_ENDPOINT}/{OBJECT_STORAGE_BUCKET}/{EXPECTED_STAGE_FOLDER}"
        )
        assert _get_s3_credentials() == AWSKeyPair.unsafe_from_strings(
            OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY
        )


@pytest.mark.parametrize(
    "access_key_id,secret_access_key",
    [
        (OBJECT_STORAGE_ACCESS_KEY_ID, None),
        (None, OBJECT_STORAGE_SECRET_ACCESS_KEY),
        (None, None),
    ],
)
def test_partially_configured_object_storage_is_keyless(
    access_key_id: str | None, secret_access_key: str | None
) -> None:
    # Half a pair would reach boto3 as partial credentials and raise, so it counts as keyless.
    with override_settings(
        CLOUD_DEPLOYMENT=None,
        DEBUG=False,
        TEST=False,
        BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT=OBJECT_STORAGE_ENDPOINT,
        BATCH_EXPORT_INTERNAL_STAGING_BUCKET=OBJECT_STORAGE_BUCKET,
        OBJECT_STORAGE_ACCESS_KEY_ID=access_key_id,
        OBJECT_STORAGE_SECRET_ACCESS_KEY=secret_access_key,
    ):
        assert _get_s3_credentials() is None


@pytest.mark.parametrize("cloud_deployment", ["DEV", "US", "EU", "E2E"])
def test_internal_stage_uses_aws_s3_for_cloud(cloud_deployment: str) -> None:
    with override_settings(
        CLOUD_DEPLOYMENT=cloud_deployment,
        DEBUG=False,
        TEST=False,
        BATCH_EXPORT_OBJECT_STORAGE_REGION=OBJECT_STORAGE_REGION,
        BATCH_EXPORT_INTERNAL_STAGING_BUCKET=OBJECT_STORAGE_BUCKET,
    ):
        assert (
            _get_test_s3_staging_folder_url()
            == f"https://{OBJECT_STORAGE_BUCKET}.s3.{OBJECT_STORAGE_REGION}.amazonaws.com/{EXPECTED_STAGE_FOLDER}"
        )
        assert _get_s3_credentials() is None


def test_s3_endpoint_url_self_hosted_uses_configured_endpoint_not_localhost() -> None:
    with override_settings(
        CLOUD_DEPLOYMENT=None,
        DEBUG=False,
        TEST=False,
        BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT=OBJECT_STORAGE_ENDPOINT,
    ):
        assert _get_s3_endpoint_url() == OBJECT_STORAGE_ENDPOINT


@pytest.mark.parametrize(
    "start,end,run_id,expected_base",
    [
        ("2026-01-01", "2026-01-02", None, "batch-exports/export/2026-01-01-2026-01-02"),
        (None, "2026-01-02", None, "batch-exports/export/None-2026-01-02"),
        (None, "2026-01-02", "run-a", "batch-exports/export/runs/run-a"),
        ("2026-01-01", None, "run-a", "batch-exports/export/runs/run-a"),
        (None, None, "run-b", "batch-exports/export/runs/run-b"),
        (None, None, None, None),
    ],
)
def test_staging_folder_namespace(
    start: str | None, end: str | None, run_id: str | None, expected_base: str | None
) -> None:
    if expected_base is None:
        with pytest.raises(MissingRequiredInputsError, match="requires data_interval_end or run_id"):
            get_s3_staging_folder("export", start, end, 1, run_id=run_id)
        return
    assert get_base_s3_staging_folder("export", start, end, run_id) == expected_base
    for attempt in (1, 2):
        assert (
            get_s3_staging_folder("export", start, end, attempt, run_id).folder == f"{expected_base}/attempt_{attempt}"
        )
