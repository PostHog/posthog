import json
import typing

import pytest
from unittest.mock import MagicMock, patch

import requests
import google.auth.exceptions
from google.api_core.exceptions import NotFound

from posthog.models.integration import GoogleCloudServiceAccountIntegration

from products.batch_exports.backend.destination_tests import get_destination_test
from products.batch_exports.backend.destination_tests.base import DestinationTestStepResult, Status
from products.batch_exports.backend.destination_tests.bigquery import (
    BigQueryDatasetTestStep,
    BigQueryDestinationTest,
    BigQueryImpersonateServiceAccountTestStep,
    BigQueryProjectTestStep,
    BigQueryTableTestStep,
    BigQueryVerifyServiceAccountOwnershipTestStep,
    ServiceAccountInfo,
)
from products.batch_exports.backend.destination_tests.bigquery_create_dataset import (
    BigQueryCreateDatasetDestinationTest,
    BigQueryDatasetExistsOrCreatableTestStep,
    BigQueryProjectPermissionsTestStep,
    BigQueryTableIfDatasetExistsTestStep,
    get_iam_check_credentials,
)
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import impersonate_service_account

MODULE = "products.batch_exports.backend.destination_tests.bigquery_create_dataset"
BIGQUERY_MODULE = "products.batch_exports.backend.destination_tests.bigquery"
BATCH_EXPORT_MODULE = "products.batch_exports.backend.temporal.destinations.bigquery_batch_export"

READ_ONLY_SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"
JOBS = "bigquery.jobs.create"
DATASETS = "bigquery.datasets.create"

SERVICE_ACCOUNT_INFO: ServiceAccountInfo = {
    "private_key": "dummy-key",
    "private_key_id": "dummy-key-id",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_email": "service-account@example.com",
}


def make_response(status_code: int, body: object) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def make_error(status: str, message: str, reason: str | None = None) -> dict[str, typing.Any]:
    details = []
    if reason is not None:
        details.append(
            {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "domain": "googleapis.com"}
        )
    return {"error": {"code": 403, "message": message, "status": status, "details": details}}


def make_client(dataset_exists: bool) -> MagicMock:
    client = MagicMock()
    if not dataset_exists:
        client.sync_client.get_dataset.side_effect = NotFound("missing")
    return client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dataset_exists,post_result,expected_status,expected_message_parts,unexpected_message_parts",
    [
        pytest.param(True, make_response(200, {"permissions": [JOBS]}), Status.PASSED, (), (), id="exists-granted"),
        pytest.param(
            True,
            make_response(200, {}),
            Status.FAILED,
            (JOBS, "BigQuery Job User"),
            (DATASETS, "BigQuery Data Editor"),
            id="exists-jobs-denied",
        ),
        pytest.param(
            False,
            make_response(200, {"permissions": [DATASETS, JOBS]}),
            Status.PASSED,
            (),
            (),
            id="missing-granted",
        ),
        pytest.param(
            False,
            make_response(200, {"permissions": [JOBS]}),
            Status.FAILED,
            (DATASETS, "BigQuery Data Editor", "create the dataset first"),
            ("BigQuery Job User",),
            id="missing-datasets-denied",
        ),
        pytest.param(
            False,
            make_response(200, {}),
            Status.FAILED,
            (f"{DATASETS}, {JOBS}", "BigQuery Data Editor", "BigQuery Job User"),
            (),
            id="missing-all-denied",
        ),
        pytest.param(
            False,
            make_response(403, make_error("PERMISSION_DENIED", "API has not been used", reason="SERVICE_DISABLED")),
            Status.SKIPPED,
            ("Cloud Resource Manager API is disabled",),
            (),
            id="service-disabled",
        ),
        pytest.param(
            True,
            make_response(403, make_error("PERMISSION_DENIED", "Billing is disabled for this project")),
            Status.FAILED,
            ("HTTP 403",),
            ("Cloud Resource Manager",),
            id="billing-disabled-is-not-service-disabled",
        ),
        pytest.param(
            True,
            make_response(403, make_error("PERMISSION_DENIED", "Access denied", reason="BILLING_DISABLED")),
            Status.FAILED,
            ("HTTP 403",),
            ("Cloud Resource Manager",),
            id="other-error-reason",
        ),
        pytest.param(True, make_response(500, "oops"), Status.FAILED, ("HTTP 500", "try again"), (), id="server-error"),
        pytest.param(
            True,
            requests.exceptions.ConnectionError("down"),
            Status.FAILED,
            ("request to Google Cloud failed", "try again"),
            (),
            id="connection-error",
        ),
        pytest.param(
            False,
            requests.exceptions.Timeout("slow"),
            Status.FAILED,
            ("request to Google Cloud failed", "try again"),
            (),
            id="timeout",
        ),
        pytest.param(
            True,
            google.auth.exceptions.RefreshError("no token"),
            Status.FAILED,
            ("authentication failed", "Review the service account credentials"),
            (),
            id="credentials-refresh-error",
        ),
    ],
)
async def test_project_permissions_step(
    dataset_exists: bool,
    post_result: requests.Response | Exception,
    expected_status: Status,
    expected_message_parts: tuple[str, ...],
    unexpected_message_parts: tuple[str, ...],
) -> None:
    step = BigQueryProjectPermissionsTestStep(
        project_id="my-project", dataset_id="d", service_account_info=SERVICE_ACCOUNT_INFO
    )
    post_kwargs = {"side_effect": post_result} if isinstance(post_result, Exception) else {"return_value": post_result}

    with (
        patch(f"{MODULE}.get_client", return_value=make_client(dataset_exists)),
        patch(f"{MODULE}.service_account.Credentials.from_service_account_info", return_value=MagicMock()),
        patch(f"{MODULE}.google.auth.transport.requests.AuthorizedSession.post", **post_kwargs) as post,
    ):
        result = await step.run()

    assert result.status == expected_status, result.message
    for part in expected_message_parts:
        assert result.message is not None and part in result.message
    for part in unexpected_message_parts:
        assert result.message is None or part not in result.message
    if expected_status == Status.PASSED:
        assert result.message is None

    post.assert_called_once_with(
        "https://cloudresourcemanager.googleapis.com/v1/projects/my-project:testIamPermissions",
        json={"permissions": [JOBS] if dataset_exists else [DATASETS, JOBS]},
        timeout=30,
    )


