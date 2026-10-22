import os
import uuid
import socket
import asyncio

import pytest
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import override_settings

import dns.exception
from botocore.exceptions import EndpointConnectionError, HTTPClientError

from products.batch_exports.backend.destination_tests import get_destination_test
from products.batch_exports.backend.destination_tests.s3 import (
    AwsS3DestinationTest,
    S3AssumeRoleTestStep,
    S3CompatibleDestinationTest,
    S3EnsureBucketTestStep,
    Status,
)
from products.batch_exports.backend.service import AWSCredentials
from products.batch_exports.backend.temporal.destinations.s3_batch_export import InvalidS3EndpointError, s3_client
from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3

TEST_ROOT_BUCKET = "test-destination-tests"

# Production destination tests use a single attempt (fast failure for users verifying
# config). These tests create a role and immediately assume it, so they need extra
# attempts to absorb IAM's eventual consistency.
ROLE_PROPAGATION_ATTEMPTS = 5


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest.fixture
async def object_storage_client(bucket_name):
    """Manage an S3 client to interact with a local object storage bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as object_storage_client:
        await object_storage_client.create_bucket(Bucket=bucket_name)

        yield object_storage_client

        await delete_all_from_s3(object_storage_client, bucket_name, key_prefix="/")

        await object_storage_client.delete_bucket(Bucket=bucket_name)


async def test_s3_check_bucket_exists_test_step(bucket_name, object_storage_client):
    test_step = S3EnsureBucketTestStep(
        bucket_name=bucket_name,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_s3_check_bucket_exists_test_step_without_bucket(object_storage_client):
    test_step = S3EnsureBucketTestStep(
        bucket_name="some-other-bucket",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message == "Bucket 'some-other-bucket' does not exist or we don't have permissions to use it"


@override_settings(FORCE_URL_VALIDATION=True, SSRF_TRUSTED_PROXY_URLS=["http://proxy.example.com:3128"])
@pytest.mark.parametrize("virtual", [False, True])
@pytest.mark.parametrize("proxied", [False, True])
async def test_custom_s3_connections_pin_the_sdk_hostname_and_preserve_proxies(virtual: bool, proxied: bool) -> None:
    resolved_hosts: list[str] = []
    addresses = {"storage.example.com": "93.184.216.34", "exports.storage.example.com": "1.1.1.1"}

    def resolve_name(host: str, **kwargs: object) -> Mock:
        address = "127.0.0.1" if host in resolved_hosts else addresses[host]
        resolved_hosts.append(host)
        return Mock(addresses=Mock(return_value=[address]))

    with (
        patch.dict(
            os.environ,
            {
                **{key: "" for key in os.environ if key.lower().endswith("_proxy")},
                "HTTPS_PROXY": "http://proxy.example.com:3128" if proxied else "",
            },
        ),
        patch("dns.resolver.Resolver.resolve_name", side_effect=resolve_name),
        patch(
            "aiohttp.connector.DefaultResolver.resolve",
            return_value=[
                {
                    "hostname": "proxy.example.com",
                    "host": "10.0.0.2",
                    "port": 3128,
                    "family": socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": socket.AI_NUMERICHOST,
                }
            ],
        ) as resolve_again,
        patch(
            "aiohappyeyeballs.start_connection", side_effect=RuntimeError("Socket connection intercepted")
        ) as connect,
    ):
        async with s3_client(
            AWSCredentials(aws_access_key_id="fake-key", aws_secret_access_key="fake-secret"),
            region="us-east-1",
            endpoint_url="https://storage.example.com",
            use_virtual_style_addressing=virtual,
        ) as client:
            assert resolved_hosts == []

            async def create_multipart_upload() -> None:
                with pytest.raises(HTTPClientError, match="Socket connection intercepted"):
                    await client.create_multipart_upload(Bucket="exports", Key=r"folder\events.jsonl")

            await asyncio.gather(create_multipart_upload(), create_multipart_upload())
            await create_multipart_upload()

    expected_host = "exports.storage.example.com" if virtual else "storage.example.com"
    assert resolved_hosts == [expected_host]
    assert connect.await_count == 3
    for call in connect.call_args_list:
        assert call.kwargs["addr_infos"][0][4][0] == ("10.0.0.2" if proxied else addresses[expected_host])
    if proxied:
        resolve_again.assert_awaited_once()
        assert resolve_again.call_args.args[0] == "proxy.example.com"
    else:
        resolve_again.assert_not_awaited()


@override_settings(FORCE_URL_VALIDATION=True)
@pytest.mark.parametrize(
    "address,expected_error,expected_message",
    [
        ("93.184.216.34", HTTPClientError, "Socket connection intercepted"),
        ("127.0.0.1", InvalidS3EndpointError, "Endpoint URL is invalid"),
        (None, EndpointConnectionError, "Could not connect to the endpoint URL"),
    ],
)
async def test_custom_s3_retries_dns_failures(
    address: str | None, expected_error: type[Exception], expected_message: str
) -> None:
    with (
        patch.dict(
            os.environ,
            {
                **{key: "" for key in os.environ if key.lower().endswith("_proxy")},
                "AWS_MAX_ATTEMPTS": "2",
                "AWS_RETRY_MODE": "standard",
            },
        ),
        patch(
            "dns.resolver.Resolver.resolve_name",
            side_effect=[
                dns.exception.Timeout(),
                Mock(addresses=Mock(return_value=[address])) if address is not None else dns.exception.Timeout(),
            ],
        ) as resolve,
        patch("botocore.retries.standard.ExponentialBackoff.delay_amount", return_value=0),
        patch(
            "aiohappyeyeballs.start_connection", side_effect=RuntimeError("Socket connection intercepted")
        ) as connect,
    ):
        async with s3_client(
            AWSCredentials(aws_access_key_id="fake-key", aws_secret_access_key="fake-secret"),
            region="us-east-1",
            endpoint_url="https://storage.example.com",
        ) as client:
            with pytest.raises(expected_error, match=expected_message):
                await client.head_bucket(Bucket="exports")

    assert resolve.call_count == 2
    if address == "93.184.216.34":
        connect.assert_awaited_once()
        assert connect.call_args.kwargs["addr_infos"][0][4][0] == address
    else:
        connect.assert_not_awaited()


@override_settings(FORCE_URL_VALIDATION=True)
@pytest.mark.parametrize("virtual", [False, True])
async def test_custom_s3_rejects_private_bucket_hostname_before_connecting(virtual: bool) -> None:
    with (
        patch(
            "dns.resolver.Resolver.resolve_name",
            return_value=Mock(addresses=Mock(return_value=["127.0.0.1"])),
        ),
        patch("aiohappyeyeballs.start_connection", side_effect=AssertionError("Unexpected connection")) as connect,
    ):
        async with s3_client(
            AWSCredentials(aws_access_key_id="fake-key", aws_secret_access_key="fake-secret"),
            region="us-east-1",
            endpoint_url="https://storage.example.com",
            use_virtual_style_addressing=virtual,
        ) as client:
            with pytest.raises(InvalidS3EndpointError):
                await client.head_bucket(Bucket="exports")

    connect.assert_not_awaited()


@pytest.mark.parametrize("debug,test", [(True, False), (False, True)])
async def test_custom_s3_bypasses_validation_in_dev_and_test(debug: bool, test: bool) -> None:
    with (
        override_settings(DEBUG=debug, TEST=test, FORCE_URL_VALIDATION=False),
        patch.dict(os.environ, {key: "" for key in os.environ if key.lower().endswith("_proxy")}),
        patch("dns.resolver.Resolver.resolve_name", side_effect=AssertionError("Unexpected validation")),
        patch(
            "aiohappyeyeballs.start_connection", side_effect=RuntimeError("Socket connection intercepted")
        ) as connect,
    ):
        async with s3_client(
            AWSCredentials(aws_access_key_id="fake-key", aws_secret_access_key="fake-secret"),
            region="us-east-1",
            endpoint_url="http://127.0.0.1:19000",
        ) as client:
            with pytest.raises(HTTPClientError, match="Socket connection intercepted"):
                await client.head_bucket(Bucket="exports")

    connect.assert_awaited_once()
    assert connect.call_args.kwargs["addr_infos"][0][4][0] == "127.0.0.1"


@override_settings(FORCE_URL_VALIDATION=True)
async def test_s3_destination_check_rejects_private_endpoint_before_connecting() -> None:
    step = S3EnsureBucketTestStep(
        bucket_name="exports",
        region="us-east-1",
        endpoint_url="https://storage.example.com",
        aws_access_key_id="fake-key",
        aws_secret_access_key="fake-secret",
    )
    with (
        patch("dns.resolver.Resolver.resolve_name", return_value=Mock(addresses=Mock(return_value=["127.0.0.1"]))),
        patch("aiohappyeyeballs.start_connection", side_effect=AssertionError("Unexpected connection")) as connect,
    ):
        result = await step.run()

    assert result.status == Status.FAILED
    assert "Endpoint URL is invalid" in (result.message or "")
    connect.assert_not_awaited()


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
        ("S3Compatible", S3CompatibleDestinationTest, [S3EnsureBucketTestStep]),
        ("AwsS3", AwsS3DestinationTest, [S3AssumeRoleTestStep, S3EnsureBucketTestStep]),
    ],
)
def test_get_destination_test_resolves_s3_family(destination, expected_test, expected_steps):
    destination_test = get_destination_test(destination=destination)

    assert isinstance(destination_test, expected_test)
    assert [type(step) for step in destination_test.steps] == expected_steps


def test_aws_s3_destination_test_builds_steps_without_integration() -> None:
    # The AwsS3 steps read organization_id, which an inline-credential config never sets.
    destination_test = AwsS3DestinationTest()
    destination_test.configure(bucket_name="b", region="us-east-1", aws_access_key_id="a", aws_secret_access_key="s")

    steps = destination_test.steps
    assert len(steps) > 0
    assert all(step.result is None for step in steps)


async def test_assume_role_step_passes_with_assumable_role(
    external_aws_role_arn: str,
    destination_aws_role_arn: str,
    aorganization,
    bucket_name,
):
    """The assume role step passes when the role is assumable with the right external id."""
    test_step = S3AssumeRoleTestStep(
        aws_role_arn=destination_aws_role_arn,
        bucket_name=bucket_name,
        organization_id=aorganization.id,
        max_attempts=ROLE_PROPAGATION_ATTEMPTS,
    )

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.PASSED, result.message
    assert result.message is None


@pytest.mark.parametrize("external_id", ["not-an-org-id"], indirect=True)
async def test_assume_role_step_fails_with_wrong_external_id(
    external_aws_role_arn: str,
    destination_aws_role_arn: str,
    external_id: str | None,
    bucket_name: str,
    aorganization,
):
    """A mismatched external id surfaces an AccessDenied failure."""
    test_step = S3AssumeRoleTestStep(
        aws_role_arn=destination_aws_role_arn, bucket_name=bucket_name, organization_id=aorganization.id
    )

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message is not None
    assert "AccessDenied" in result.message


@pytest.mark.parametrize("external_id", [None], indirect=True)
async def test_assume_role_step_fails_without_external_id_condition(
    external_aws_role_arn: str, destination_aws_role_arn: str, external_id: str | None, aorganization, bucket_name: str
):
    """A role whose trust policy omits the external id condition is rejected."""
    test_step = S3AssumeRoleTestStep(
        aws_role_arn=destination_aws_role_arn,
        bucket_name=bucket_name,
        organization_id=aorganization.id,
        max_attempts=ROLE_PROPAGATION_ATTEMPTS,
    )

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
        max_attempts=ROLE_PROPAGATION_ATTEMPTS,
    )

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None
