import typing
import asyncio
import urllib.parse
import collections.abc

import requests
import google.auth.exceptions
import google.auth.transport.requests
from google.api_core.exceptions import NotFound
from google.oauth2 import service_account

from posthog.models.integration import GoogleCloudServiceAccountIntegration
from posthog.models.integration.google_cloud import require_google_token_uri

from products.batch_exports.backend.destination_tests.base import DestinationTestStep, DestinationTestStepResult, Status
from products.batch_exports.backend.destination_tests.bigquery import (
    BigQueryDatasetTestStep,
    BigQueryDestinationTest,
    BigQueryImpersonateServiceAccountTestStep,
    BigQueryProjectTestStep,
    BigQueryTableTestStep,
    BigQueryVerifyServiceAccountOwnershipTestStep,
    ServiceAccountInfo,
    get_client,
)
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import impersonate_service_account

if typing.TYPE_CHECKING:
    from google.auth.credentials import Credentials

# Impersonated BigQuery credentials only carry the bigquery scope, which Cloud Resource Manager rejects.
IAM_CHECK_SCOPES = ("https://www.googleapis.com/auth/cloud-platform.read-only",)
IAM_CHECK_TIMEOUT_SECONDS = 30

JOBS_CREATE_PERMISSION = "bigquery.jobs.create"
DATASETS_CREATE_PERMISSION = "bigquery.datasets.create"


def get_iam_check_credentials(
    integration: GoogleCloudServiceAccountIntegration | None,
    service_account_info: ServiceAccountInfo | None,
) -> "Credentials":
    """Get credentials for the service account with a scope that allows `projects.testIamPermissions`."""
    if integration is not None:
        if integration.has_key():
            return service_account.Credentials.from_service_account_info(
                integration.service_account_info, scopes=list(IAM_CHECK_SCOPES)
            )
        return impersonate_service_account(integration, scopes=IAM_CHECK_SCOPES)

    if service_account_info is not None:
        return service_account.Credentials.from_service_account_info(
            {**service_account_info, "token_uri": require_google_token_uri(service_account_info["token_uri"])},
            scopes=list(IAM_CHECK_SCOPES),
        )

    raise ValueError("Either integration or service account information must be defined")


def is_service_disabled_error(response: requests.Response) -> bool:
    """Return whether an error response says that the API is disabled in the project.

    Google reports this as a `PERMISSION_DENIED` error with a `google.rpc.ErrorInfo` detail whose
    reason is `SERVICE_DISABLED`. Other 403 errors, such as a disabled billing account, also say
    "disabled" in the message, so only the structured reason is reliable.
    """
    try:
        body = response.json()
    except ValueError:
        return False

    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict) or error.get("status") != "PERMISSION_DENIED":
        return False

    details = error.get("details")
    if not isinstance(details, list):
        return False

    return any(
        isinstance(detail, dict)
        and detail.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo"
        and detail.get("reason") == "SERVICE_DISABLED"
        for detail in details
    )


def dataset_exists(
    project_id: str | None,
    dataset_id: str,
    integration: GoogleCloudServiceAccountIntegration | None,
    service_account_info: ServiceAccountInfo | None,
) -> bool:
    client = get_client(project_id, integration, service_account_info)
    try:
        _ = client.sync_client.get_dataset(dataset_id)
    except NotFound:
        return False
    return True


