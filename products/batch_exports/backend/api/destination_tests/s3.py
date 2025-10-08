import collections.abc

from products.batch_exports.backend.api.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)


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
    ) -> None:
        super().__init__()
        self.bucket_name = bucket_name
        self.region = region
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if self.bucket_name is None or self.aws_access_key_id is None or self.aws_secret_access_key is None:
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        import aioboto3
        from botocore.exceptions import ClientError

        session = aioboto3.Session()
        async with session.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
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


class S3DestinationTest(DestinationTest):
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