@pytest.mark.asyncio
async def test_project_permissions_step_quotes_project_id() -> None:
    step = BigQueryProjectPermissionsTestStep(
        project_id="evil/../projects/other?x=1", dataset_id="d", service_account_info=SERVICE_ACCOUNT_INFO
    )

    with (
        patch(f"{MODULE}.get_client", return_value=make_client(True)),
        patch(f"{MODULE}.service_account.Credentials.from_service_account_info", return_value=MagicMock()),
        patch(
            f"{MODULE}.google.auth.transport.requests.AuthorizedSession.post",
            return_value=make_response(200, {"permissions": [JOBS]}),
        ) as post,
    ):
        await step.run()

    assert post.call_args.args[0] == (
        "https://cloudresourcemanager.googleapis.com/v1/projects/evil%2F..%2Fprojects%2Fother%3Fx%3D1:testIamPermissions"
    )


def make_integration(has_key: bool) -> MagicMock:
    integration = MagicMock(spec=GoogleCloudServiceAccountIntegration)
    integration.has_key.return_value = has_key
    integration.service_account_email = "their-sa@example.iam.gserviceaccount.com"
    integration.service_account_info = {**SERVICE_ACCOUNT_INFO, "project_id": "my-project"}
    return integration


@pytest.mark.parametrize(
    "integration,service_account_info",
    [
        pytest.param(make_integration(has_key=True), None, id="key-file-integration"),
        pytest.param(None, SERVICE_ACCOUNT_INFO, id="service-account-inputs"),
    ],
)
def test_iam_check_credentials_from_key_use_read_only_scope(
    integration: MagicMock | None, service_account_info: ServiceAccountInfo | None
) -> None:
    with patch(f"{MODULE}.service_account.Credentials.from_service_account_info") as from_info:
        get_iam_check_credentials(integration, service_account_info)

    assert from_info.call_args.kwargs["scopes"] == [READ_ONLY_SCOPE]