class BigQueryProjectPermissionsTestStep(DestinationTestStep):
    """Test whether a service account has the project permissions to create a dataset and run jobs.

    The service account always needs `bigquery.jobs.create` to run load, copy and merge jobs. It
    also needs `bigquery.datasets.create` on the project when the dataset does not exist yet.

    Attributes:
        project_id: ID of the BigQuery project we are checking.
        dataset_id: ID of the dataset that is created if it does not exist.
        integration: Integration with service account configuration.
        service_account_info: Service account credentials used when there is no integration.
    """

    name = "Verify BigQuery project permissions"
    description = (
        "Ensure the service account can run BigQuery jobs in the configured project, "
        "and can create the configured dataset if it does not exist."
    )

    def __init__(
        self,
        project_id: str | None = None,
        dataset_id: str | None = None,
        integration: GoogleCloudServiceAccountIntegration | None = None,
        service_account_info: ServiceAccountInfo | None = None,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.integration = integration
        self.service_account_info = service_account_info

    def _is_configured(self) -> bool:
        """Ensure required configuration parameters are set."""
        if (
            self.project_id is None
            or self.dataset_id is None
            or (self.service_account_info is None and self.integration is None)
        ):
            return False
        return True

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        return await asyncio.to_thread(self._check_permissions)

    def _check_permissions(self) -> DestinationTestStepResult:
        # This method should be called by `run()` which ensures this test step is configured
        # with non-`None` values.
        assert self.project_id is not None
        assert self.dataset_id is not None

        if dataset_exists(self.project_id, self.dataset_id, self.integration, self.service_account_info):
            required = [JOBS_CREATE_PERMISSION]
        else:
            required = [DATASETS_CREATE_PERMISSION, JOBS_CREATE_PERMISSION]

        credentials = get_iam_check_credentials(self.integration, self.service_account_info)
        url = (
            "https://cloudresourcemanager.googleapis.com/v1/projects/"
            f"{urllib.parse.quote(self.project_id, safe='')}:testIamPermissions"
        )

        try:
            with google.auth.transport.requests.AuthorizedSession(credentials) as session:
                response = session.post(url, json={"permissions": required}, timeout=IAM_CHECK_TIMEOUT_SECONDS)
        except google.auth.exceptions.GoogleAuthError:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Could not check permissions on project '{self.project_id}' because authentication failed. Review the service account credentials and try again.",
            )
        except requests.exceptions.RequestException:
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Could not check permissions on project '{self.project_id}' because the request to Google Cloud failed. This is usually temporary, so try again.",
            )

        if response.status_code != 200:
            if is_service_disabled_error(response):
                return DestinationTestStepResult(
                    status=Status.SKIPPED,
                    message=f"Could not check permissions because the Cloud Resource Manager API is disabled in project '{self.project_id}'. Enable the API to run this check.",
                )
            if response.status_code == 429 or response.status_code >= 500:
                advice = "This is usually temporary, so try again."
            else:
                advice = "Review the service account credentials and its access to the project, then try again."
            return DestinationTestStepResult(
                status=Status.FAILED,
                message=f"Could not check permissions on project '{self.project_id}' (HTTP {response.status_code}). {advice}",
            )

        granted = set(response.json().get("permissions", []))
        missing = [permission for permission in required if permission not in granted]
        if not missing:
            return DestinationTestStepResult(status=Status.PASSED)

        message = f"The service account is missing permissions on project '{self.project_id}': {', '.join(missing)}."
        if DATASETS_CREATE_PERMISSION in missing:
            message += f" Dataset '{self.dataset_id}' does not exist, so grant the BigQuery Data Editor role on the project, or create the dataset first."
        if JOBS_CREATE_PERMISSION in missing:
            message += " Grant the BigQuery Job User role on the project."

        return DestinationTestStepResult(status=Status.FAILED, message=message)


class BigQueryDatasetExistsOrCreatableTestStep(BigQueryDatasetTestStep):
    """Test whether a BigQuery dataset exists, and skip when it does not exist yet.

    A missing dataset is not a failure here, because the dataset is created when data is first
    written. `BigQueryProjectPermissionsTestStep` checks that the service account can create it.
    """

    description = "Ensure the configured BigQuery dataset exists and that we have the required permissions to access it. A dataset that does not exist yet is created when data is first written."

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        assert self.dataset_id is not None

        if dataset_exists(self.project_id, self.dataset_id, self.integration, self.service_account_info):
            return DestinationTestStepResult(status=Status.PASSED)

        return DestinationTestStepResult(
            status=Status.SKIPPED,
            message=f"Dataset '{self.dataset_id}' does not exist yet. It is created when data is first written.",
        )


class BigQueryTableIfDatasetExistsTestStep(BigQueryTableTestStep):
    """Run the table test only when the dataset exists.

    Creating a test table in a missing dataset always fails, and the tables are created together
    with the dataset when data is first written.
    """

    async def _run_step(self) -> DestinationTestStepResult:
        """Run this test step."""
        assert self.dataset_id is not None

        if not dataset_exists(self.project_id, self.dataset_id, self.integration, self.service_account_info):
            return DestinationTestStepResult(
                status=Status.SKIPPED,
                message=f"Dataset '{self.dataset_id}' does not exist yet, so its tables cannot be checked. They are created with the dataset.",
            )

        return await super()._run_step()


class BigQueryCreateDatasetDestinationTest(BigQueryDestinationTest):
    """A `DestinationTest` for a BigQuery destination that creates its dataset when it is missing.

    Batch exports require the dataset to exist, so they use `BigQueryDestinationTest`. This test
    is for destinations that create the dataset and run their own jobs. It requires the Cloud
    Resource Manager API to check project permissions.
    """

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
            BigQueryProjectPermissionsTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                integration=self.integration,
                service_account_info=self.service_account_info,
            ),
            BigQueryDatasetExistsOrCreatableTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                integration=self.integration,
                service_account_info=self.service_account_info,
            ),
            BigQueryTableIfDatasetExistsTestStep(
                project_id=self.project_id,
                dataset_id=self.dataset_id,
                table_id=self.table_id,
                integration=self.integration,
                service_account_info=self.service_account_info,
            ),
        ]
