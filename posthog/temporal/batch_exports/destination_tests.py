import abc
import collections.abc
import dataclasses
import enum

from asgiref.sync import async_to_sync


class Status(enum.StrEnum):
    PASSED = "Passed"
    FAILED = "Failed"


DestinationTestStepResultDict = dict[str, str | None]


@dataclasses.dataclass
class DestinationTestStepResult:
    """The result of a test step.

    Attributes:
        status: Whether the test passed or failed.
        message: An optional message, only included on failure, describing the
            potential cause for the `status`.
    """

    status: Status
    message: str | None = None

    def as_dict(self) -> DestinationTestStepResultDict:
        """Serialize this as a dictionary."""
        return {
            "status": str(self.status),
            "message": self.message,
        }


DestinationTestStepDict = dict[str, str | DestinationTestStepResultDict | None]


class DestinationTestStep:
    """A single step in a destination test.

    Attributes:
        name: A short (ideally) string used to identify this step.
        description: A longer string with more details about this step.
        result: After running this test step, the result will be populated.
    """

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.result: DestinationTestStepResult | None = None

    @abc.abstractmethod
    async def run(self) -> DestinationTestStepResult:
        """Method called to run this test step.

        Subclasses should override this method and implement their concrete running
        operations.
        """
        raise NotImplementedError

    def as_dict(self) -> DestinationTestStepDict:
        """Serialize this as a dictionary."""
        base: dict[str, str | DestinationTestStepResultDict | None] = {
            "name": self.name,
            "description": self.description,
        }
        if self.result:
            base["result"] = self.result.as_dict()
        else:
            base["result"] = None
        return base


class DestinationTest:
    """Interface representing a test executed for a particular destination.

    A test is composed of multiple test steps organized in a linear hierarchy.
    This is used to represent that a parent test step should pass before allowing
    the next test steps (its children) to run. As a concrete example, if we have
    a test to check whether we can connect to a database, and a second test step
    to check whether we can create a table, it makes no sense to run the second
    test step if the first one fails. Future revisions of this interface could
    expand the hierarchy to allow for multiple paths (a tree), but for now a simple
    list is sufficient.

    Attributes:
        steps: A property returning a sequence of steps to run.
    """

    @abc.abstractmethod
    def configure(self, **kwargs):
        """Method to configure a concrete test.

        By "configure" I mean setting any attributes required to initialize and/or
        run test steps.

        Subclasses should override this to set any attributes. This decoupling of
        configuration from initialization allows us to serialize a `DestinationTest`
        without needing to configure it.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Property returning a sequence of steps to run.

        Subclasses should override this with their required test steps.
        """
        raise NotImplementedError

    def run_step(self, step: int) -> DestinationTestStep:
        """Run the test step at index `step`."""
        test_step = self.steps[step]
        step_result = async_to_sync(test_step.run)()

        test_step.result = step_result
        return test_step

    def as_dict(self) -> dict[str, list[DestinationTestStepDict]]:
        """Serialize this as a dictionary."""
        return {"steps": [step.as_dict() for step in self.steps]}


class S3CheckBucketExistsTestStep(DestinationTestStep):
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

    def __init__(
        self,
        bucket_name: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        super().__init__(
            name="Check S3 bucket exists", description="Verify the configured S3 bucket exists and we can access it"
        )
        self.bucket_name = bucket_name
        self.region = region
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    async def run(self) -> DestinationTestStepResult:
        """Run this test step."""
        import aioboto3
        from botocore.exceptions import ClientError

        if self.bucket_name is None or self.aws_access_key_id is None or self.aws_secret_access_key is None:
            raise ValueError("Test step not configured")

        session = aioboto3.Session()
        async with session.client(
            "s3",
            region_name=self.region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            endpoint_url=self.endpoint_url,
        ) as client:
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
            S3CheckBucketExistsTestStep(
                bucket_name=self.bucket_name,
                region=self.region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
            )
        ]


class BigQueryCheckProjectExistsTestStep(DestinationTestStep):
    """Test whether a BigQuery project exists and we can access it.

    This test could not be broken into two as the project not existing and us not
    having permissions to access it looks the same from our perspective.

    Attributes:
        project_id: ID of the BigQuery project we are checking.
        service_account_info: Service account credentials used to access the
            project.
    """

    def __init__(self, project_id: str | None = None, service_account_info: dict[str, str] | None = None) -> None:
        super().__init__(name="Check project exists", description="Verify the configured project exists")
        self.project_id = project_id
        self.service_account_info = service_account_info

    async def run(self) -> DestinationTestStepResult:
        """Run this test step."""
        from posthog.temporal.batch_exports.bigquery_batch_export import BigQueryClient

        if self.project_id is None or self.service_account_info is None:
            raise ValueError("Test step not configured")

        client = BigQueryClient.from_service_account_inputs(project_id=self.project_id, **self.service_account_info)
        projects = {p.project_id for p in client.list_projects()}

        if self.project_id in projects:
            return DestinationTestStepResult(status=Status.PASSED)
        else:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Project '{self.project_id}' could not be found because it doesn't exist or we don't have permissions to use it",
            )