@pytest.mark.parametrize(
    "build_credentials,expected_scopes",
    [
        pytest.param(
            lambda integration: get_iam_check_credentials(integration, None),
            [READ_ONLY_SCOPE],
            id="iam-check",
        ),
        pytest.param(
            impersonate_service_account,
            ["https://www.googleapis.com/auth/bigquery"],
            id="default-bigquery-scope-unchanged",
        ),
    ],
)
def test_impersonated_credentials_scopes(
    build_credentials: typing.Callable[[MagicMock], object], expected_scopes: list[str]
) -> None:
    integration = make_integration(has_key=False)

    with (
        patch(f"{BATCH_EXPORT_MODULE}.get_our_google_cloud_credentials", return_value=MagicMock()),
        patch(f"{BATCH_EXPORT_MODULE}.google.auth.impersonated_credentials.Credentials") as impersonated,
    ):
        build_credentials(integration)

    assert impersonated.call_args.kwargs["target_scopes"] == expected_scopes
    assert impersonated.call_args.kwargs["target_principal"] == integration.service_account_email


ORIGINAL_DATASET_MISSING_MESSAGE = (
    "Dataset 'd' could not be found because it doesn't exist or we don't have permissions to use it"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "step_class,dataset_exists,expected_status,expected_message",
    [
        pytest.param(BigQueryDatasetTestStep, True, Status.PASSED, None, id="original-exists"),
        pytest.param(
            BigQueryDatasetTestStep, False, Status.FAILED, ORIGINAL_DATASET_MISSING_MESSAGE, id="original-missing"
        ),
        pytest.param(BigQueryDatasetExistsOrCreatableTestStep, True, Status.PASSED, None, id="creatable-exists"),
        pytest.param(
            BigQueryDatasetExistsOrCreatableTestStep,
            False,
            Status.SKIPPED,
            "Dataset 'd' does not exist yet. It is created when data is first written.",
            id="creatable-missing",
        ),
    ],
)
async def test_dataset_steps(
    step_class: type[BigQueryDatasetTestStep],
    dataset_exists: bool,
    expected_status: Status,
    expected_message: str | None,
) -> None:
    client = make_client(dataset_exists)
    step = step_class(project_id="p", dataset_id="d", service_account_info=SERVICE_ACCOUNT_INFO)

    with (
        patch(f"{MODULE}.get_client", return_value=client),
        patch(f"{BIGQUERY_MODULE}.get_client", return_value=client),
    ):
        result = await step.run()

    assert result == DestinationTestStepResult(status=expected_status, message=expected_message)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dataset_exists,expected_status,create_table_called",
    [
        pytest.param(True, Status.PASSED, True, id="dataset-exists"),
        pytest.param(False, Status.SKIPPED, False, id="dataset-missing"),
    ],
)
async def test_table_step_runs_only_when_dataset_exists(
    dataset_exists: bool, expected_status: Status, create_table_called: bool
) -> None:
    client = make_client(dataset_exists)
    client.sync_client.get_table.side_effect = NotFound("missing")
    step = BigQueryTableIfDatasetExistsTestStep(
        project_id="p", dataset_id="d", table_id="t", service_account_info=SERVICE_ACCOUNT_INFO
    )

    with (
        patch(f"{MODULE}.get_client", return_value=client),
        patch(f"{BIGQUERY_MODULE}.get_client", return_value=client),
    ):
        result = await step.run()

    assert result.status == expected_status
    assert client.sync_client.create_table.called is create_table_called


@pytest.mark.parametrize(
    "destination_type,expected_class,expected_step_classes",
    [
        pytest.param(
            "BigQuery",
            BigQueryDestinationTest,
            [
                BigQueryImpersonateServiceAccountTestStep,
                BigQueryVerifyServiceAccountOwnershipTestStep,
                BigQueryProjectTestStep,
                BigQueryDatasetTestStep,
                BigQueryTableTestStep,
            ],
            id="batch-exports-bigquery",
        ),
        pytest.param(
            "BigQueryCreateDataset",
            BigQueryCreateDatasetDestinationTest,
            [
                BigQueryImpersonateServiceAccountTestStep,
                BigQueryVerifyServiceAccountOwnershipTestStep,
                BigQueryProjectTestStep,
                BigQueryProjectPermissionsTestStep,
                BigQueryDatasetExistsOrCreatableTestStep,
                BigQueryTableIfDatasetExistsTestStep,
            ],
            id="create-dataset",
        ),
    ],
)
def test_destination_test_registry(
    destination_type: str, expected_class: type[BigQueryDestinationTest], expected_step_classes: list[type]
) -> None:
    destination_test = get_destination_test(destination_type)
    destination_test.configure(project_id="p", dataset_id="d", table_id="t", create_dataset_if_missing=True)

    assert type(destination_test) is expected_class
    assert [type(step) for step in destination_test.steps] == expected_step_classes
