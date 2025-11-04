import os
import warnings

import pytest

from django.conf import settings

import psycopg
import aioboto3

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import AWSCredentials
from products.batch_exports.backend.tests.temporal.destinations.redshift.utils import MISSING_REQUIRED_ENV_VARS


@pytest.fixture
def redshift_config():
    """Fixture to provide a default configuration for Redshift batch exports.

    Reads required env vars to construct configuration, but if not present
    we default to local development PostgreSQL database, which should be mostly compatible.
    """
    if MISSING_REQUIRED_ENV_VARS:
        user = settings.PG_USER
        password = settings.PG_PASSWORD
        host = settings.PG_HOST
        port = int(settings.PG_PORT)
        warnings.warn("Missing required Redshift env vars. Running tests against local PG database.", stacklevel=1)

    else:
        user = os.environ["REDSHIFT_USER"]
        password = os.environ["REDSHIFT_PASSWORD"]
        host = os.environ["REDSHIFT_HOST"]
        port = int(os.environ.get("REDSHIFT_PORT", "5439"))

    return {
        "user": user,
        "password": password,
        "database": "posthog_batch_exports_test_2",
        "schema": "exports_test_schema",
        "host": host,
        "port": port,
    }


@pytest.fixture
def postgres_config(redshift_config):
    """We shadow this name so that setup_postgres_test_db works with Redshift."""
    psycopg._encodings._py_codecs["UNICODE"] = "utf-8"
    psycopg._encodings.py_codecs.update((k.encode(), v) for k, v in psycopg._encodings._py_codecs.items())

    yield redshift_config


@pytest.fixture
async def psycopg_connection(redshift_config, setup_postgres_test_db):
    """Fixture to manage a psycopg2 connection."""
    connection = await psycopg.AsyncConnection.connect(
        user=redshift_config["user"],
        password=redshift_config["password"],
        dbname=redshift_config["database"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        # this is needed, otherwise query results are cached
        autocommit=True,
    )
    connection.prepare_threshold = None

    yield connection

    await connection.close()


@pytest.fixture
def properties_data_type(request) -> str:
    """A parametrizable fixture to configure the `str` `properties_data_type` setting."""
    try:
        return request.param
    except AttributeError:
        return "varchar"


@pytest.fixture
def bucket_name() -> str | None:
    """Name for a test S3 bucket."""
    test_bucket = os.getenv("S3_TEST_BUCKET")

    if not test_bucket:
        return None

    return test_bucket


@pytest.fixture
def bucket_region() -> str | None:
    """Region for a test S3 bucket."""
    bucket_region = os.getenv("AWS_REGION")

    if not bucket_region:
        return None

    return bucket_region


@pytest.fixture
def aws_credentials() -> AWSCredentials | None:
    """AWS credentials to test Redshift copy activity with an S3 bucket."""
    aws_access_key_id, aws_secret_access_key = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")

    if not aws_access_key_id or not aws_secret_access_key:
        return None

    return AWSCredentials(aws_access_key_id, aws_secret_access_key)


@pytest.fixture
def key_prefix(ateam) -> str:
    return f"/test-copy-redshift-batch-export_{ateam.pk}"


@pytest.fixture
async def s3_client(aws_credentials, bucket_name):
    """Manage an S3 client to interact with an S3 bucket."""
    if not aws_credentials or not bucket_name:
        yield None
        return

    async with aioboto3.Session().client("s3") as s3_client:
        yield s3_client
