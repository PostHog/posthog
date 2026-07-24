import os
import uuid
import secrets
import collections.abc

import pytest

import aioboto3
import pytest_asyncio
import botocore.exceptions

from products.batch_exports.backend.tests.temporal.utils.s3 import aws_role, delete_all_from_s3

TEST_ROOT_BUCKET = "test-destination-tests"
TEST_REGION = os.getenv("TEST_S3_BUCKET_REGION", "us-east-1")


@pytest.fixture(scope="module")
def region() -> str:
    return TEST_REGION


@pytest.fixture
def token() -> str:
    return secrets.token_hex(6)


@pytest.fixture
def external_aws_role_name(token: str) -> str:
    return f"test-destination-external-role-{token}"


@pytest.fixture
def destination_aws_role_name(token: str) -> str:
    return f"test-destination-role-{token}"


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
        raise pytest.skip("Missing AWS credentials")

    return session


@pytest_asyncio.fixture(scope="module")
async def account_id(session: aioboto3.Session) -> str:
    async with session.client("sts") as sts:
        try:
            identity = await sts.get_caller_identity()
        except (
            botocore.exceptions.NoCredentialsError,
            botocore.exceptions.PartialCredentialsError,
            botocore.exceptions.ClientError,
        ):
            raise pytest.skip("Could not obtain current identity")

    return identity["Account"]


@pytest_asyncio.fixture(scope="module")
async def identity_role(session: aioboto3.Session) -> str:
    async with session.client("sts") as sts:
        try:
            identity = await sts.get_caller_identity()
            identity_role_name = identity["Arn"].split("/")[-2]
        except (
            botocore.exceptions.NoCredentialsError,
            botocore.exceptions.PartialCredentialsError,
            botocore.exceptions.ClientError,
        ):
            raise pytest.skip("Could not obtain current identity")

    return identity_role_name


# Named distinctly from the test module's function-scoped `bucket_name` fixture (used by
# the MinIO tests) so this module-scoped fixture is not shadowed, which would cause a
# ScopeMismatch when the module-scoped `aws_bucket` requests it.
@pytest.fixture(scope="module")
def aws_bucket_name() -> str:
    """Name for a test S3 bucket."""
    return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest_asyncio.fixture(scope="module")
async def aws_bucket(
    session: aioboto3.Session, aws_bucket_name: str, region: str
) -> collections.abc.AsyncIterator[str]:
    """A real S3 bucket the destination role is granted access to."""
    async with session.client("s3") as s3_client:
        try:
            await s3_client.create_bucket(Bucket=aws_bucket_name, ACL="private")
        except (
            botocore.exceptions.NoCredentialsError,
            botocore.exceptions.PartialCredentialsError,
            botocore.exceptions.ClientError,
        ):
            raise pytest.skip("Could not setup S3 bucket")

        yield aws_bucket_name

        try:
            await delete_all_from_s3(s3_client, aws_bucket_name, key_prefix="")
            await s3_client.delete_bucket(Bucket=aws_bucket_name)
        except Exception:
            pass


@pytest_asyncio.fixture
async def external_aws_role_arn(
    session: aioboto3.Session,
    account_id: str,
    identity_role: str,
    external_aws_role_name: str,
    destination_aws_role_name: str,
) -> collections.abc.AsyncIterator[str]:
    """Role used to assume a destination AWS role.

    This simulates the role shown to PostHog users so that they can grant it
    permission to assume one of their roles.
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
    """External id used in the destination role's trust policy.

    Parametrize indirectly to test wrong (or missing) external ids.
    """
    try:
        return request.param
    except AttributeError:
        return f"posthog-{aorganization.id}"


@pytest_asyncio.fixture
async def destination_aws_role_arn(
    session: aioboto3.Session,
    external_aws_role_arn: str,
    destination_aws_role_name: str,
    aws_bucket: str,
    external_id: str | None,
) -> collections.abc.AsyncIterator[str]:
    """Role with S3 permissions in a destination.

    This simulates a role in a user's destination. It can be assumed by our
    external role and grants access to S3. When `external_id` is `None`, the
    trust policy omits the external id condition (used to test that path).
    """
    statement: dict[str, object] = {
        "Effect": "Allow",
        "Principal": {
            "AWS": external_aws_role_arn,
        },
        "Action": "sts:AssumeRole",
    }
    if external_id is not None:
        statement["Condition"] = {
            "StringEquals": {
                "sts:ExternalId": external_id,
            },
        }

    external_trust_policy = {
        "Version": "2012-10-17",
        "Statement": [statement],
    }

    s3_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BucketAccess",
                "Effect": "Allow",
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": f"arn:aws:s3:::{aws_bucket}",
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
