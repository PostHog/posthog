import json
import typing
import asyncio
import secrets
import datetime as dt
import contextlib
import dataclasses
import collections.abc

import pyarrow as pa
import aioboto3
import botocore.exceptions
from aiobotocore.config import AioConfig
from opentelemetry import trace

if typing.TYPE_CHECKING:
    from types_aiobotocore_s3.client import S3Client
    from types_aiobotocore_s3.type_defs import CompletedPartTypeDef, UploadPartOutputTypeDef

from django.conf import settings

from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.models.integration import (
    AwsS3Integration,
    AwsS3RoleBasedIntegration,
    Integration,
    S3CompatibleIntegration,
    S3CredentialIntegrationError,
)
from posthog.models.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger, get_write_only_logger

from products.batch_exports.backend.service import (
    AWSCredentials,
    BatchExportField,
    BatchExportInsertInputs,
    BatchExportModel,
    S3BatchExportInputs,
)
from products.batch_exports.backend.temporal.batch_exports import (
    OverBillingLimitError,
    StartBatchExportRunInputs,
    default_fields,
    get_data_interval,
    start_batch_export_run,
)
from products.batch_exports.backend.temporal.destinations.constants import (
    S3_SUPPORTED_COMPRESSIONS as SUPPORTED_COMPRESSIONS,
)
from products.batch_exports.backend.temporal.destinations.utils import (
    get_absolute_key_prefix,
    get_manifest_key,
    get_object_key,
)
from products.batch_exports.backend.temporal.metrics import Attributes, CumulativeTimer, ExecutionTimeRecorder
from products.batch_exports.backend.temporal.pipeline.consumer import Consumer, run_consumer_from_stage
from products.batch_exports.backend.temporal.pipeline.entrypoint import execute_batch_export_using_internal_stage
from products.batch_exports.backend.temporal.pipeline.producer import Producer as ProducerFromInternalStage
from products.batch_exports.backend.temporal.pipeline.transformer import (
    ParquetStreamTransformer,
    get_json_stream_transformer,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.spmc import RecordBatchQueue, wait_for_schema_or_producer
from products.batch_exports.backend.temporal.utils import handle_non_retryable_errors

NON_RETRYABLE_ERROR_TYPES = (
    # S3 parameter validation failed.
    "ParamValidationError",
    # This error usually indicates credentials are incorrect or permissions are missing.
    "ClientError",
    # An S3 bucket doesn't exist.
    "NoSuchBucket",
    # Couldn't connect to custom S3 endpoint
    "EndpointConnectionError",
    # User provided an invalid S3 key
    "InvalidS3Key",
    # Invalid S3 endpoint URL
    "InvalidS3EndpointError",
    # Invalid file_format input
    "UnsupportedFileFormatError",
    # Invalid compression input
    "UnsupportedCompressionError",
    # Invalid S3 credentials
    "InvalidCredentialsError",
    # The linked Integration was deleted or doesn't belong to the team
    "S3IntegrationNotFoundError",
    # The linked Integration is the wrong kind or has invalid/missing credentials
    "S3CredentialIntegrationError",
)

FILE_FORMAT_EXTENSIONS = {
    "Parquet": "parquet",
    "JSONLines": "jsonl",
}

COMPRESSION_EXTENSIONS = {
    "gzip": "gz",
    "snappy": "sz",
    "brotli": "br",
    "zstd": "zst",
    "lz4": "lz4",
}

LOGGER = get_write_only_logger(__name__)
EXTERNAL_LOGGER = get_logger("EXTERNAL")
TRACER = trace.get_tracer(__name__)
SESSION = aioboto3.Session()


class UnsupportedFileFormatError(Exception):
    """Raised when an unsupported file format is requested."""

    def __init__(self, file_format: str):
        super().__init__(f"'{file_format}' is not a supported format for S3 batch exports.")


class UnsupportedCompressionError(Exception):
    """Raised when an unsupported compression is requested."""

    def __init__(self, compression: str):
        super().__init__(f"'{compression}' is not a supported compression for S3 batch exports.")


class S3IntegrationNotFoundError(Exception):
    """Raised when an S3-family export references an Integration that can't be resolved."""

    def __init__(self, integration_id: int, team_id: int):
        super().__init__(f"S3 integration with ID '{integration_id}' not found for team '{team_id}'")


async def _get_s3_integration(
    integration_id: int, team_id: int
) -> AwsS3RoleBasedIntegration | AwsS3Integration | S3CompatibleIntegration:
    """Fetch an S3-family integration from the database.

    The kind is validated on create by the batch export serializer, so the wrong-kind branch is
    purely defensive against an integration whose kind was changed out from under the export.
    `AwsS3Integration`/`S3CompatibleIntegration` themselves raise `S3CredentialIntegrationError` if
    the credentials are malformed.
    """
    try:
        integration = await Integration.objects.aget(id=integration_id, team_id=team_id)
    except Integration.DoesNotExist:
        raise S3IntegrationNotFoundError(integration_id, team_id)  # noqa: B904

    if integration.kind == Integration.IntegrationKind.AWS_S3:
        if "aws_role_arn" in integration.config:
            return AwsS3RoleBasedIntegration(integration)
        return AwsS3Integration(integration)

    if integration.kind == Integration.IntegrationKind.S3_COMPATIBLE:
        return S3CompatibleIntegration(integration)

    raise S3CredentialIntegrationError(
        f"Integration with ID '{integration_id}' for team '{team_id}' is not an S3 integration "
        f"(kind='{integration.kind}')"
    )


@dataclasses.dataclass(kw_only=True)
class S3InsertInputs(BatchExportInsertInputs):
    """Inputs for S3 exports."""

    # TODO: do _not_ store credentials in temporal inputs. It makes it very hard
    # to keep track of where credentials are being stored and increases the
    # attach surface for credential leaks.

    bucket_name: str
    region: str
    prefix: str
    # When set, credentials (and endpoint_url for S3-compatible) are resolved from this Integration
    # at run time; otherwise the inline credentials below are used (legacy path).
    integration_id: int | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    compression: str | None = None
    encryption: str | None = None
    kms_key_id: str | None = None
    endpoint_url: str | None = None
    # TODO: In Python 3.11, this could be a enum.StrEnum.
    file_format: str = "JSONLines"
    max_file_size_mb: int | None = None
    use_virtual_style_addressing: bool = False


def get_s3_key_from_inputs(inputs: S3InsertInputs, file_number: int = 0) -> str:
    return get_object_key(
        prefix=inputs.prefix,
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        batch_export_model=inputs.batch_export_model,
        file_extension=FILE_FORMAT_EXTENSIONS[inputs.file_format],
        compression_extension=COMPRESSION_EXTENSIONS[inputs.compression] if inputs.compression is not None else None,
        file_number=file_number,
        include_file_number=bool(inputs.max_file_size_mb),
    )


class InvalidS3Key(Exception):
    """Exception raised when an invalid S3 key is provided."""

    def __init__(self, err):
        super().__init__(f"An invalid S3 key was provided: {err}")


class UploadAlreadyInProgressError(Exception):
    """Exception raised when an S3MultiPartUpload is already in progress."""

    def __init__(self, upload_id):
        super().__init__(f"This upload is already in progress with ID: {upload_id}. Instantiate a new object.")


class NoUploadInProgressError(Exception):
    """Exception raised when there is no S3MultiPartUpload in progress."""

    def __init__(self):
        super().__init__("No multi-part upload is in progress. Call 'create' to start one.")


class IntermittentUploadPartTimeoutError(Exception):
    """Exception raised when an S3 upload part times out.

    This is generally a transient or intermittent error that can be handled by a retry.
    However, it's wrapped by a `botocore.exceptions.ClientError` that generally includes
    non-retryable errors. So, we can re-raise our own exception in those cases.
    """

    def __init__(self, part_number: int):
        super().__init__(f"An intermittent `RequestTimeout` was raised while attempting to upload part {part_number}")


class InvalidS3EndpointError(Exception):
    """Exception raised when an S3 endpoint is invalid."""

    def __init__(self, message: str = "Endpoint URL is invalid."):
        super().__init__(message)


class InvalidCredentialsError(Exception):
    """Exception raised when the S3 credentials are invalid."""

    def __init__(self, message: str = "Credentials are invalid."):
        super().__init__(message)


def s3_default_fields() -> list[BatchExportField]:
    """Default fields for an S3 batch export.

    Starting from the common default fields, we add and tweak some fields for
    backwards compatibility.
    """
    batch_export_fields = default_fields()
    batch_export_fields.append({"expression": "elements_chain", "alias": "elements_chain"})
    batch_export_fields.append({"expression": "person_properties", "alias": "person_properties"})
    batch_export_fields.append({"expression": "person_id", "alias": "person_id"})

    # Again, in contrast to other destinations, and for historical reasons, we do not include these fields.
    not_exported_by_default = {"team_id", "set", "set_once"}

    return [field for field in batch_export_fields if field["alias"] not in not_exported_by_default]


@workflow.defn(name="s3-export", failure_exception_types=[workflow.NondeterminismError])
class S3BatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into S3 or any S3-compatible bucket.

    This Workflow is shared across every S3-family destination — `AwsS3`, `S3Compatible`,
    and the legacy `S3` alias. The API surface validates per-destination input dataclasses
    (`AwsS3BatchExportInputs`, `S3CompatibleBatchExportInputs`); Temporal's data converter
    serializes them to JSON, and on deserialization fields not present on the narrower
    input class fall through to their `S3BatchExportInputs` defaults.

    This Workflow is intended to be executed both manually and by a Temporal Schedule.
    When ran by a schedule, `data_interval_end` should be set to `None` so that we will fetch the
    end of the interval from the Temporal search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> S3BatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return S3BatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: S3BatchExportInputs):
        """Workflow implementation to export data to S3 bucket."""
        is_backfill = inputs.get_is_backfill()
        is_earliest_backfill = inputs.get_is_earliest_backfill()
        data_interval_start, data_interval_end = get_data_interval(
            inputs.interval, inputs.data_interval_end, inputs.timezone
        )
        should_backfill_from_beginning = is_backfill and is_earliest_backfill

        start_batch_export_run_inputs = StartBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            backfill_id=inputs.backfill_details.backfill_id if inputs.backfill_details else None,
        )
        try:
            run_id = await workflow.execute_activity(
                start_batch_export_run,
                start_batch_export_run_inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "OverBillingLimitError"],
                ),
            )
        except OverBillingLimitError:
            return

        insert_inputs = S3InsertInputs(
            bucket_name=inputs.bucket_name,
            region=inputs.region,
            prefix=inputs.prefix,
            team_id=inputs.team_id,
            integration_id=inputs.integration_id,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
            endpoint_url=inputs.endpoint_url or None,
            data_interval_start=data_interval_start.isoformat() if not should_backfill_from_beginning else None,
            data_interval_end=data_interval_end.isoformat(),
            compression=inputs.compression,
            exclude_events=inputs.exclude_events,
            include_events=inputs.include_events,
            encryption=inputs.encryption,
            kms_key_id=inputs.kms_key_id,
            file_format=inputs.file_format,
            max_file_size_mb=inputs.max_file_size_mb,
            run_id=run_id,
            backfill_details=inputs.backfill_details,
            is_backfill=is_backfill,
            batch_export_model=inputs.batch_export_model,
            use_virtual_style_addressing=inputs.use_virtual_style_addressing,
            # TODO: Remove after updating existing batch exports.
            batch_export_schema=inputs.batch_export_schema,
            batch_export_id=inputs.batch_export_id,
            destination_default_fields=s3_default_fields(),
        )

        await execute_batch_export_using_internal_stage(
            insert_into_s3_activity_from_stage,
            insert_inputs,
            interval=inputs.interval,
        )
        return


