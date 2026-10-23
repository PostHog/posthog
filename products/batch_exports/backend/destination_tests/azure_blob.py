import collections.abc

from posthog.models.integration.azure_blob import EndpointNotAllowedError, strip_leading_whitespace
from posthog.security.pinned_requests import SSRFBlockedError

from products.batch_exports.backend.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)


class AzureBlobContainerTestStep(DestinationTestStep):
    """Test whether an Azure Blob container exists and we can access it.

    Attributes:
        connection_string: Azure Storage connection string.
        container_name: The container we are checking.
    """

    name = "Check Azure Blob container exists"
    description = "Ensure the configured container exists and that we have the required permissions to access it."

    def __init__(
        self,
        connection_string: str | None = None,
        container_name: str | None = None,
    ) -> None:
        super().__init__()
        self.connection_string = connection_string
        self.container_name = container_name

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        return self.connection_string is not None and self.container_name is not None

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError, ServiceRequestError

        from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
            MalformedConnectionStringError,
            azure_container_client,
        )

        assert self.connection_string is not None
        assert self.container_name is not None

        connection_string = strip_leading_whitespace(self.connection_string)
        try:
            async with azure_container_client(connection_string, self.container_name) as client:
                await client.get_container_properties()
        except (MalformedConnectionStringError, EndpointNotAllowedError, SSRFBlockedError) as e:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Invalid connection string: {str(e)}",
            )
        except ResourceNotFoundError:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Container '{self.container_name}' does not exist",
            )
        except ClientAuthenticationError:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message="Authentication failed. Check your connection string credentials",
            )
        except ServiceRequestError as err:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Could not connect to Azure Blob Storage: {err}",
            )

        return DestinationTestStepResult(status=Status.PASSED)


class AzureBlobDestinationTest(DestinationTest):
    """A concrete implementation of a `DestinationTest` for Azure Blob Storage.

    Attributes:
        connection_string: Azure Storage connection string.
        container_name: The container we are batch exporting to.
    """

    def __init__(self):
        self.connection_string = None
        self.container_name = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.connection_string = kwargs.get("connection_string", None)
        self.container_name = kwargs.get("container_name", None)

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            AzureBlobContainerTestStep(
                connection_string=self.connection_string,
                container_name=self.container_name,
            )
        ]
