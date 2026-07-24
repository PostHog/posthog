import collections.abc

from products.batch_exports.backend.api.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    InvalidCredentialsError,
    PolicyStatement,
    get_credentials_using_user_aws_role,
)


class S3AssumeRoleTestStep(DestinationTestStep):
    """Test whether we can assume a configured AWS role.


    Attributes:
        aws_role_arn: AWS role ARN we are testing.
    """

    name = "Ensure we can assume provided AWS role"
    description = (
        "Ensure the configured AWS role ARN exists and that we have the required trust relationship to assume it."
    )

    def __init__(
        self,
        aws_role_arn: str | None = None,
        organization_id: str | None = None,
        max_attempts: int = 1,
    ) -> None:
        super().__init__()
        self.aws_role_arn = aws_role_arn
        self.organization_id = organization_id
        # This test verifies user-provided config, where failures are expected, so
        # default to a single attempt and report promptly rather than retrying.
        self.max_attempts = max_attempts

    def _is_configured(self) -> bool:
        # Always considered configured: when there is no role ARN to assume (e.g.
        # key-based auth) the step reports SKIPPED rather than failing.
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        from botocore.exceptions import ClientError

        if self.aws_role_arn is None:
            return DestinationTestStepResult(status=Status.SKIPPED, message="No configured AWS role ARN, skipping test")

        external_id = f"posthog-{self.organization_id}"
        try:
            _ = await get_credentials_using_user_aws_role(
                self.aws_role_arn,
                external_id,
                session_name="PostHog-batch-exports-test",
                policy_statements=[
                    PolicyStatement(Effect="Allow", Action=["s3:ListBucket"], Resource="arn:aws:s3:::*")
                ],
                max_attempts=self.max_attempts,
            )
        except InvalidCredentialsError as err:
            return DestinationTestStepResult(
                status=Status.FAILED,
                # The error message here is already pretty clear.
                message=str(err),
            )

        except ClientError as err:
            error_code = err.response.get("Error", {}).get("Code")
            if error_code == "AccessDenied":
                # We can't really separate what went wrong here.
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"We couldn't assume '{self.aws_role_arn}' due to an 'AccessDenied' error. Ensure that the trust policy attached to the role allows 'sts:AssumeRole' for the PostHog role, that the 'ExternalId' condition is set, and that the role actually exists.",
                )

            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"An unknown error occurred when trying to assume '{self.aws_role_arn}': {err}",
            )
        except Exception as err:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"An unknown error occurred when trying to assume '{self.aws_role_arn}': {err}",
            )

        return DestinationTestStepResult(status=Status.PASSED)


