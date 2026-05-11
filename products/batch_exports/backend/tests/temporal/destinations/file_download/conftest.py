import os
import json
import secrets

import pytest

import aioboto3
import structlog
import pytest_asyncio
import botocore.exceptions

from products.batch_exports.backend.tests.temporal.utils.s3 import delete_all_from_s3

LOGGER = structlog.get_logger()
TOKEN = secrets.token_hex(6)
TEST_BUCKET_NAME = os.getenv("FILE_DOWNLOAD_TEST_BUCKET", f"test-file-downloads-{TOKEN}")
TEST_ROLE = os.getenv("FILE_DOWNLOAD_TEST_ROLE", f"test-file-downloads-role-{TOKEN}")
TEST_REGION = os.getenv("FILE_DOWNLOAD_TEST_BUCKET_REGION", "us-east-1")


@pytest.fixture(scope="module")
def region() -> str:
    return TEST_REGION


@pytest.fixture(scope="module")
def bucket_name() -> str:
    return TEST_BUCKET_NAME


@pytest.fixture(scope="module")
def role_name() -> str:
    return TEST_ROLE


@pytest.fixture
def compression(request) -> str | None:
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def file_format(request) -> str:
    try:
        return request.param
    except AttributeError:
        return "Parquet"


@pytest_asyncio.fixture(scope="module")
async def session():
    session = aioboto3.Session()
    return session


@pytest_asyncio.fixture(scope="module")
async def s3_client(session):
    """Manage an S3 client to interact with an S3 bucket.

    Yields the client after assuming the test bucket exists. Upon resuming, we delete
    the contents of the bucket under the key prefix we are testing.
    """
    async with session.client("s3") as s3_client:
        yield s3_client


@pytest_asyncio.fixture(scope="module")
async def s3_bucket(bucket_name, s3_client, region):
    try:
        resp = await s3_client.create_bucket(
            Bucket=bucket_name,
            ACL="private",
        )
    except botocore.exceptions.ClientError:
        raise pytest.skip("Could not setup S3 bucket")

    yield bucket_name

    try:
        await delete_all_from_s3(s3_client, bucket_name, key_prefix="batch-exports")
        await s3_client.delete_bucket(Bucket=bucket_name)
    except Exception:
        LOGGER.warning("Bucket clean-up failed", name=bucket_name, arn=resp["BucketArn"], exc_info=True)


@pytest_asyncio.fixture(scope="module")
async def aws_role_arn(session, bucket_name, role_name):
    async with session.client("iam") as iam, session.client("sts") as sts:
        identity = await sts.get_caller_identity()
        identity_role_name = identity["Arn"].split("/")[-2]
        resp = await iam.create_role(
            RoleName=role_name,
            MaxSessionDuration=3600,
            # Allow the current account to assume the role
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": f"arn:aws:iam::{identity['Account']}:role/aws-reserved/sso.amazonaws.com/{identity_role_name}",
                            },
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
            Description="Role assumed by the file download batch export during testing",
        )

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
                    "Action": [
                        "s3:PutObject",
                        "s3:GetObject",
                        "s3:DeleteObject",
                    ],
                    "Resource": f"arn:aws:s3:::{bucket_name}/*",
                },
            ],
        }
        await iam.put_role_policy(
            RoleName=role_name,
            PolicyName="batch-export-s3-access",
            PolicyDocument=json.dumps(s3_policy),
        )

        yield resp["Role"]["Arn"]

        try:
            resp = await iam.list_role_policies(RoleName=role_name)
            for policy_name in resp.get("PolicyNames", []):
                await iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
            await iam.delete_role(RoleName=role_name)

        except Exception:
            LOGGER.warning("Test role clean-up failed", name=TEST_ROLE, arn=resp["Role"]["Arn"], exc_info=True)
