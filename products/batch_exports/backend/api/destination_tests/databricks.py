import contextlib
import collections.abc
from collections.abc import AsyncGenerator

from products.batch_exports.backend.api.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksCatalogNotFoundError,
    DatabricksClient,
    DatabricksConnectionError,
    DatabricksInsufficientPermissionsError,
    DatabricksSchemaNotFoundError,
)


class DatabricksTestStep(DestinationTestStep):
    """Base class for Databricks test steps.

    Attributes:
        server_hostname: Databricks server hostname.
        http_path: Databricks http path.
        client_id: Databricks client id.
        client_secret: Databricks client secret.
        catalog: Databricks catalog.
        schema: Databricks schema.
        table_name: Databricks table name.
    """

    def __init__(
        self,
        server_hostname: str | None = None,
        http_path: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        catalog: str | None = None,
        schema: str | None = None,
        table_name: str | None = None,
    ) -> None:
        super().__init__()
        self.server_hostname = server_hostname
        self.http_path = http_path
        self.client_id = client_id
        self.client_secret = client_secret
        self.catalog = catalog
        self.schema = schema
        self.table_name = table_name

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncGenerator[DatabricksClient, None]:
        assert self.server_hostname is not None
        assert self.http_path is not None
        assert self.client_id is not None
        assert self.client_secret is not None

        client = DatabricksClient(
            server_hostname=self.server_hostname,
            http_path=self.http_path,
            client_id=self.client_id,
            client_secret=self.client_secret,
            catalog="",
            schema="",
        )
        async with client.connect(set_context=False) as databricks_client:
            yield databricks_client


class DatabricksEstablishConnectionTestStep(DatabricksTestStep):
    """Test whether we can establish a connection to Databricks."""

    name = "Establish connection to Databricks"
    description = "Attempt to establish a Databricks connection with the provided configuration values."

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.server_hostname is None
            or self.http_path is None
            or self.client_id is None
            or self.client_secret is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""

        try:
            async with self.connect():
                pass
        except DatabricksConnectionError as err:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=str(err),
            )

        return DestinationTestStepResult(status=Status.PASSED)


class DatabricksCatalogTestStep(DatabricksTestStep):
    """Test whether we can use the configured Databricks catalog."""

    name = "Verify Databricks catalog"
    description = "Verify the configured Databricks catalog exists and we have the necessary permissions to use it."

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.server_hostname is None
            or self.http_path is None
            or self.client_id is None
            or self.client_secret is None
            or self.catalog is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""

        assert self.catalog is not None

        async with self.connect() as databricks_client:
            try:
                await databricks_client.use_catalog(self.catalog)
            except DatabricksCatalogNotFoundError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=str(err),
                )

        return DestinationTestStepResult(status=Status.PASSED)


class DatabricksSchemaTestStep(DatabricksTestStep):
    """Test whether we can use the configured Databricks schema."""

    name = "Verify Databricks schema"
    description = "Verify the configured Databricks schema exists and we have the necessary permissions to use it."

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.server_hostname is None
            or self.http_path is None
            or self.client_id is None
            or self.client_secret is None
            or self.catalog is None
            or self.schema is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""

        assert self.catalog is not None
        assert self.schema is not None

        async with self.connect() as databricks_client:
            await databricks_client.use_catalog(self.catalog)
            try:
                await databricks_client.use_schema(self.schema)
            except DatabricksSchemaNotFoundError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=str(err),
                )

        return DestinationTestStepResult(status=Status.PASSED)


