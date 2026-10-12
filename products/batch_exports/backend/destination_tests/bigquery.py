import typing
import asyncio
import collections.abc

import requests
import google.auth.transport.requests
from google.api_core.exceptions import BadRequest, NotFound, PermissionDenied
from google.cloud import bigquery, iam_admin_v1

from posthog.models.integration import GoogleCloudServiceAccountIntegration

from products.batch_exports.backend.destination_tests.base import (
    DestinationTest,
    DestinationTestStep,
    DestinationTestStepResult,
    Status,
)
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    get_our_google_cloud_credentials,
    impersonate_service_account,
)

if typing.TYPE_CHECKING:
    from google.auth.credentials import Credentials


class ServiceAccountInfo(typing.TypedDict):
    private_key: str
    private_key_id: str
    token_uri: str
    client_email: str


def get_client(
    project_id: str | None,
    integration: GoogleCloudServiceAccountIntegration | None,
    service_account_info: ServiceAccountInfo | None,
) -> BigQueryClient:
    """Get a `BigQueryClient` from an integration or service account information."""
    if project_id is None:
        raise ValueError("Project ID not set")

    if integration is not None:
        client = BigQueryClient.from_service_account_integration(integration=integration)
    elif service_account_info is not None:
        client = BigQueryClient.from_service_account_inputs(project_id=project_id, **service_account_info)
    else:
        raise ValueError("Either integration or service account information must be defined")

    return client


class BigQueryImpersonateServiceAccountTestStep(DestinationTestStep):
    """Test whether a BigQuery service account exists and we can impersonate it.

    Attributes:
        project_id: ID of the BigQuery project containing the service account.
        integration: Integration with service account configuration.
    """

    name = "Impersonate BigQuery service account"
    description = "Confirm we can impersonate a BigQuery service account."

    def __init__(
        self,
        project_id: str | None = None,
        integration: GoogleCloudServiceAccountIntegration | None = None,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.integration = integration

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if self.project_id is None:
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        if self.integration is None or self.integration.has_key():
            return DestinationTestStepResult(
                status=Status.SKIPPED, message="Using credentials without impersonation, skipping test"
            )

        try:
            their_credentials = impersonate_service_account(self.integration)
            # This triggers an actual credential refresh
            their_credentials.refresh(google.auth.transport.requests.Request())

        except NotFound:
            service_account_email = self.integration.service_account_email

            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Service account '{service_account_email}' was not found and cannot be impersonated. It may not exist or we may not have sufficient permissions.",
            )
        except Exception:
            service_account_email = self.integration.service_account_email

            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Failed to impersonate Service account '{service_account_email}'.",
            )

        return DestinationTestStepResult(status=Status.PASSED)


