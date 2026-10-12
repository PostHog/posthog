import pytest
from unittest.mock import MagicMock, patch

import requests
import google.auth.transport.requests
from google.api_core.exceptions import NotFound

from products.batch_exports.backend.destination_tests.base import DestinationTestStepResult, Status
from products.batch_exports.backend.destination_tests.bigquery import (
    BigQueryDatasetTestStep,
    BigQueryDestinationTest,
    BigQueryTableTestStep,
    ServiceAccountInfo,
)

SERVICE_ACCOUNT_INFO: ServiceAccountInfo = {
    "private_key": "dummy-key",
    "private_key_id": "dummy-key-id",
    "token_uri": "https://example.com/token",
    "client_email": "service-account@example.com",
}
ORIGINAL_NOT_FOUND_MESSAGE = (
    "Dataset 'd' could not be found because it doesn't exist or we don't have permissions to use it"
)
API_DISABLED_MESSAGE = (
    "Could not check whether the service account can create datasets because the Cloud Resource Manager API "
    "is disabled for this project. Enable it, or create the dataset first."
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "create_if_missing,dataset_exists,status_code,response_text,granted,expected_status,message_parts",
    [
        pytest.param(False, False, 200, "", [], Status.FAILED, (ORIGINAL_NOT_FOUND_MESSAGE,), id="flag-off-missing"),
        pytest.param(False, True, 200, "", [], Status.PASSED, (), id="flag-off-exists"),
        pytest.param(True, True, 200, "", ["bigquery.jobs.create"], Status.PASSED, (), id="exists-jobs-granted"),
        pytest.param(
            True,
            True,
            200,
            "",
            [],
            Status.FAILED,
            ("bigquery.jobs.create", "BigQuery Job User"),
            id="exists-jobs-denied",
        ),
        pytest.param(
            True,
            False,
            200,
            "",
            ["bigquery.datasets.create", "bigquery.jobs.create"],
            Status.PASSED,
            (),
            id="missing-all-granted",
        ),
        pytest.param(
            True,
            False,
            200,
            "",
            ["bigquery.jobs.create"],
            Status.FAILED,
            ("bigquery.datasets.create", "BigQuery Data Editor"),
            id="missing-dataset-denied",
        ),
        pytest.param(
            True,
            False,
            200,
            "",
            ["bigquery.datasets.create"],
            Status.FAILED,
            ("bigquery.jobs.create", "BigQuery Job User"),
            id="missing-jobs-denied",
        ),
        pytest.param(
            True,
            False,
            200,
            "",
            [],
            Status.FAILED,
            ("bigquery.datasets.create, bigquery.jobs.create",),
            id="missing-all-denied",
        ),
        pytest.param(
            True, False, 403, "SERVICE_DISABLED", [], Status.SKIPPED, (API_DISABLED_MESSAGE,), id="missing-api-disabled"
        ),
        pytest.param(
            True,
            False,
            403,
            "API has not been used",
            [],
            Status.SKIPPED,
            (API_DISABLED_MESSAGE,),
            id="missing-api-unused",
        ),
        pytest.param(
            True,
            False,
            403,
            "API is disabled",
            [],
            Status.SKIPPED,
            (API_DISABLED_MESSAGE,),
            id="missing-api-disabled-text",
        ),
        pytest.param(True, True, 403, "SERVICE_DISABLED", [], Status.PASSED, (), id="exists-api-disabled"),
        pytest.param(
            True,
            False,
            403,
            "Permission denied",
            [],
            Status.FAILED,
            ("Could not check permissions on project 'p' (HTTP 403).",),
            id="missing-http-forbidden",
        ),
        pytest.param(
            True,
            False,
            500,
            "",
            [],
            Status.FAILED,
            ("Could not check permissions on project 'p' (HTTP 500).",),
            id="missing-http-error",
        ),
        pytest.param(
            True,
            True,
            500,
            "",
            [],
            Status.FAILED,
            ("Could not check permissions on project 'p' (HTTP 500).",),
            id="exists-http-error",
        ),
        pytest.param(True, True, 200, "", None, Status.FAILED, ("BigQuery Job User",), id="permissions-key-absent"),
    ],
)
async def test_bigquery_dataset_create_check(
    create_if_missing: bool,
    dataset_exists: bool,
    status_code: int,
    response_text: str,
    granted: list[str] | None,
    expected_status: Status,
    message_parts: tuple[str, ...],
) -> None:
    client = MagicMock()
    if dataset_exists:
        client.sync_client.get_dataset.return_value = MagicMock()
    else:
        client.sync_client.get_dataset.side_effect = NotFound("x")
    response = MagicMock(status_code=status_code, text=response_text)
    response.json.return_value = {} if granted is None else {"permissions": granted}

    step = BigQueryDatasetTestStep(
        project_id="p",
        dataset_id="d",
        service_account_info=SERVICE_ACCOUNT_INFO,
        create_if_missing=create_if_missing,
    )
    with (
        patch("products.batch_exports.backend.destination_tests.bigquery.get_client", return_value=client),
        patch.object(google.auth.transport.requests.AuthorizedSession, "post", return_value=response) as post,
    ):
        result = await step.run()

    assert isinstance(result, DestinationTestStepResult)
    assert result.status == expected_status
    if message_parts:
        assert result.message is not None
        for message_part in message_parts:
            assert message_part in result.message
    else:
        assert result.message is None

    if not create_if_missing:
        post.assert_not_called()
        if not dataset_exists:
            assert result.message == ORIGINAL_NOT_FOUND_MESSAGE
    else:
        permissions = (
            ["bigquery.jobs.create"] if dataset_exists else ["bigquery.datasets.create", "bigquery.jobs.create"]
        )
        post.assert_called_once_with(
            "https://cloudresourcemanager.googleapis.com/v1/projects/p:testIamPermissions",
            json={"permissions": permissions},
            timeout=30,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("dataset_exists", [False, True])
@pytest.mark.parametrize("error_type", [requests.exceptions.ConnectionError, requests.exceptions.Timeout])
async def test_bigquery_dataset_permission_request_failure(
    dataset_exists: bool, error_type: type[requests.exceptions.RequestException]
) -> None:
    client = MagicMock()
    if not dataset_exists:
        client.sync_client.get_dataset.side_effect = NotFound("x")
    step = BigQueryDatasetTestStep(
        project_id="p", dataset_id="d", service_account_info=SERVICE_ACCOUNT_INFO, create_if_missing=True
    )
    with (
        patch("products.batch_exports.backend.destination_tests.bigquery.get_client", return_value=client),
        patch.object(
            google.auth.transport.requests.AuthorizedSession, "post", side_effect=error_type("request failed")
        ) as post,
    ):
        result = await step.run()

    assert result == DestinationTestStepResult(
        status=Status.FAILED,
        message="Could not check permissions on project 'p' because the request failed.",
    )
    permissions = ["bigquery.jobs.create"] if dataset_exists else ["bigquery.datasets.create", "bigquery.jobs.create"]
    post.assert_called_once_with(
        "https://cloudresourcemanager.googleapis.com/v1/projects/p:testIamPermissions",
        json={"permissions": permissions},
        timeout=30,
    )


def test_bigquery_destination_create_dataset_configuration() -> None:
    destination = BigQueryDestinationTest()
    dataset_step = next(step for step in destination.steps if isinstance(step, BigQueryDatasetTestStep))
    assert dataset_step.create_if_missing is False

    destination.configure(create_dataset_if_missing=True)
    assert destination.create_dataset_if_missing
    dataset_step = next(step for step in destination.steps if isinstance(step, BigQueryDatasetTestStep))
    assert dataset_step.create_if_missing is True
    table_step = next(step for step in destination.steps if isinstance(step, BigQueryTableTestStep))
    assert table_step.skip_if_dataset_missing is True

    destination.configure()
    dataset_step = next(step for step in destination.steps if isinstance(step, BigQueryDatasetTestStep))
    assert dataset_step.create_if_missing is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skip_if_dataset_missing,dataset_exists,expected_status,create_table_called",
    [
        pytest.param(True, False, Status.SKIPPED, False, id="skip-missing-dataset"),
        pytest.param(True, True, Status.PASSED, True, id="skip-flag-dataset-exists"),
        pytest.param(False, True, Status.PASSED, True, id="flag-off"),
    ],
)
async def test_bigquery_table_step_with_missing_dataset(
    skip_if_dataset_missing: bool, dataset_exists: bool, expected_status: Status, create_table_called: bool
) -> None:
    client = MagicMock()
    if dataset_exists:
        client.sync_client.get_dataset.return_value = MagicMock()
    else:
        client.sync_client.get_dataset.side_effect = NotFound("x")
    client.sync_client.get_table.side_effect = NotFound("x")

    step = BigQueryTableTestStep(
        project_id="p",
        dataset_id="d",
        table_id="t",
        service_account_info=SERVICE_ACCOUNT_INFO,
        skip_if_dataset_missing=skip_if_dataset_missing,
    )
    with patch("products.batch_exports.backend.destination_tests.bigquery.get_client", return_value=client):
        result = await step.run()

    assert result.status == expected_status
    assert client.sync_client.create_table.called is create_table_called
