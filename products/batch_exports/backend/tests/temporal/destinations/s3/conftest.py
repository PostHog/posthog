import os
import json
import uuid
import typing
import asyncio
import secrets
import contextlib
import collections.abc

import pytest

from django.conf import settings

import aioboto3
import structlog
import pytest_asyncio
import botocore.exceptions

from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

LOGGER = structlog.get_logger()
TEST_ROOT_BUCKET = "test-batch-exports"
ARN = str
TEST_REGION = os.getenv("TEST_S3_BUCKET_REGION", "us-east-1")


@pytest.fixture(scope="module")
def region() -> str:
    return TEST_REGION


@pytest.fixture
def compression(request) -> str | None:
    """A parametrizable fixture to configure compression.

    By decorating a test function with @pytest.mark.parametrize("compression", ..., indirect=True)
    it's possible to set the compression that will be used to create an S3
    BatchExport. Possible values are "brotli", "gzip", or None.
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def encryption(request) -> str | None:
    """A parametrizable fixture to configure a batch export encryption.

    By decorating a test function with @pytest.mark.parametrize("encryption", ..., indirect=True)
    it's possible to set the exclude_events that will be used to create an S3
    BatchExport. Any list of event names can be used, or None.
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest.fixture
def s3_key_prefix(request):
    """An S3 key prefix to use when putting files in a bucket."""
    try:
        return request.param
    except AttributeError:
        return f"posthog-data-{str(uuid.uuid4())}"


@pytest.fixture
def file_format(request) -> str:
    """S3 file format."""
    try:
        return request.param
    except AttributeError:
        return f"JSONLines"


@pytest_asyncio.fixture
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

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="")

        await minio_client.delete_bucket(Bucket=bucket_name)


@pytest_asyncio.fixture
async def s3_compatible_batch_export(
    ateam,
    s3_key_prefix,
    bucket_name,
    compression,
    interval,
    exclude_events,
    temporal_client,
    file_format,
):
    destination_data = {
        "type": "S3Compatible",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": s3_key_prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "compression": compression,
            "exclude_events": exclude_events,
            "file_format": file_format,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest_asyncio.fixture(scope="module")
async def session() -> aioboto3.Session:
    session = aioboto3.Session()

    try:
        async with session.client("sts") as sts:
            await sts.get_caller_identity()
    except (
        botocore.exceptions.NoCredentialsError,
        botocore.exceptions.PartialCredentialsError,
        botocore.exceptions.ClientError,
        botocore.exceptions.NoRegionError,
    ):
        raise pytest.skip("Missing AWS credentials")  # noqa: B904

    return session


@pytest_asyncio.fixture(scope="module")
async def kms_key(session: aioboto3.Session) -> collections.abc.AsyncIterator[dict]:
    try:
        async with session.client("kms") as kms:
            resp = await kms.create_key(
                Description="PostHog batch exports test key",
                KeyUsage="ENCRYPT_DECRYPT",
                KeySpec="SYMMETRIC_DEFAULT",
            )
            key_id = resp["KeyMetadata"]["KeyId"]
            yield resp["KeyMetadata"]
            await kms.schedule_key_deletion(
                KeyId=key_id,
                PendingWindowInDays=7,  # Minimum
            )

    except (
        botocore.exceptions.NoCredentialsError,
        botocore.exceptions.PartialCredentialsError,
        botocore.exceptions.ClientError,
        botocore.exceptions.NoRegionError,
    ):
        raise pytest.skip("Could not create KMS key")  # noqa: B904


@pytest.fixture(scope="module")
def kms_key_id(kms_key: dict) -> str:
    return kms_key["KeyId"]


@pytest.fixture(scope="module")
def kms_key_arn(kms_key: dict) -> str:
    return kms_key["Arn"]


@pytest_asyncio.fixture(scope="module")
async def s3_client(session: aioboto3.Session) -> collections.abc.AsyncIterator["S3Client"]:
    """Manage an S3 client to interact with an S3 bucket.

    Yields the client after assuming the test bucket exists. Upon resuming, we delete
    the contents of the bucket under the key prefix we are testing.
    """
    async with session.client("s3") as s3_client:
        yield s3_client


@pytest_asyncio.fixture(scope="module")
async def s3_bucket(bucket_name: str, s3_client: "S3Client", region: str):
    try:
        _ = await s3_client.create_bucket(
            Bucket=bucket_name,
            ACL="private",
        )
    except (
        botocore.exceptions.NoCredentialsError,
        botocore.exceptions.PartialCredentialsError,
        botocore.exceptions.ClientError,
    ):
        raise pytest.skip("Could not setup S3 bucket")  # noqa: B904

    yield bucket_name

    try:
        await delete_all_from_s3(s3_client, bucket_name, key_prefix="batch-exports")
        await s3_client.delete_bucket(Bucket=bucket_name)
    except Exception:
        LOGGER.warning("Bucket clean-up failed", name=bucket_name, exc_info=True)


@pytest_asyncio.fixture(scope="module")
async def account_id(session) -> str:
    async with session.client("sts") as sts:
        try:
            identity = await sts.get_caller_identity()
        except (
            botocore.exceptions.NoCredentialsError,
            botocore.exceptions.PartialCredentialsError,
            botocore.exceptions.ClientError,
        ):
            raise pytest.skip("Could not obtain current identity")  # noqa: B904

    return identity["Account"]


@pytest_asyncio.fixture(scope="module")
async def identity_role(session) -> str:
    async with session.client("sts") as sts:
        try:
            identity = await sts.get_caller_identity()
            identity_role_name = identity["Arn"].split("/")[-2]
        except (
            botocore.exceptions.NoCredentialsError,
            botocore.exceptions.PartialCredentialsError,
            botocore.exceptions.ClientError,
        ):
            raise pytest.skip("Could not obtain current identity")  # noqa: B904

    return identity_role_name


@pytest.fixture
def token() -> str:
    return secrets.token_hex(6)


@pytest.fixture
def external_aws_role_name(token: str) -> str:
    return f"test-aws-external-role-{token}"


@pytest.fixture
def destination_aws_role_name(token: str) -> str:
    return f"test-aws-destination-role-{token}"


@pytest_asyncio.fixture
async def external_aws_role_arn(
    session: aioboto3.Session,
    account_id: str,
    identity_role: str,
    external_aws_role_name: str,
    destination_aws_role_name: str,
) -> collections.abc.AsyncIterator[str]:
    """Role used to assume a destination AWS role.

    This simulates the role shown to users of PostHog, so that they can grant
    this role permission to assume one of their roles.

    The current assumed role is granted permission to assume this role.
    """
    current_role_trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::{account_id}:role/aws-reserved/sso.amazonaws.com/{identity_role}",
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }

    # For testing purposes, all roles may be under the same account, so a trust
    # policy is sufficient and this is unnecessary. But to closely mimic production
    # setup, we also add this policy.
    external_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAssumeDestinationRole",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Resource": f"arn:aws:iam::{account_id}:role/{destination_aws_role_name}",
            }
        ],
    }

    async with aws_role(
        session,
        external_aws_role_name,
        description="External role used to assume a user's role",
        trust_policy=current_role_trust_policy,
        role_policy=external_role_policy,
        policy_name="AssumeDestinationRole",
    ) as arn:
        yield arn