class BigQueryCheckDatasetExistsTestStep(DestinationTestStep):
    """Test whether a BigQuery dataset exists and we can access it.

    This test could not be broken into two as the dataset not existing and us not
    having permissions to access it looks the same from our perspective.

    Attributes:
        project_id: ID of the BigQuery project containing the dataset.
        dataset_id: The ID of the dataset we are checking.
        service_account_info: Service account credentials used to access the
            project and dataset.
    """

    def __init__(
        self,
        project_id: str | None = None,
        dataset_id: str | None = None,
        service_account_info: dict[str, str] | None = None,
    ) -> None:
        super().__init__(name="Check dataset exists", description="Verify the configured dataset exists")
        self.dataset_id = dataset_id
        self.project_id = project_id
        self.service_account_info = service_account_info

    async def run(self) -> DestinationTestStepResult:
        """Run this test step."""
        from google.cloud.exceptions import NotFound

        from posthog.temporal.batch_exports.bigquery_batch_export import BigQueryClient

        if self.project_id is None or self.dataset_id is None or self.service_account_info is None:
            raise ValueError("Test step not configured")

        client = BigQueryClient.from_service_account_inputs(project_id=self.project_id, **self.service_account_info)

        try:
            _ = client.get_dataset(self.dataset_id)
        except NotFound:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Dataset '{self.dataset_id}' could not be found because it doesn't exist or we don't have permissions to use it",
            )
        else:
            return DestinationTestStepResult(status=Status.PASSED)


class BigQueryCheckTableTestStep(DestinationTestStep):
    """Test whether a BigQuery table exists or we can create it.

    A batch export will export data to an existing table or attempt to create
    a new one if a table doesn't exist. In the second case, we should have
    permissions to create a table.

    We also check for permissions to delete a table, although more as a side-effect
    of needing to clean-up after ourselves.

    Attributes:
        project_id: ID of the BigQuery project containing the dataset.
        dataset_id: The ID of the dataset containing the table.
        table_id: The ID of the table we are checking.
        service_account_info: Service account credentials used to access the
            project and dataset.
    """

    def __init__(
        self,
        project_id: str | None = None,
        dataset_id: str | None = None,
        table_id: str | None = None,
        service_account_info: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            name="Check batch exports table", description="Verify the configured table already exists or can be created"
        )
        self.dataset_id = dataset_id
        self.project_id = project_id
        self.table_id = table_id
        self.service_account_info = service_account_info

    async def run(self) -> DestinationTestStepResult:
        """Run this test step."""
        from google.api_core.exceptions import BadRequest
        from google.cloud import bigquery
        from google.cloud.exceptions import NotFound

        from posthog.temporal.batch_exports.bigquery_batch_export import BigQueryClient

        if (
            self.project_id is None
            or self.dataset_id is None
            or self.service_account_info is None
            or self.table_id is None
        ):
            raise ValueError("Test step not configured")

        client = BigQueryClient.from_service_account_inputs(project_id=self.project_id, **self.service_account_info)

        fully_qualified_name = f"{self.project_id}.{self.dataset_id}.{self.table_id}"
        table = bigquery.Table(fully_qualified_name, schema=[bigquery.SchemaField(name="event", field_type="STRING")])

        try:
            _ = client.get_table(table)
        except NotFound:
            try:
                # Since permissions to create are not table specific, we can test creating
                # a table with a slightly different ID so that it is easier to clean up for the
                # user in case the delete call later on fails.
                fully_qualified_name = f"{fully_qualified_name}_test"

                table = bigquery.Table(
                    fully_qualified_name, schema=[bigquery.SchemaField(name="event", field_type="STRING")]
                )

                _ = client.create_table(table, exists_ok=True)
            except BadRequest as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"A table could not be created in dataset '{self.dataset_id}': {err.errors[0]['message']}",
                )
            else:
                try:
                    client.delete_table(table, not_found_ok=True)
                except BadRequest as err:
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"A test table '{self.table_id}_test' was created, but could not be deleted afterwards: {err.errors[0]['message']}",
                    )

        return DestinationTestStepResult(status=Status.PASSED)


class BigQueryDestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for BigQuery.

    Attributes:
        project_id: ID of BigQuery project we are batch exporting to.
        dataset_id: ID of BigQuery dataset we are batch exporting to.
        table_id: ID of BigQuery table we are batch exporting to.
        service_account_info: Service account credentials used to access BigQuery.
    """

    def __init__(self):
        self.project_id = None
        self.dataset_id = None
        self.table_id = None
        self.service_account_info = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.project_id = kwargs.get("project_id", None)
        self.dataset_id = kwargs.get("dataset_id", None)
        self.table_id = kwargs.get("table_id", None)
        self.service_account_info = {
            "private_key": kwargs.get("private_key", None),
            "private_key_id": kwargs.get("private_key_id", None),
            "token_uri": kwargs.get("token_uri", None),
            "client_email": kwargs.get("client_email", None),
        }

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            BigQueryCheckProjectExistsTestStep(
                project_id=self.project_id, service_account_info=self.service_account_info
            ),
            BigQueryCheckDatasetExistsTestStep(
                project_id=self.project_id, dataset_id=self.dataset_id, service_account_info=self.service_account_info
            ),
            BigQueryCheckTableTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                table_id=self.table_id,
                service_account_info=self.service_account_info,
            ),
        ]


def get_destination_test(
    destination: str,
) -> DestinationTest:
    """Resolve a destination to its corresponding `DestinationTest` implementation."""
    if destination == "S3":
        return S3DestinationTest()
    elif destination == "BigQuery":
        return BigQueryDestinationTest()
    else:
        raise ValueError(f"Unsupported destination: {destination}")
