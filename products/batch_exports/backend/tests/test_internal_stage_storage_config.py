import pytest

from django.test.utils import override_settings

from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    _get_s3_credentials,
    _get_s3_endpoint_url,
    get_s3_staging_folder,
)

OBJECT_STORAGE_ENDPOINT = "http://objectstorage:19000"
OBJECT_STORAGE_BUCKET = "posthog-test"
OBJECT_STORAGE_REGION = "us-east-2"
OBJECT_STORAGE_ACCESS_KEY_ID = "object-storage-key"
OBJECT_STORAGE_SECRET_ACCESS_KEY = "object-storage-secret"
EXPECTED_STAGE_FOLDER = "batch-exports/batch-export/2026-01-01-2026-01-02/attempt_1"


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
        assert _get_s3_credentials() == (OBJECT_STORAGE_ACCESS_KEY_ID, OBJECT_STORAGE_SECRET_ACCESS_KEY)


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
        assert _get_s3_credentials() == (None, None)


def test_s3_endpoint_url_self_hosted_uses_configured_endpoint_not_localhost() -> None:
    with override_settings(
        CLOUD_DEPLOYMENT=None,
        DEBUG=False,
        TEST=False,
        BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT=OBJECT_STORAGE_ENDPOINT,
    ):
        assert _get_s3_endpoint_url() == OBJECT_STORAGE_ENDPOINT