class BigQueryVerifyServiceAccountOwnershipTestStep(DestinationTestStep):
    """Test whether a BigQuery service account is owned by the current organization.

    We require users to set their organization ID as the service account description so
    that we can verify they own them at runtime. This test reproduces that verification
    to help debug incorrect descriptions or missing permissions.

    Attributes:
        project_id: ID of the BigQuery project containing the service account.
        integration: Integration with service account configuration.
    """

    name = "Verify BigQuery service account ownership"
    description = "Confirm that the current PostHog organization owns a BigQuery service account by ensuring its organization ID is set as part of the service account description."

    def __init__(
        self,
        project_id: str | None = None,
        integration: GoogleCloudServiceAccountIntegration | None = None,
        organization_id: str | None = None,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.integration = integration
        self.organization_id = organization_id

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if self.project_id is None:
            return False

        if self.integration is not None and not self.integration.has_key() and self.organization_id is None:
            # Only when we actually need to verify ownership is organization_id required
            return False

        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        if self.integration is None or self.integration.has_key():
            return DestinationTestStepResult(
                status=Status.SKIPPED, message="Using credentials without impersonation, ownership is assumed"
            )

        service_account_email = self.integration.service_account_email

        try:
            our_credentials = get_our_google_cloud_credentials()
            client = iam_admin_v1.IAMClient(credentials=our_credentials)
            sa = client.get_service_account(
                request=iam_admin_v1.GetServiceAccountRequest(
                    name=f"projects/-/serviceAccounts/{self.integration.service_account_email}"
                )
            )
        except PermissionDenied:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"No permission to read service account's '{service_account_email}' description. Have you granted the PostHog service account a role with `iam.serviceAccounts.get`?",
            )
        except NotFound:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Service account '{service_account_email}' was not found. It may not exist or we may not have sufficient permissions.",
            )
        except Exception:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Failed to verify ownership of service account '{service_account_email}'.",
            )

        if f"posthog:{self.organization_id}" not in sa.description:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Organization ID not found in service account's '{service_account_email}' description. Ownership could not be verified.",
            )

        return DestinationTestStepResult(status=Status.PASSED)


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

    def __init__(
        self,
        project_id: str | None = None,
        integration: GoogleCloudServiceAccountIntegration | None = None,
        service_account_info: ServiceAccountInfo | None = None,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.integration = integration
        self.service_account_info = service_account_info

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if self.project_id is None or (self.integration is None and self.service_account_info is None):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        client = get_client(self.project_id, self.integration, self.service_account_info)
        projects = {p.project_id for p in client.sync_client.list_projects()}

        if self.project_id in projects:
            return DestinationTestStepResult(status=Status.PASSED)

        dataset_projects = {d.project for d in client.sync_client.list_datasets()}

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
        create_if_missing: Check creation permissions if the dataset does not exist.
    """

    name = "Verify BigQuery dataset"
    description = (
        "Ensure the configured BigQuery dataset exists and that we have the required permissions to access it."
    )

    def __init__(
        self,
        project_id: str | None = None,
        dataset_id: str | None = None,
        integration: GoogleCloudServiceAccountIntegration | None = None,
        service_account_info: ServiceAccountInfo | None = None,
        create_if_missing: bool = False,
    ) -> None:
        super().__init__()

        self.dataset_id = dataset_id
        self.project_id = project_id
        self.integration = integration
        self.service_account_info = service_account_info
        self.create_if_missing = create_if_missing

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.project_id is None
            or self.dataset_id is None
            or (self.service_account_info is None and self.integration is None)
        ):
            return False
        return True

    def _test_iam_permissions(
        self, credentials: "Credentials", permissions: list[str]
    ) -> DestinationTestStepResult | list[str]:
        try:
            with google.auth.transport.requests.AuthorizedSession(credentials) as session:
                response = session.post(
                    f"https://cloudresourcemanager.googleapis.com/v1/projects/{self.project_id}:testIamPermissions",
                    json={"permissions": permissions},
                    timeout=30,
                )
        except requests.exceptions.RequestException:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Could not check permissions on project '{self.project_id}' because the request failed.",
            )

        if response.status_code == 403 and any(
            marker in response.text for marker in ("SERVICE_DISABLED", "has not been used", "is disabled")
        ):
            return DestinationTestStepResult(
                status=Status.SKIPPED,
                message="Could not check whether the service account can create datasets because the Cloud Resource Manager API is disabled for this project. Enable it, or create the dataset first.",
            )

        if not 200 <= response.status_code < 300:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Could not check permissions on project '{self.project_id}' (HTTP {response.status_code}).",
            )

        return response.json().get("permissions", [])

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        client = get_client(self.project_id, self.integration, self.service_account_info)

        # This method should be called by `run()` which ensures this test step is configured
        # with non-`None` values.
        assert self.dataset_id is not None

        try:
            _ = client.sync_client.get_dataset(self.dataset_id)
        except NotFound:
            if not self.create_if_missing:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"Dataset '{self.dataset_id}' could not be found because it doesn't exist or we don't have permissions to use it",
                )
            dataset_exists = False
            permissions = ["bigquery.datasets.create", "bigquery.jobs.create"]
        else:
            if not self.create_if_missing:
                return DestinationTestStepResult(status=Status.PASSED)
            dataset_exists = True
            permissions = ["bigquery.jobs.create"]

        granted = await asyncio.to_thread(self._test_iam_permissions, client.sync_client._credentials, permissions)
        if isinstance(granted, DestinationTestStepResult):
            if dataset_exists and granted.status == Status.SKIPPED:
                return DestinationTestStepResult(status=Status.PASSED)
            return granted

        missing = [permission for permission in permissions if permission not in granted]
        if missing and not dataset_exists:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Dataset '{self.dataset_id}' does not exist and the service account cannot create it. Missing permissions: {', '.join(missing)}. Grant the BigQuery Data Editor and BigQuery Job User roles on project '{self.project_id}', or create the dataset first.",
            )
        if missing:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"The service account is missing permissions: bigquery.jobs.create. Grant the BigQuery Job User role on project '{self.project_id}'.",
            )
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
        integration: GoogleCloudServiceAccountIntegration | None = None,
        service_account_info: ServiceAccountInfo | None = None,
        skip_if_dataset_missing: bool = False,
    ) -> None:
        super().__init__()
        self.dataset_id = dataset_id
        self.project_id = project_id
        self.table_id = table_id
        self.integration = integration
        self.service_account_info = service_account_info
        self.skip_if_dataset_missing = skip_if_dataset_missing

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.project_id is None
            or self.dataset_id is None
            or self.table_id is None
            or (self.service_account_info is None and self.integration is None)
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        client = get_client(self.project_id, self.integration, self.service_account_info)

        # This method should be called by `run()` which ensures this test step is configured
        # with non-`None` values.
        assert self.table_id is not None
        assert self.dataset_id is not None

        if self.skip_if_dataset_missing:
            # A missing dataset makes `create_table` fail with NotFound. The dataset step already
            # checked that the dataset can be created, and the tables are created inside it later.
            try:
                client.sync_client.get_dataset(f"{self.project_id}.{self.dataset_id}")
            except NotFound:
                return DestinationTestStepResult(
                    status=Status.SKIPPED,
                    message=f"Dataset '{self.dataset_id}' does not exist yet. Its tables are created with it.",
                )

        fully_qualified_name = f"{self.project_id}.{self.dataset_id}.{self.table_id}"
        table = bigquery.Table(fully_qualified_name, schema=[bigquery.SchemaField(name="event", field_type="STRING")])

        try:
            _ = client.sync_client.get_table(table)
        except NotFound:
            try:
                # Since permissions to create are not table specific, we can test creating
                # a table with a slightly different ID so that it is easier to clean up for the
                # user in case the delete call later on fails.
                fully_qualified_name = f"{fully_qualified_name}_test"

                table = bigquery.Table(
                    fully_qualified_name, schema=[bigquery.SchemaField(name="event", field_type="STRING")]
                )

                _ = client.sync_client.create_table(table, exists_ok=True)
            except BadRequest as err:
                return DestinationTestStepResult(
                    status=Status.FAILED,
                    message=f"A table could not be created in dataset '{self.dataset_id}': {err.errors[0]['message']}",
                )
            else:
                try:
                    client.sync_client.delete_table(table, not_found_ok=True)
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

    def __init__(self) -> None:
        self.project_id: str | None = None
        self.integration: GoogleCloudServiceAccountIntegration | None = None
        self.service_account_email: str | None = None
        self.dataset_id: str | None = None
        self.create_dataset_if_missing: bool = False
        self.table_id: str | None = None
        self.private_key: str | None = None
        self.private_key_id: str | None = None
        self.token_uri: str | None = None

    def configure(self, **kwargs):
        """Configure this test with necessary attributes."""
        self.project_id = kwargs.get("project_id", None)
        self.service_account_email = kwargs.get("service_account_email", None) or kwargs.get("client_email", None)
        self.dataset_id = kwargs.get("dataset_id", None)
        self.create_dataset_if_missing = bool(kwargs.get("create_dataset_if_missing", False))
        self.table_id = kwargs.get("table_id", None)

        self.private_key = kwargs.get("private_key", None)
        self.private_key_id = kwargs.get("private_key_id", None)
        self.token_uri = kwargs.get("token_uri", None)

        integration = kwargs.get("integration", None)
        if integration is not None:
            self.integration = GoogleCloudServiceAccountIntegration(integration)

    @property
    def service_account_info(self) -> ServiceAccountInfo | None:
        if (
            self.private_key is None
            or self.private_key_id is None
            or self.token_uri is None
            or self.service_account_email is None
        ):
            return None

        return {
            "private_key": self.private_key,
            "private_key_id": self.private_key_id,
            "token_uri": self.token_uri,
            "client_email": self.service_account_email,
        }

    @property
    def steps(self) -> collections.abc.Sequence[DestinationTestStep]:
        """Sequence of test steps that make up this destination test."""
        return [
            BigQueryImpersonateServiceAccountTestStep(project_id=self.project_id, integration=self.integration),
            BigQueryVerifyServiceAccountOwnershipTestStep(
                project_id=self.project_id,
                integration=self.integration,
                organization_id=str(self.integration.integration.team.organization_id) if self.integration else None,
            ),
            BigQueryProjectTestStep(
                project_id=self.project_id,
                integration=self.integration,
                service_account_info=self.service_account_info,
            ),
            BigQueryDatasetTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                integration=self.integration,
                service_account_info=self.service_account_info,
                create_if_missing=self.create_dataset_if_missing,
            ),
            BigQueryTableTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                table_id=self.table_id,
                integration=self.integration,
                service_account_info=self.service_account_info,
                skip_if_dataset_missing=self.create_dataset_if_missing,
            ),
        ]
