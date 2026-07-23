import uuid

import pytest

from django.conf import settings
from django.test import override_settings

from products.batch_exports.backend.api.destination_tests import get_destination_test
from products.batch_exports.backend.api.destination_tests.s3 import (
    AwsS3DestinationTest,
    S3AssumeRoleTestStep,
    S3CompatibleDestinationTest,
    S3EnsureBucketTestStep,
    Status,
)
from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3

TEST_ROOT_BUCKET = "test-destination-tests"


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest.fixture
async def minio_client(bucket_name):
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="/")

        await minio_client.delete_bucket(Bucket=bucket_name)


async def test_s3_check_bucket_exists_test_step(bucket_name, minio_client):
    test_step = S3EnsureBucketTestStep(
        bucket_name=bucket_name,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_s3_check_bucket_exists_test_step_without_bucket(minio_client):
    test_step = S3EnsureBucketTestStep(
        bucket_name="some-other-bucket",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message == "Bucket 'some-other-bucket' does not exist or we don't have permissions to use it"


@pytest.mark.parametrize("step", [S3EnsureBucketTestStep()])
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        # Bucket plus long-lived credentials.
        ({"bucket_name": "b", "aws_access_key_id": "a", "aws_secret_access_key": "s"}, True),
        # Bucket plus role assumption.
        ({"bucket_name": "b", "aws_role_arn": "arn:aws:iam::123:role/r", "organization_id": "1"}, True),
        # Missing bucket.
        ({"aws_access_key_id": "a", "aws_secret_access_key": "s"}, False),
        # Bucket but no credentials at all.
        ({"bucket_name": "b"}, False),
        # Role without organization id can't build the external id, so it's not usable on its own.
        ({"bucket_name": "b", "aws_role_arn": "arn:aws:iam::123:role/r"}, False),
    ],
)
def test_ensure_bucket_step_is_configured(kwargs, expected):
    assert S3EnsureBucketTestStep(**kwargs)._is_configured() is expected


async def test_assume_role_step_skips_without_role():
    """The assume role step is skipped (not failed) when no role is configured.

    This lets key-based AwsS3 exports run the rest of their steps.
    """
    test_step = S3AssumeRoleTestStep(aws_role_arn=None)
    result = await test_step.run()

    assert result.status == Status.SKIPPED
    assert result.message == "No configured AWS role ARN, skipping test"


@pytest.mark.parametrize(
    "destination,expected_test,expected_steps",
    [
        ("S3", S3CompatibleDestinationTest, [S3EnsureBucketTestStep]),
        ("S3Compatible", S3CompatibleDestinationTest, [S3EnsureBucketTestStep]),
        ("AwsS3", AwsS3DestinationTest, [S3AssumeRoleTestStep, S3EnsureBucketTestStep]),
    ],
)
def test_get_destination_test_resolves_s3_family(destination, expected_test, expected_steps):
    destination_test = get_destination_test(destination=destination)

    assert isinstance(destination_test, expected_test)
    assert [type(step) for step in destination_test.steps] == expected_steps


def test_aws_s3_destination_test_serializes_without_integration():
    """AwsS3 configured with inline credentials (no integration) must not raise.

    Its steps reference `organization_id` and each step needs an initialized
    `result`, so building the steps and serializing them exercises both.
    """
    destination_test = AwsS3DestinationTest()
    destination_test.configure(bucket_name="b", region="us-east-1", aws_access_key_id="a", aws_secret_access_key="s")

    assert destination_test.as_dict() == {
        "steps": [
            {"name": step.name, "description": step.description, "result": None} for step in destination_test.steps
        ]
    }


async def test_assume_role_step_passes_with_assumable_role(
    external_aws_role_arn: str,
    destination_aws_role_arn: str,
    aorganization,
):
    """The assume role step passes when the role is assumable with the right external id."""
    test_step = S3AssumeRoleTestStep(aws_role_arn=destination_aws_role_arn, organization_id=aorganization.id)

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


@pytest.mark.parametrize("external_id", ["not-an-org-id"], indirect=True)
async def test_assume_role_step_fails_with_wrong_external_id(
    external_aws_role_arn: str,
    destination_aws_role_arn: str,
    external_id: str | None,
    aorganization,
):
    """A mismatched external id surfaces an AccessDenied failure."""
    test_step = S3AssumeRoleTestStep(aws_role_arn=destination_aws_role_arn, organization_id=aorganization.id)

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert "AccessDenied" in result.message


@pytest.mark.parametrize("external_id", [None], indirect=True)
async def test_assume_role_step_fails_without_external_id_condition(
    external_aws_role_arn: str,
    destination_aws_role_arn: str,
    external_id: str | None,
    aorganization,
):
    """A role whose trust policy omits the external id condition is rejected."""
    test_step = S3AssumeRoleTestStep(aws_role_arn=destination_aws_role_arn, organization_id=aorganization.id)

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert "without a required external id condition" in result.message


async def test_ensure_bucket_step_passes_with_role_assumption(
    external_aws_role_arn: str,
    destination_aws_role_arn: str,
    aws_bucket: str,
    region: str,
    aorganization,
):
    """The bucket check resolves temporary credentials via role assumption and passes."""
    test_step = S3EnsureBucketTestStep(
        bucket_name=aws_bucket,
        region=region,
        aws_role_arn=destination_aws_role_arn,
        organization_id=aorganization.id,
    )

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None