class S3EnsureBucketTestStep(DestinationTestStep):
    """Test whether an S3 bucket exists and we can access it.

    This test could not be broken into two as the bucket not existing and not having
    permissions to access it looks the same from our perspective.

    Attributes:
        bucket_name: The bucket we are checking.
        region: Region where the bucket is supposed to be.
        endpoint_url: Set for S3-compatible destinations.
        aws_access_key_id: Access key ID for the bucket.
        aws_secret_access_key: Secret access key for the bucket.
    """

    name = "Check S3 bucket exists"
    description = "Ensure the configured S3 bucket exists and that we have the required permissions to access it."

    def __init__(
        self,
        bucket_name: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_role_arn: str | None = None,
        organization_id: str | None = None,
        max_attempts: int = 1,
    ) -> None:
        super().__init__()
        self.bucket_name = bucket_name
        self.region = region
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_role_arn = aws_role_arn
        self.organization_id = organization_id
        # This test verifies user-provided config, where failures are expected, so
        # default to a single attempt and report promptly rather than retrying.
        self.max_attempts = max_attempts

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if self.bucket_name is None:
            return False

        if (self.aws_role_arn is None or self.organization_id is None) and (
            self.aws_access_key_id is None or self.aws_secret_access_key is None
        ):
            return False

        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        import aioboto3
        from botocore.exceptions import ClientError

        session = aioboto3.Session()

        aws_access_key_id = self.aws_access_key_id
        aws_secret_access_key = self.aws_secret_access_key
        aws_session_token = None

        if self.aws_role_arn is not None:
            external_id = f"posthog-{self.organization_id}"

            credentials = await get_credentials_using_user_aws_role(
                self.aws_role_arn,
                external_id,
                session_name="PostHog-batch-exports-test",
                policy_statements=[
                    PolicyStatement(
                        Effect="Allow", Action=["s3:ListBucket"], Resource=f"arn:aws:s3:::{self.bucket_name}"
                    )
                ],
                max_attempts=self.max_attempts,
            )

            aws_access_key_id, aws_secret_access_key, aws_session_token = (
                credentials.aws_access_key_id,
                credentials.aws_secret_access_key,
                credentials.aws_session_token,
            )

        async with session.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            endpoint_url=self.endpoint_url,
        ) as client:
            assert self.bucket_name is not None
            try:
                await client.head_bucket(Bucket=self.bucket_name)
            except ClientError as err:
                error_code = err.response.get("Error", {}).get("Code")
                if error_code == "404":
                    # I think 404 is returned if the bucket doesn't exist **AND** we
                    # would have permissions to use it, where as 403 is for we wouldn't even
                    # have permissions, regardless of bucket status. But the message here intends to
                    # also cover the case when we don't have permissions for a specific bucket.
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"Bucket '{self.bucket_name}' does not exist or we don't have permissions to use it",
                    )
                elif error_code == "403":
                    # 403 is also apparently caused by `endpoint_url` problems.
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"We couldn't access bucket '{self.bucket_name}'. Check the provided credentials, endpoint, and whether the necessary permissions to access the bucket have been granted",
                    )
                else:
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"An unknown error occurred when trying to access bucket '{self.bucket_name}': {err}",
                    )

        return DestinationTestStepResult(status=Status.PASSED)


class S3CompatibleDestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for S3.

    Attributes:
        bucket_name: The bucket we are batch exporting to.
        region: Region where the bucket is supposed to be.
        endpoint_url: Set for S3-compatible destinations.
        aws_access_key_id: Access key ID for the bucket.
        aws_secret_access_key: Secret access key for the bucket.
    """

    def __init__(self):
        self.bucket_name = None
        self.region = None
        self.endpoint_url = None
        self.aws_access_key_id = None
        self.aws_secret_access_key = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.bucket_name = kwargs.get("bucket_name", None)
        self.region = kwargs.get("region", None)
        self.endpoint_url = kwargs.get("endpoint_url", None)
        self.aws_access_key_id = kwargs.get("aws_access_key_id", None)
        self.aws_secret_access_key = kwargs.get("aws_secret_access_key", None)

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            S3EnsureBucketTestStep(
                bucket_name=self.bucket_name,
                region=self.region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            )
        ]


class AwsS3DestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for AWS S3.

    Attributes:
        bucket_name: The bucket we are batch exporting to.
        region: Region where the bucket is supposed to be.
        aws_access_key_id: Access key ID for the bucket.
        aws_secret_access_key: Secret access key for the bucket.
        aws_role_arn: Role to assume to access the bucket, if not using
            long-lived credentials.
    """

    def __init__(self):
        self.bucket_name = None
        self.region = None
        self.aws_access_key_id = None
        self.aws_secret_access_key = None
        self.aws_role_arn = None
        self.organization_id: str | None = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.bucket_name = kwargs.get("bucket_name", None)
        self.region = kwargs.get("region", None)
        self.aws_access_key_id = kwargs.get("aws_access_key_id", None)
        self.aws_secret_access_key = kwargs.get("aws_secret_access_key", None)
        self.aws_role_arn = kwargs.get("aws_role_arn", None)

        integration = kwargs.get("integration", None)
        if integration is not None:
            self.organization_id = integration.team.organization_id

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            S3AssumeRoleTestStep(aws_role_arn=self.aws_role_arn, organization_id=self.organization_id),
            S3EnsureBucketTestStep(
                bucket_name=self.bucket_name,
                region=self.region,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                aws_role_arn=self.aws_role_arn,
                organization_id=self.organization_id,
            ),
        ]
