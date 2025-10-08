import collections.abc

from products.batch_exports.backend.api.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)


class BigQueryProjectTestStep(DestinationTestStep):
    """Test whether a BigQuery project exists and we can access it.

    This test could not be broken into two as the project not existing and us not
    having permissions to access it looks the same from our perspective.

    Permissions could be granted at the project level, or at the dataset level.
    To account for this, we check that the project exists by listing projects
    (`list_projects` call) and by listing datasets (with `list_datasets`) and
    inspecting the project associated with each dataset.

    Attributes:
        project_id: ID of the BigQuery project we are checking.
        service_account_info: Service account credentials used to access the
            project.
    """

    name = "Verify BigQuery project"
    description = (
        "Ensure the configured BigQuery project exists and that we have the required permissions to access it."
    )

    def __init__(self, project_id: str | None = None, service_account_info: dict[str, str] | None = None) -> None:
        super().__init__()
        self.project_id = project_id
        self.service_account_info = service_account_info

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.project_id is None
            or self.service_account_info is None
            or not all(
                param in self.service_account_info
                for param in ("private_key", "private_key_id", "token_uri", "client_email")
            )
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import BigQueryClient

        # This method should be called by `run()` which ensures this test step is configured
        # with non-`None` values.
        assert self.service_account_info is not None
        assert self.project_id is not None

        client = BigQueryClient.from_service_account_inputs(project_id=self.project_id, **self.service_account_info)
        projects = {p.project_id for p in client.list_projects()}

        if self.project_id in projects:
            return DestinationTestStepResult(status=Status.PASSED)

        dataset_projects = {d.project for d in client.list_datasets()}

        if self.project_id in dataset_projects:
            return DestinationTestStepResult(status=Status.PASSED)
        else:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Project '{self.project_id}' could not be found because it doesn't exist or we don't have permissions to use it",
            )


class BigQueryDatasetTestStep(DestinationTestStep):
    """Test whether a BigQuery dataset exists and we can access it.

    This test could not be broken into two as the dataset not existing and us not
    having permissions to access it looks the same from our perspective.

    Attributes:
        project_id: ID of the BigQuery project containing the dataset.
        dataset_id: The ID of the dataset we are checking.
        service_account_info: Service account credentials used to access the
            project and dataset.
    """

    name = "Verify BigQuery dataset"
    description = (
        "Ensure the configured BigQuery dataset exists and that we have the required permissions to access it."
    )

    def __init__(
        self,
        project_id: str | None = None,
        dataset_id: str | None = None,
        service_account_info: dict[str, str] | None = None,
    ) -> None:
        super().__init__()

        self.dataset_id = dataset_id
        self.project_id = project_id
        self.service_account_info = service_account_info

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.project_id is None
            or self.dataset_id is None
            or self.service_account_info is None
            or not all(
                param in self.service_account_info
                for param in ("private_key", "private_key_id", "token_uri", "client_email")
            )
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        from google.cloud.exceptions import NotFound

        from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import BigQueryClient

        # This method should be called by `run()` which ensures this test step is configured
        # with non-`None` values.
        assert self.service_account_info is not None
        assert self.project_id is not None
        assert self.dataset_id is not None

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


class BigQueryTableTestStep(DestinationTestStep):
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

    name = "Verify BigQuery table"
    description = (
        "Ensure the configured BigQuery table already exists or that we have the required permissions to create it. "
        "Additionally, when creating a table, we will attempt to delete it."
    )

    def __init__(
        self,
        project_id: str | None = None,
        dataset_id: str | None = None,
        table_id: str | None = None,
        service_account_info: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.dataset_id = dataset_id
        self.project_id = project_id
        self.table_id = table_id
        self.service_account_info = service_account_info

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.project_id is None
            or self.dataset_id is None
            or self.table_id is None
            or self.service_account_info is None
            or not all(
                param in self.service_account_info
                for param in ("private_key", "private_key_id", "token_uri", "client_email")
            )
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        from google.api_core.exceptions import BadRequest
        from google.cloud import bigquery
        from google.cloud.exceptions import NotFound

        from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import BigQueryClient

        # This method should be called by `run()` which ensures this test step is configured
        # with non-`None` values.
        assert self.service_account_info is not None
        assert self.project_id is not None

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
            BigQueryProjectTestStep(project_id=self.project_id, service_account_info=self.service_account_info),
            BigQueryDatasetTestStep(
                project_id=self.project_id, dataset_id=self.dataset_id, service_account_info=self.service_account_info
            ),
            BigQueryTableTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                table_id=self.table_id,
                service_account_info=self.service_account_info,
            ),
        ]
