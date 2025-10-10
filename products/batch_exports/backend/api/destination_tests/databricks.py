import collections.abc

from products.batch_exports.backend.api.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksClient,
    DatabricksConnectionError,
)


class DatabricksEstablishConnectionTestStep(DestinationTestStep):
    """Test whether we can establish a connection to Databricks.

    Attributes:
        server_hostname: Databricks server hostname.
        http_path: Databricks http path.
        client_id: Databricks client id.
        client_secret: Databricks client secret.
    """

    name = "Establish connection to Databricks"
    description = "Attempt to establish a Databricks connection with the provided configuration values."

    def __init__(
        self,
        server_hostname: str | None = None,
        http_path: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        super().__init__()
        self.server_hostname = server_hostname
        self.http_path = http_path
        self.client_id = client_id
        self.client_secret = client_secret

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

        try:
            async with client.connect(set_context=False):
                pass
        except DatabricksConnectionError as err:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=str(err),
            )

        return DestinationTestStepResult(
            status=Status.PASSED,
        )


class DatabricksDestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for Databricks."""

    def __init__(self):
        self.server_hostname = None
        self.http_path = None
        self.client_id = None
        self.client_secret = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.server_hostname = kwargs.get("server_hostname", None)
        self.http_path = kwargs.get("http_path", None)
        self.client_id = kwargs.get("client_id", None)
        self.client_secret = kwargs.get("client_secret", None)

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
        ]