@pytest.fixture
def external_id(request, aorganization) -> str | None:
    try:
        return request.param
    except Exception:
        return str(aorganization.id)


@pytest_asyncio.fixture
async def destination_aws_role_arn(
    session: aioboto3.Session,
    external_aws_role_arn: str,
    bucket_name: str,
    aorganization,
    account_id: str,
    identity_role: str,
    destination_aws_role_name: str,
    external_id: str | None,
    kms_key_arn: str,
) -> collections.abc.AsyncIterator[str]:
    """Role with S3 permissions in a destination.

    This simulates a role in a user's destination. It can be assumed by our
    external role and ultimately grants access to S3.
    """
    external_trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": external_aws_role_arn,
                },
                "Action": "sts:AssumeRole",
            }
        ],
    }
    if external_id is not None:
        external_trust_policy["Statement"][0]["Condition"] = {  # type: ignore
            "StringEquals": {
                "sts:ExternalId": external_id,
            },
        }

    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BucketAccess",
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": f"arn:aws:s3:::{bucket_name}",
            },
            {
                "Sid": "ObjectAccess",
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
            },
            {
                "Sid": "KMSKeyAccess",
                "Effect": "Allow",
                "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
                "Resource": kms_key_arn,
            },
        ],
    }

    async with aws_role(
        session,
        destination_aws_role_name,
        trust_policy=external_trust_policy,
        description="A user's role with access to S3",
        role_policy=s3_policy,
        policy_name="S3BucketAccess",
    ) as arn:
        yield arn


@contextlib.asynccontextmanager
async def aws_role(
    session: aioboto3.Session,
    role_name: str,
    /,
    *,
    description: str,
    trust_policy: dict,
    role_policy: dict | None = None,
    policy_name: str | None = None,
    max_attempts: int = 5,
    delay: int | float = 3.0,
) -> collections.abc.AsyncIterator[ARN]:
    async with session.client("iam") as iam:
        attempt = 0

        for attempt in range(max_attempts):
            try:
                resp = await iam.create_role(
                    RoleName=role_name,
                    MaxSessionDuration=3600,
                    AssumeRolePolicyDocument=json.dumps(trust_policy),
                    Description=description,
                )

            except botocore.exceptions.ClientError as exc:
                if (
                    exc.response["Error"]["Code"] != "MalformedPolicyDocument"
                    or "Invalid principal" not in exc.response["Error"]["Message"]
                ) and exc.response["Error"]["Code"] != "EntityAlreadyExists":
                    raise pytest.skip(f"Failed with an unknown error when creating role: {type(exc)} {exc}")  # noqa: B904

                if attempt >= max_attempts:
                    raise pytest.skip("Failed multiple times to create role")  # noqa: B904

                await asyncio.sleep(delay)

            except (
                botocore.exceptions.NoCredentialsError,
                botocore.exceptions.PartialCredentialsError,
            ):
                raise pytest.skip("Credentials error when attempting to create role")  # noqa: B904

            else:
                break

        if role_policy is not None and policy_name is not None:
            await iam.put_role_policy(
                RoleName=role_name,
                PolicyName=policy_name,
                PolicyDocument=json.dumps(role_policy),
            )

        yield resp["Role"]["Arn"]

        try:
            resp = await iam.list_role_policies(RoleName=role_name)
            for policy_name in resp.get("PolicyNames", []):
                await iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
            await iam.delete_role(RoleName=role_name)

        except Exception:
            LOGGER.warning("Test role clean-up failed", name=role_name, arn=resp["Role"]["Arn"], exc_info=True)