class DatabricksTableTestStep(DatabricksTestStep):
    """Test whether a Databricks table exists or we can create it.

    A batch export will export data to an existing table or attempt to create
    a new one if a table doesn't exist. In the second case, we should have
    permissions to create a table.

    We also check for permissions to delete a table, although more as a side-effect
    of needing to clean-up after ourselves.
    """

    name = "Verify Databricks table"
    description = "Ensure the configured Databricks table already exists or that we have the required permissions to create it. Additionally, when creating this test table, we will attempt to delete it."

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.server_hostname is None
            or self.http_path is None
            or self.client_id is None
            or self.client_secret is None
            or self.catalog is None
            or self.schema is None
            or self.table_name is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""

        assert self.catalog is not None
        assert self.schema is not None
        assert self.table_name is not None

        async with self.connect() as databricks_client:
            await databricks_client.use_catalog(self.catalog)
            await databricks_client.use_schema(self.schema)
            try:
                columns = await databricks_client.aget_table_columns(self.table_name)
            except DatabricksInsufficientPermissionsError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=str(err),
                )
            if columns:
                # table exists
                return DestinationTestStepResult(status=Status.PASSED)

            # table does not exist, so try to create a test table
            test_table_name = f"{self.table_name}_test"
            try:
                await databricks_client.acreate_table(test_table_name, [("event", "STRING")])
            except DatabricksInsufficientPermissionsError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"A test table could not be created: {err}",
                )

            # now try to delete the test table
            try:
                await databricks_client.adelete_table(test_table_name)
            except DatabricksInsufficientPermissionsError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"A test table {test_table_name} was created, but could not be deleted afterwards: {err}",
                )

        return DestinationTestStepResult(status=Status.PASSED)


class DatabricksVolumeTestStep(DatabricksTestStep):
    """Test whether we can create a Databricks volume.

    A batch export needs to create a volume to upload files to. We also check for permissions to delete a volume.
    """

    name = "Verify permissions to create a Databricks volume"
    description = "Ensure we have the required permissions to create a Databricks volume. We need to create temporary volumes as part of the batch export process."

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.server_hostname is None
            or self.http_path is None
            or self.client_id is None
            or self.client_secret is None
            or self.catalog is None
            or self.schema is None
            or self.table_name is None
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""

        assert self.catalog is not None
        assert self.schema is not None
        assert self.table_name is not None

        async with self.connect() as databricks_client:
            await databricks_client.use_catalog(self.catalog)
            await databricks_client.use_schema(self.schema)

            test_volume_name = f"{self.table_name}_test"
            try:
                await databricks_client.acreate_volume(test_volume_name)
            except DatabricksInsufficientPermissionsError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"A test volume could not be created: {err}",
                )

            try:
                await databricks_client.adelete_volume(test_volume_name)
            except DatabricksInsufficientPermissionsError as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"A test volume {test_volume_name} was created, but could not be deleted afterwards: {err}",
                )

        return DestinationTestStepResult(status=Status.PASSED)


class DatabricksDestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for Databricks."""

    def __init__(self):
        self.server_hostname = None
        self.http_path = None
        self.client_id = None
        self.client_secret = None
        self.catalog = None
        self.schema = None
        self.table_name = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.server_hostname = kwargs.get("server_hostname", None)
        self.http_path = kwargs.get("http_path", None)
        self.client_id = kwargs.get("client_id", None)
        self.client_secret = kwargs.get("client_secret", None)
        self.catalog = kwargs.get("catalog", None)
        self.schema = kwargs.get("schema", None)
        self.table_name = kwargs.get("table_name", None)

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            DatabricksEstablishConnectionTestStep(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                client_id=self.client_id,
                client_secret=self.client_secret,
            ),
            DatabricksCatalogTestStep(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                client_id=self.client_id,
                client_secret=self.client_secret,
                catalog=self.catalog,
            ),
            DatabricksSchemaTestStep(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                client_id=self.client_id,
                client_secret=self.client_secret,
                catalog=self.catalog,
                schema=self.schema,
            ),
            DatabricksTableTestStep(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                client_id=self.client_id,
                client_secret=self.client_secret,
                catalog=self.catalog,
                schema=self.schema,
                table_name=self.table_name,
            ),
            DatabricksVolumeTestStep(
                server_hostname=self.server_hostname,
                http_path=self.http_path,
                client_id=self.client_id,
                client_secret=self.client_secret,
                catalog=self.catalog,
                schema=self.schema,
                table_name=self.table_name,
            ),
        ]
