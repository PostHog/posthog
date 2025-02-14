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
    status: Status
    message: str | None = None

    def as_dict(self) -> DestinationTestStepResultDict:
        return {
            "status": str(self.status),
            "message": self.message,
        }


DestinationTestStepDict = dict[str, str | DestinationTestStepResultDict]


class DestinationTestStep:
    """A single step in a destination test.

    Attributes:
        name: A short (ideally) string used to identify this step.
        description: A longer string with more details about this step.
    """

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.result: DestinationTestStepResult | None = None

    @abc.abstractmethod
    async def run(self) -> DestinationTestStepResult:
        raise NotImplementedError

    def as_dict(self) -> DestinationTestStepDict:
        base: dict[str, str | dict[str, str | None]] = {"name": self.name, "description": self.description}
        if self.result:
            base["result"] = self.result.as_dict()
        return base


class DestinationTest:
    @property
    @abc.abstractmethod
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        raise NotImplementedError

    def run_step(self, step: int) -> DestinationTestStepResult:
        step_result = async_to_sync(self.steps[step].run)()

        return step_result

    def as_dict(self) -> dict[str, list[DestinationTestStepDict]]:
        return {"steps": [step.as_dict() for step in self.steps]}


class S3CheckBucketExistsTestStep(DestinationTestStep):
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
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"Bucket '{self.bucket_name}' does not exist or we don't have permissions to use it",
                    )
                else:
                    return DestinationTestStepResult(
                        status=Status.FAILED,
                        message=f"An unknown error occurred when trying to access bucket '{self.bucket_name}': {err}",
                    )

        return DestinationTestStepResult(status=Status.PASSED)


class S3DestinationTest(DestinationTest):
    def __init__(self):
        self.bucket_name = None
        self.region = None
        self.aws_access_key_id = None
        self.aws_secret_access_key = None
        self.endpoint_url = None

    def configure(
        self,
        bucket_name: str,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        endpoint_url: str,
    ):
        self.bucket_name = bucket_name
        self.region = region
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.endpoint_url = endpoint_url

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
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
    def __init__(self, project_id: str | None = None, service_account_info: dict[str, str] | None = None) -> None:
        super().__init__(name="Check project exists", description="Verify the configured project exists")
        self.project_id = project_id
        self.service_account_info = service_account_info

    async def run(self) -> DestinationTestStepResult:
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
    def __init__(self):
        self.project_id = None
        self.dataset_id = None
        self.table_id = None
        self.service_account_info = None

    def configure(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        private_key: str,
        private_key_id: str,
        token_uri: str,
        client_email: str,
    ):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_id = table_id
        self.service_account_info = {
            "private_key": private_key,
            "private_key_id": private_key_id,
            "token_uri": token_uri,
            "client_email": client_email,
        }

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
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


class SnowflakeDestinationTest(DestinationTest):
    pass


class PostgreSQLDestinationTest(DestinationTest):
    pass


class RedshiftDestinationTest(DestinationTest):
    pass


def get_destination_test(destination: str, **kwargs) -> DestinationTest:
    if destination == "S3":
        return S3DestinationTest(**kwargs)
    elif destination == "Snowflake":
        return SnowflakeDestinationTest(**kwargs)
    elif destination == "BigQuery":
        return BigQueryDestinationTest(**kwargs)
    elif destination == "Postgres":
        return PostgreSQLDestinationTest(**kwargs)
    elif destination == "Redshift":
        return RedshiftDestinationTest(**kwargs)
    else:
        raise ValueError(f"Unsupported destination: {destination}")
