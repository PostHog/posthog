import uuid
import collections.abc

import pytest

from django.test import override_settings

import aioboto3
import pytest_asyncio
from temporalio.testing._activity import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    PolicyStatement,
    S3InsertInputs,
    get_credentials_using_user_aws_role,
    s3_default_fields,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import (
    assert_clickhouse_records_in_s3,
    run_activity,
)


@pytest.fixture(scope="module")
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"test-role-assumption-{str(uuid.uuid4())}"


async def test_get_credentials_using_user_aws_role(
    external_aws_role_arn: str, destination_aws_role_arn: str, aorganization: Organization, bucket_name: str
):
    external_id = str(aorganization.id)

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        credentials = await get_credentials_using_user_aws_role(
            destination_aws_role_arn,
            external_id,
            session_name="test",
            policy_statements=[
                PolicyStatement(Effect="Allow", Action=["s3:ListBucket"], Resource="arn:aws:s3:::{bucket_name}")
            ],
        )

    session = aioboto3.Session(
        aws_access_key_id=credentials.aws_access_key_id,
        aws_secret_access_key=credentials.aws_secret_access_key,
        aws_session_token=credentials.aws_session_token,
    )

    async with session.client("sts") as sts:
        identity = await sts.get_caller_identity()

    # The ARNs between assumed and requested will not match exactly the same
    # So, we take out the role part that we care about and check that.
    assert identity["Arn"].rsplit("/", 2)[1] == destination_aws_role_arn.rsplit("/", 1)[1]


@pytest_asyncio.fixture
async def integration(ateam: Team, destination_aws_role_arn: str) -> collections.abc.AsyncIterator[Integration]:
    integration = await Integration.objects.acreate(
        team_id=ateam.pk,
        kind=Integration.IntegrationKind.AWS_S3,
        integration_id="s3-role-assumption",
        config={"name": "test-role-assumption", "aws_role_arn": destination_aws_role_arn},
    )

    yield integration

    await integration.adelete()


@pytest.fixture
def kms_key_value(request) -> str | None:
    if not request.param:
        return None
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize(
    "kms_key_value",
    [None, "kms_key_id", "kms_key_arn"],
    indirect=True,
)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
async def test_insert_into_s3_activity_puts_data_into_s3_with_role_assumption(
    clickhouse_client,
    activity_environment: ActivityEnvironment,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel,
    generate_test_data,
    integration: Integration,
    s3_client,
    external_aws_role_arn: str,
    ateam: Team,
    s3_bucket: str,
    region: str,
    kms_key_value: str | None,
):
    """Test the main S3 batch export activity using role assumption auth."""
    prefix = "batch-exports/" + str(uuid.uuid4())

    batch_export_id = str(uuid.uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=s3_bucket,
        region=region,
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        integration_id=integration.id,
        compression="zstd",
        file_format="Parquet",
        batch_export_model=model,
        batch_export_id=batch_export_id,
        destination_default_fields=s3_default_fields(),
        kms_key_id=kms_key_value,
        encryption="aws:kms" if kms_key_value is not None else None,
    )

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await run_activity(activity_environment, insert_inputs)

    records_exported = result.records_completed
    bytes_exported = result.bytes_exported
    assert result.error is None

    events_to_export_created, _ = generate_test_data
    assert records_exported == len(events_to_export_created)

    assert isinstance(bytes_exported, int)
    assert bytes_exported > 0

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=s3_client,
        clickhouse_client=clickhouse_client,
        bucket_name=s3_bucket,
        key_prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        compression="zstd",
        file_format="Parquet",
        sort_key="uuid",
    )


@pytest.mark.parametrize("external_id", ["not-an-org-id", None], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
async def test_insert_into_s3_activity_fails_role_assumption_with_missing_external_id(
    clickhouse_client,
    activity_environment: ActivityEnvironment,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel,
    generate_test_data,
    integration: Integration,
    s3_client,
    external_aws_role_arn: str,
    bucket_name: str,
    ateam: Team,
    region: str,
    external_id: str | None,
):
    """Test the main S3 batch export activity fails role assumption with wrong external id.

    When the external id doesn't match, then we expect an access denied error, when the
    external id is not present at all, then we should raise our own error explaining that
    external id is required.
    """
    prefix = "batch-exports/" + str(uuid.uuid4())

    batch_export_id = str(uuid.uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region=region,
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        integration_id=integration.id,
        compression="zstd",
        file_format="Parquet",
        batch_export_model=model,
        batch_export_id=batch_export_id,
        destination_default_fields=s3_default_fields(),
    )

    with override_settings(BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN=external_aws_role_arn):
        result = await run_activity(activity_environment, insert_inputs)

    assert result.error is not None
    if external_id:
        assert "AccessDenied" in result.error.message
    else:
        assert "allows access without a required external id condition" in result.error.message