@dataclasses.dataclass
class S3BatchExportResult(BatchExportResult):
    files_uploaded: list[str] = dataclasses.field(default_factory=list)


class PolicyStatement(typing.TypedDict):
    Effect: typing.Literal["Allow", "Deny"]
    Action: list[str]
    Resource: str


async def get_credentials_using_user_aws_role(
    aws_role_arn: str,
    external_id: str,
    /,
    session_name: str,
    policy_statements: list[PolicyStatement],
    duration: int = 3600,
    max_attempts: int = 5,
    delay: int | float = 1.0,
) -> AWSCredentials:
    """Attempt to obtain credentials assuming a user-provided AWS role.

    This assumes the pre-configured external AWS role available as the
    BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN setting is provided to users upon setting
    up an AWS S3 integration.

    Then, we use credentials from the external AWS role to assume the role
    provided by our users, finally returning our users credentials.

    Arguments:
        aws_role_arn: User-provided AWS role ARN. Should have S3 access
            permissions required for batch exports.
        external_id: An additional ID provided to users for security.
        session_name: The name used for both AWS sessions.
        policy_statements: Policy statements to request narrower permissions on
            final assumed role.
        duration: Maximum session duration, in seconds (1 hour limit).
        max_attempts: How many times to attempt to connect. Useful for tests as
            roles and/or policies may not be immediately available.
        delay: Initial delay in between connection attempts.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            async with SESSION.client("sts") as sts:
                first_response = await sts.assume_role(
                    RoleArn=settings.BATCH_EXPORT_S3_EXTERNAL_ROLE_ARN,
                    RoleSessionName=session_name,
                    # Hard limit of 1h imposed by AWS
                    # TODO: Support refreshable credentials so we can support batch
                    # exports running for longer
                    DurationSeconds=duration,
                    Policy=json.dumps(
                        # Narrow permissions to only allow assuming provided role with this
                        # session.
                        {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["sts:AssumeRole"],
                                    "Resource": aws_role_arn,
                                },
                            ],
                        }
                    ),
                )

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("AccessDenied", "InvalidClientTokenId") or attempt == max_attempts:
                raise

            await asyncio.sleep(min(delay * (2**attempt), 32))
            continue

        external_session = aioboto3.Session(
            aws_access_key_id=first_response["Credentials"]["AccessKeyId"],
            aws_secret_access_key=first_response["Credentials"]["SecretAccessKey"],
            aws_session_token=first_response["Credentials"]["SessionToken"],
        )
        try:
            async with external_session.client("sts") as sts:
                try:
                    # This first call is expected to fail, as it includes an
                    # invalid ExternalId. Passing here would indicate the
                    # customer has not included ExternalId condition in their
                    # policy, and we should fail.
                    _ = await sts.assume_role(
                        RoleArn=aws_role_arn,
                        RoleSessionName=session_name,
                        DurationSeconds=duration,
                        ExternalId=secrets.token_hex(67),
                    )
                except Exception:
                    pass
                else:
                    raise InvalidCredentialsError(
                        f"The provided role '{aws_role_arn}' allows access without a required external id condition. Update the role's policy with a condition to match '{external_id}' as a external id."
                    )
                second_response = await sts.assume_role(
                    RoleArn=aws_role_arn,
                    RoleSessionName=session_name,
                    DurationSeconds=duration,
                    ExternalId=external_id,
                    Policy=json.dumps(
                        # Narrow permissions in this session.
                        {
                            "Version": "2012-10-17",
                            "Statement": policy_statements,
                        }
                    ),
                )

        except botocore.exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("AccessDenied", "InvalidClientTokenId") or attempt == max_attempts:
                raise

            await asyncio.sleep(min(delay * (2**attempt), 32))
            continue
        else:
            break

    return AWSCredentials(
        aws_access_key_id=second_response["Credentials"]["AccessKeyId"],
        aws_secret_access_key=second_response["Credentials"]["SecretAccessKey"],
        aws_session_token=second_response["Credentials"]["SessionToken"],
    )


@contextlib.asynccontextmanager
async def s3_client(
    aws_access_key_id: str,
    aws_secret_access_key: str,
    aws_session_token: str | None,
    region: str,
    use_virtual_style_addressing: bool = False,
    endpoint_url: str | None = None,
) -> collections.abc.AsyncIterator["S3Client"]:
    session = aioboto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token,
    )

    config: dict[str, typing.Any] = {
        # Increase connection pool, so to ensure we're not limited by this
        "max_pool_connections": settings.BATCH_EXPORT_S3_MAX_CONCURRENT_UPLOADS * 5,
        # Set checksum calculation to 'when_required' for compatibility with S3-compatible
        # services like GCS that don't support AWS's newer checksum features
        "request_checksum_calculation": "when_required",
        "response_checksum_validation": "when_required",
    }
    if use_virtual_style_addressing:
        config["s3"] = {"addressing_style": "virtual"}

    try:
        async with session.client(
            "s3", config=AioConfig(**config), region_name=region, endpoint_url=endpoint_url
        ) as s3_client:
            yield s3_client

    except ValueError as err:
        if "Invalid endpoint" in str(err):
            raise InvalidS3EndpointError(str(err)) from err
        raise


@activity.defn
@handle_non_retryable_errors(NON_RETRYABLE_ERROR_TYPES)
async def insert_into_s3_activity_from_stage(inputs: S3InsertInputs) -> S3BatchExportResult:
    """Activity to batch export data from our internal S3 stage to a customer's S3.

    We support both AWS S3 and S3-compatible destinations (eg Cloudflare R2, DigitalOcean Spaces, etc).

    It will upload multiple files if the max_file_size_mb is set, otherwise it will upload a single
    file. File uploads are done using multipart upload.

    We could maybe optimize this by simply copying the data from the internal S3 stage to the
    customer's S3 bucket, however, we've tried to keep the activity that writes the data to the
    internal S3 stage as generic as possible, as it will be used by other destinations, not just S3.
    Our S3 batch exports also support customising the max S3 file size, different file formats,
    compression, etc, which ClickHouse's S3 functions may not support.
    """
    bind_contextvars(
        team_id=inputs.team_id,
        destination="S3",
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )

    if inputs.file_format not in FILE_FORMAT_EXTENSIONS:
        raise UnsupportedFileFormatError(inputs.file_format)
    if inputs.compression is not None and inputs.compression not in SUPPORTED_COMPRESSIONS[inputs.file_format]:
        raise UnsupportedCompressionError(inputs.compression)

    async with Heartbeater():
        # Integration-backed exports resolve credentials at run time; legacy exports carry them inline.
        # TODO: require integration
        aws_access_key_id = inputs.aws_access_key_id
        aws_secret_access_key = inputs.aws_secret_access_key
        aws_session_token = inputs.aws_session_token
        endpoint_url = inputs.endpoint_url

        if inputs.integration_id is not None:
            integration = await _get_s3_integration(inputs.integration_id, inputs.team_id)

            if isinstance(integration, AwsS3Integration):
                aws_access_key_id = integration.aws_access_key_id
                aws_secret_access_key = integration.aws_secret_access_key

            if isinstance(integration, AwsS3RoleBasedIntegration):
                team = await Team.objects.aget(id=inputs.team_id)
                organization_id = str(team.organization_id)

                bucket_name = inputs.bucket_name
                key_prefix = get_absolute_key_prefix(
                    inputs.prefix, inputs.data_interval_start, inputs.data_interval_end, inputs.batch_export_model
                )

                policy_statements = [
                    PolicyStatement(
                        Effect="Allow",
                        Action=["s3:PutObject", "s3:AbortMultipartUpload"],
                        Resource=f"arn:aws:s3:::{bucket_name}{key_prefix}*",
                    )
                ]

                # TODO: We should be more explicit about this parameter being
                # an ARN or an ID
                if inputs.kms_key_id is not None:
                    # KMS key could be in a different acount, in which case
                    # a customer would have provided the full ARN here.
                    if inputs.kms_key_id.startswith("arn:"):
                        resource = inputs.kms_key_id

                    else:
                        # If not, assume that the KMS key is in the same account as the role
                        # we are assuming. This is the same assumption S3 makes when passing
                        # just a key ID.
                        parts = integration.aws_role_arn.split(":")
                        if len(parts) < 6 or not parts[4]:
                            raise ValueError(f"Malformed role ARN: {integration.aws_role_arn!r}")
                        account_id = parts[4]

                        # I am aware KMS key aliases are a thing, but we explicitly ask for
                        # KMS key "ID". It's a user error if they pass an alias (and we can)
                        # just tell them to use the full ARN then.
                        resource = f"arn:aws:kms:{inputs.region}:{account_id}:key/{inputs.kms_key_id}"

                    policy_statements.append(
                        PolicyStatement(
                            Effect="Allow",
                            Action=["kms:GenerateDataKey", "kms:Decrypt"],
                            Resource=resource,
                        )
                    )

                credentials = await get_credentials_using_user_aws_role(
                    integration.aws_role_arn,
                    organization_id,
                    session_name=f"PostHog-batch-exports-{inputs.batch_export_id}",
                    policy_statements=policy_statements,
                )
                aws_access_key_id, aws_secret_access_key, aws_session_token = (
                    credentials.aws_access_key_id,
                    credentials.aws_secret_access_key,
                    credentials.aws_session_token,
                )

            if isinstance(integration, S3CompatibleIntegration):
                aws_access_key_id = integration.aws_access_key_id
                aws_secret_access_key = integration.aws_secret_access_key
                endpoint_url = integration.endpoint_url

        if not aws_access_key_id or not aws_secret_access_key:
            # At these point these need to be defined: either by us assuming a new
            # role, by an integration, or by the inputs.
            raise InvalidCredentialsError("AWS access key ID and secret access key cannot be empty")

        external_logger = EXTERNAL_LOGGER.bind()
        external_logger.info(
            "Batch exporting range %s - %s to S3: %s",
            inputs.data_interval_start or "START",
            inputs.data_interval_end or "END",
            get_s3_key_from_inputs(inputs),
        )

        queue = RecordBatchQueue(max_size_bytes=settings.BATCH_EXPORT_S3_RECORD_BATCH_QUEUE_MAX_SIZE_BYTES)
        producer = ProducerFromInternalStage()
        assert inputs.batch_export_id is not None
        producer_task = await producer.start(
            queue=queue,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=inputs.data_interval_start,
            data_interval_end=inputs.data_interval_end,
            max_record_batch_size_bytes=1024 * 1024 * 60,  # 60MB
            stage_folder=inputs.stage_folder,
        )

        record_batch_schema = await wait_for_schema_or_producer(queue, producer_task)
        if record_batch_schema is None:
            external_logger.info(
                "Batch export will finish early as there is no data matching specified filters in range %s - %s",
                inputs.data_interval_start or "START",
                inputs.data_interval_end or "END",
            )

            return S3BatchExportResult(records_completed=0, bytes_exported=0)

        record_batch_schema = pa.schema(
            # NOTE: For some reason, some batches set non-nullable fields as non-nullable, whereas other
            # record batches have them as nullable.
            # Until we figure it out, we set all fields to nullable. There are some fields we know
            # are not nullable, but I'm opting for the more flexible option until we out why schemas differ
            # between batches.
            [field.with_nullable(True) for field in record_batch_schema]
        )

        json_columns = ("properties", "person_properties", "set", "set_once")
        if inputs.file_format.lower() == "jsonlines":
            transformer = get_json_stream_transformer(
                compression=inputs.compression,
                include_inserted_at=True,
                max_file_size_bytes=inputs.max_file_size_mb * 1024 * 1024 if inputs.max_file_size_mb else 0,
            )
        else:
            transformer = ParquetStreamTransformer(
                compression=inputs.compression,
                include_inserted_at=True,
                max_file_size_bytes=inputs.max_file_size_mb * 1024 * 1024 if inputs.max_file_size_mb else 0,
            )

        async with s3_client(
            aws_access_key_id,
            aws_secret_access_key,
            aws_session_token,
            use_virtual_style_addressing=inputs.use_virtual_style_addressing,
            region=inputs.region,
            endpoint_url=endpoint_url,
        ) as client:
            consumer = ConcurrentS3Consumer.from_inputs(
                s3_client=client,
                s3_inputs=inputs,
                part_size=settings.BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES,
                max_concurrent_uploads=settings.BATCH_EXPORT_S3_MAX_CONCURRENT_UPLOADS,
            )

            result = await run_consumer_from_stage(
                queue=queue,
                consumer=consumer,
                producer_task=producer_task,
                transformer=transformer,
                json_columns=json_columns,
                records_total=inputs.records_total,
            )

        return S3BatchExportResult(
            bytes_exported=result.bytes_exported,
            records_completed=result.records_completed,
            records_failed=result.records_failed,
            error=result.error,
            files_uploaded=consumer.files_uploaded,
        )


class ConcurrentS3Consumer(Consumer):
    """A consumer that uploads chunks of data to S3 concurrently.

    It uses a memory buffer to store the data and upload it in parts. It uses 2 semaphores to limit the number of
    concurrent uploads and the memory buffer.
    """

    UPLOAD_PART_MAX_ATTEMPTS: int = 5
    MAX_RETRY_DELAY: float = 32.0
    INITIAL_RETRY_DELAY: float = 1.0
    EXPONENTIAL_BACKOFF_COEFFICIENT: float = 2.0

    def __init__(
        self,
        s3_client: "S3Client",
        bucket: str,
        region_name: str,
        prefix: str,
        data_interval_start: str | None,
        data_interval_end: str,
        batch_export_model: BatchExportModel | None,
        file_format: str,
        kms_key_id: str | None = None,
        max_file_size_mb: int | None = None,
        compression: str | None = None,
        encryption: str | None = None,
        endpoint_url: str | None = None,
        use_virtual_style_addressing: bool = False,
        part_size: int = 50 * 1024 * 1024,  # 50MB parts
        max_concurrent_uploads: int = 5,
    ):
        super().__init__(model=batch_export_model.name if batch_export_model else "events")

        self.bucket = bucket
        self.region_name = region_name
        self.prefix = prefix

        self.data_interval_start = data_interval_start
        self.data_interval_end = data_interval_end
        self.batch_export_model = batch_export_model

        self.file_format = file_format
        self.compression = compression
        self.encryption = encryption
        # This is only needed to obtain a file key. It's very easy to confuse it with
        # the transformer's `max_file_size_bytes` which actually does the file splitting.
        # TODO: Remove this from here, figure out a different way to obtain an S3 key.
        self.max_file_size_mb = max_file_size_mb

        self.kms_key_id = kms_key_id
        self.endpoint_url = endpoint_url
        self.use_virtual_style_addressing = use_virtual_style_addressing

        self.part_size = part_size
        self.max_concurrent_uploads = max_concurrent_uploads
        self.upload_semaphore = asyncio.Semaphore(max_concurrent_uploads)
        # Time spent blocked waiting for an upload slot (i.e. `max_concurrent_uploads` parts are
        # already in flight), reported as a span attribute. When this dominates the consumer's
        # consume time, the bottleneck is upload throughput to the destination.
        self._upload_slot_wait_timer = CumulativeTimer()
        self.s3_client = s3_client

        # File splitting management
        self.current_file_index = 0
        self.current_file_size = 0

        self.files_uploaded: list[str] = []
        self.current_buffer = bytearray()
        self.pending_uploads: dict[int, asyncio.Task] = {}  # part_number -> Future
        self.completed_parts: dict[int, CompletedPartTypeDef] = {}  # part_number -> part_info
        self.part_counter = 1
        self.upload_id: str | None = None

        self._finalized = False

    @classmethod
    def from_inputs(
        cls,
        s3_client: "S3Client",
        s3_inputs: S3InsertInputs,
        part_size: int = 50 * 1024 * 1024,
        max_concurrent_uploads: int = 5,
    ):
        return cls(
            s3_client=s3_client,
            bucket=s3_inputs.bucket_name,
            region_name=s3_inputs.region,
            prefix=s3_inputs.prefix,
            data_interval_start=s3_inputs.data_interval_start,
            data_interval_end=s3_inputs.data_interval_end,
            batch_export_model=s3_inputs.batch_export_model,
            file_format=s3_inputs.file_format,
            compression=s3_inputs.compression,
            encryption=s3_inputs.encryption,
            max_file_size_mb=s3_inputs.max_file_size_mb,
            kms_key_id=s3_inputs.kms_key_id,
            endpoint_url=s3_inputs.endpoint_url,
            use_virtual_style_addressing=s3_inputs.use_virtual_style_addressing,
            part_size=part_size,
            max_concurrent_uploads=max_concurrent_uploads,
        )

    async def finalize_file(self):
        await self._finalize_current_file()
        await self._start_new_file()

    async def consume_chunk(self, data: bytes):
        if self._finalized:
            raise RuntimeError("Consumer already finalized")

        self.current_buffer.extend(data)
        self.current_file_size += len(data)

        # Upload parts when buffer is full
        while len(self.current_buffer) >= self.part_size:
            await self._upload_next_part()
        else:
            # Ensure that we give pending tasks a chance to run.
            await asyncio.sleep(0)

    def reset_tracking(self) -> None:
        super().reset_tracking()
        self._upload_slot_wait_timer = CumulativeTimer()

    def get_destination_span_attributes(self) -> Attributes:
        return {
            "batch_export.s3.files_uploaded": len(self.files_uploaded),
            "batch_export.s3.total_upload_slot_wait_seconds": self._upload_slot_wait_timer.total_seconds,
        }

    async def _upload_next_part(self, final: bool = False):
        """Extract a part from buffer and upload it"""
        if not len(self.current_buffer):
            return

        if not self.upload_id:
            await self._initialize_multipart_upload()

        if final:
            self.logger.debug(
                "Uploading final part of file %s with upload id %s", self._get_current_key(), self.upload_id
            )
            # take all the data
            part_data = bytes(self.current_buffer)
        else:
            # Extract part data
            part_data = bytes(self.current_buffer[: self.part_size])
            self.current_buffer = self.current_buffer[self.part_size :]

        part_number = self.part_counter
        self.part_counter += 1

        # Acquire upload semaphore (blocks if too many uploads in flight)
        with self._upload_slot_wait_timer.time():
            await self.upload_semaphore.acquire()

        # Create upload task
        upload_task = asyncio.create_task(self._upload_part_with_cleanup(part_data, part_number))
        upload_task.add_done_callback(lambda task: self._on_upload_complete(task, part_number))

        # Track the upload
        self.pending_uploads[part_number] = upload_task

        if final:
            self.current_buffer.clear()

        self.logger.debug(
            "Concurrent uploads running: %s",
            len(self.pending_uploads),
        )

    async def _upload_part_with_cleanup(
        self,
        data: bytes,
        part_number: int,
    ):
        """Upload part and handle cleanup with retry logic.

        Note: This can run concurrently so need to be careful
        """
        # safety check - we should never have a part number without an upload id
        if not self.upload_id:
            raise NoUploadInProgressError()

        optional_kwargs = {}
        if self.endpoint_url is None:
            optional_kwargs["ChecksumAlgorithm"] = "CRC64NVME"

        try:
            self.logger.debug(
                "Uploading file number %s part %s with upload id %s",
                self.current_file_index,
                part_number,
                self.upload_id,
            )
            current_key = self._get_current_key()

            # Retry logic for upload_part
            response: UploadPartOutputTypeDef | None = None
            attempt = 0

            with (
                TRACER.start_as_current_span(
                    "batch_export.s3.upload_part",
                    attributes={
                        "batch_export.s3.file_number": self.current_file_index,
                        "batch_export.s3.part_number": part_number,
                        "batch_export.s3.part_bytes": len(data),
                    },
                ) as span,
                ExecutionTimeRecorder(
                    "s3_batch_export_upload_part_duration",
                    description="Total duration of the upload of a part of a multi-part upload",
                    log_message=(
                        "Finished uploading file number %(file_number)d part %(part_number)d"
                        " with upload id '%(upload_id)s' with status '%(status)s'."
                        " File size: %(mb_processed).2f MB, upload time: %(duration_seconds)d"
                        " seconds, speed: %(mb_per_second).2f MB/s"
                    ),
                    log_attributes={
                        "file_number": self.current_file_index,
                        "upload_id": self.upload_id,
                        "part_number": part_number,
                    },
                ) as recorder,
            ):
                recorder.add_bytes_processed(len(data))

                try:
                    while response is None:
                        attempt += 1
                        try:
                            response = await self.s3_client.upload_part(
                                Bucket=self.bucket,
                                Key=current_key,
                                PartNumber=part_number,
                                UploadId=self.upload_id,
                                Body=data,
                                **optional_kwargs,  # type: ignore
                            )

                        except botocore.exceptions.ClientError as err:
                            error_code = err.response.get("Error", {}).get("Code", None)

                            self.logger.warning(
                                "Caught ClientError while uploading file %s part %s: %s (attempt %s/%s)",
                                self.current_file_index,
                                part_number,
                                error_code,
                                attempt,
                                self.UPLOAD_PART_MAX_ATTEMPTS,
                            )

                            if error_code is not None and error_code == "RequestTimeout":
                                if attempt >= self.UPLOAD_PART_MAX_ATTEMPTS:
                                    raise IntermittentUploadPartTimeoutError(part_number=part_number) from err

                                retry_delay = min(
                                    self.MAX_RETRY_DELAY,
                                    self.INITIAL_RETRY_DELAY * (attempt**self.EXPONENTIAL_BACKOFF_COEFFICIENT),
                                )
                                self.logger.warning("Retrying part %s upload in %s seconds", part_number, retry_delay)
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                raise
                finally:
                    # Backoff sleeps happen inside this span, so the count also explains durations
                    # inflated by retries.
                    span.set_attribute("batch_export.s3.upload_attempts", attempt)

            part_info: CompletedPartTypeDef = {
                "ETag": response["ETag"],
                "PartNumber": part_number,
            }

            if "ChecksumCRC64NVME" in response:
                part_info["ChecksumCRC64NVME"] = response["ChecksumCRC64NVME"]

            # Store completed part info
            self.completed_parts[part_number] = part_info

            return part_info

        except Exception:
            self.logger.exception(
                "Failed to upload file number %s part %s with upload id %s",
                self.current_file_index,
                part_number,
                self.upload_id,
            )
            raise

    def _get_current_key(self) -> str:
        """Generate the key for the current file"""
        return get_object_key(
            prefix=self.prefix,
            data_interval_start=self.data_interval_start,
            data_interval_end=self.data_interval_end,
            batch_export_model=self.batch_export_model,
            file_extension=FILE_FORMAT_EXTENSIONS[self.file_format],
            compression_extension=COMPRESSION_EXTENSIONS[self.compression] if self.compression is not None else None,
            file_number=self.current_file_index,
            include_file_number=bool(self.max_file_size_mb),
        )

    async def _start_new_file(self):
        """Start a new file (reset state for file splitting)"""
        self.current_file_index += 1
        self.current_file_size = 0
        self.part_counter = 1
        self.upload_id = None
        self.pending_uploads.clear()
        self.completed_parts.clear()
        self.external_logger.info(
            "Starting multipart upload to '%s' for file number %d", self._get_current_key(), self.current_file_index
        )

    async def _finalize_current_file(self):
        """Finalize the current file before starting a new one"""
        if self.current_file_size == 0:
            return  # Nothing to finalize

        try:
            # Upload any remaining data in buffer
            if len(self.current_buffer) > 0:
                await self._upload_next_part(final=True)

            # Wait for all pending uploads for this file and check for errors
            # TODO - maybe we can improve error handling here
            if self.pending_uploads:
                try:
                    await asyncio.gather(*self.pending_uploads.values())
                except Exception:
                    self.logger.exception("One or more upload parts failed")
                    raise

            # Complete multipart upload if needed
            if self.upload_id:
                await self._complete_multipart_upload()

            self.files_uploaded.append(self._get_current_key())
            self.external_logger.info("Completed multipart upload for file number %d", self.current_file_index)

        except Exception:
            # Cleanup on error
            await self._abort()
            raise

    def _on_upload_complete(self, task: asyncio.Task, part_number: int):
        """Callback called when an upload task completes (success or failure)"""
        self.upload_semaphore.release()

        # Remove from pending uploads immediately
        self.pending_uploads.pop(part_number, None)

        # Ignore cancellations product of an aborted multi part upload
        if task.cancelled():
            self.logger.warning("Upload cancelled for file number %s part %s", self.current_file_index, part_number)
            return

        # Handle any exceptions
        if task.exception() is not None:
            # Log the error - the exception will be re-raised when the task is awaited
            self.logger.exception("Upload failed for file number %s part %s", self.current_file_index, part_number)

    async def _initialize_multipart_upload(self):
        """Initialize multipart upload with optimizations for large files"""
        if self.upload_id:
            raise UploadAlreadyInProgressError(self.upload_id)

        optional_kwargs = {}
        if self.encryption:
            optional_kwargs["ServerSideEncryption"] = self.encryption
        if self.kms_key_id:
            optional_kwargs["SSEKMSKeyId"] = self.kms_key_id
        if self.endpoint_url is None:
            optional_kwargs["ChecksumAlgorithm"] = "CRC64NVME"

        current_key = self._get_current_key()
        with TRACER.start_as_current_span(
            "batch_export.s3.create_multipart_upload",
            attributes={"batch_export.s3.file_number": self.current_file_index},
        ):
            response = await self.s3_client.create_multipart_upload(
                Bucket=self.bucket,
                Key=current_key,
                **optional_kwargs,  # type: ignore
            )
        self.upload_id = response["UploadId"]
        self.logger.debug("Initialized multipart upload for key %s with upload id %s", current_key, self.upload_id)

    async def finalize(self):
        """Finalize upload with proper cleanup"""
        if self._finalized:
            return

        try:
            # Finalize the current/last file
            await self._finalize_current_file()

        except Exception:
            # Cleanup on error
            await self._abort()
            raise

        finally:
            self._finalized = True
            # Final cleanup
            self.current_buffer.clear()

        # If using max file size (and therefore potentially expecting more than one file) upload a manifest file
        # containing the list of files.  This is used to check if the export is complete.
        if self.max_file_size_mb:
            manifest_key = get_manifest_key(
                self.prefix, self.data_interval_start, self.data_interval_end, self.batch_export_model
            )
            self.external_logger.info("Uploading manifest file '%s'", manifest_key)
            await self.upload_manifest_file(
                self.files_uploaded,
                manifest_key,
            )
            self.external_logger.info("All uploads completed. Uploaded %d files", len(self.files_uploaded))

    async def upload_manifest_file(
        self,
        files_uploaded: list[str],
        manifest_key: str,
    ):
        optional_kwargs = {}
        if self.endpoint_url is None:
            optional_kwargs["ChecksumAlgorithm"] = "CRC64NVME"

        with TRACER.start_as_current_span("batch_export.s3.upload_manifest"):
            await self.s3_client.put_object(
                Bucket=self.bucket,
                Key=manifest_key,
                Body=json.dumps({"files": files_uploaded}),
                **optional_kwargs,  # type: ignore
            )

    # TODO - maybe we can support upload small files without the need for multipart uploads
    # we just want to ensure we test both versions of the code path
    # async def _single_file_upload(self):
    #     """Handle small files that don't need multipart"""
    #     data = bytes(self.current_buffer)
    #     client = await self._get_s3_client()
    #     await client.put_object(Bucket=self.s3_inputs.bucket_name, Key=self._get_current_key(), Body=data)
    #     self.current_buffer.clear()
    #     self.current_file_size = 0

    async def _complete_multipart_upload(self):
        """Complete multipart upload with parts in order"""
        if not self.upload_id:
            raise NoUploadInProgressError()

        # Sort parts by part number
        sorted_parts = [self.completed_parts[part_num] for part_num in sorted(self.completed_parts.keys())]

        current_key = self._get_current_key()
        with TRACER.start_as_current_span(
            "batch_export.s3.complete_multipart_upload",
            attributes={
                "batch_export.s3.file_number": self.current_file_index,
                "batch_export.s3.num_parts": len(sorted_parts),
            },
        ):
            await self.s3_client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=current_key,
                UploadId=self.upload_id,
                MultipartUpload={"Parts": sorted_parts},
            )

    async def _abort(self):
        """Abort this S3 multi-part upload and cancel any in-flight part uploads."""
        if self.pending_uploads:
            for task in self.pending_uploads.values():
                task.cancel()
            await asyncio.gather(*self.pending_uploads.values(), return_exceptions=True)
            self.pending_uploads.clear()

        if self.upload_id:
            upload_id = self.upload_id
            try:
                await self.s3_client.abort_multipart_upload(
                    Bucket=self.bucket, Key=self._get_current_key(), UploadId=upload_id
                )
            except Exception:
                self.logger.exception("Best-effort abort of multipart upload %s failed", upload_id)
            finally:
                self.upload_id = None
