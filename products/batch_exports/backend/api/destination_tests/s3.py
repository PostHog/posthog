import uuid
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


class S3EnsureMultiPartUploadTestStep(DestinationTestStep):
    """Test whether we can perform a multipart upload to the S3 bucket.

    Batch exports write their files using multipart uploads, so being able to
    access the bucket (see `S3EnsureBucketTestStep`) is not enough on its own.
    On some S3-compatible backends, most notably GCS, a set of credentials can
    pass a `head_bucket` check yet lack the permissions required for multipart
    uploads. Without this step, such credentials would only surface the problem
    at run time as a `SignatureDoesNotMatch` error when uploading a part. This
    step exercises the full `create` -> `upload_part` -> `complete` path so the
    missing permission surfaces at configuration time instead.

    Attributes:
        bucket_name: The bucket we are checking.
        region: Region where the bucket is supposed to be.
        endpoint_url: Set for S3-compatible destinations.
        aws_access_key_id: Access key ID for the bucket.
        aws_secret_access_key: Secret access key for the bucket.
    """

    name = "Check S3 multipart upload"
    description = "Ensure we can perform a multipart upload to the configured S3 bucket, as required by batch exports."

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

        assert self.bucket_name is not None

        # A dedicated key that won't collide with exported data, cleaned up below.
        key = f"__posthog_batch_export_connection_test__/{uuid.uuid4()}"

        session = aioboto3.Session()
        async with session.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            endpoint_url=self.endpoint_url,
        ) as client:
            upload_id: str | None = None
            completed = False
            try:
                response = await client.create_multipart_upload(Bucket=self.bucket_name, Key=key)
                upload_id = response["UploadId"]

                part = await client.upload_part(
                    Bucket=self.bucket_name,
                    Key=key,
                    PartNumber=1,
                    UploadId=upload_id,
                    Body=b"PostHog batch export connection test",
                )

                await client.complete_multipart_upload(
                    Bucket=self.bucket_name,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": [{"ETag": part["ETag"], "PartNumber": 1}]},
                )
                completed = True
            except ClientError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=(
                        f"We couldn't perform a multipart upload to bucket '{self.bucket_name}'. "
                        "Batch exports upload files using multipart uploads, so the provided credentials need "
                        "multipart-upload permissions (for example, on GCS grant a role such as "
                        f"'roles/storage.objectAdmin'). The underlying error was: {err}"
                    ),
                )
            finally:
                await self._cleanup(client, key, upload_id, completed)

        return DestinationTestStepResult(status=Status.PASSED)

    async def _cleanup(self, client, key: str, upload_id: str | None, completed: bool) -> None:
        """Best-effort cleanup of the test object or in-progress upload."""
        try:
            if completed:
                await client.delete_object(Bucket=self.bucket_name, Key=key)
            elif upload_id is not None:
                await client.abort_multipart_upload(Bucket=self.bucket_name, Key=key, UploadId=upload_id)
        except Exception:
            # Cleanup is best-effort: a leftover test object or aborted upload must not
            # fail an otherwise successful test.
            pass


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
            ),
            S3EnsureMultiPartUploadTestStep(
                bucket_name=self.bucket_name,
                region=self.region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            ),
        ]
