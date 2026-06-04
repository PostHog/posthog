import datetime as dt

import pytest

from django.test.client import Client as HttpClient

from rest_framework import status
from temporalio.client import ScheduleActionStartWorkflow

from posthog.models.integration import Integration

from products.batch_exports.backend.tests.api.conftest import describe_schedule
from products.batch_exports.backend.tests.api.operations import create_batch_export

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("temporal_worker", "cleanup"),
]


@pytest.fixture
def databricks_integration(team, user):
    """Create a Databricks integration."""
    return Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.DATABRICKS,
        integration_id="my-server-hostname",
        config={"server_hostname": "my-server-hostname"},
        sensitive_config={"client_id": "my-client-id", "client_secret": "my-client-secret"},
        created_by=user,
    )


def test_creating_databricks_batch_export_using_integration(
    client: HttpClient, temporal, organization, team, user, databricks_integration
):
    """Test that we can create a Databricks batch export using an integration.

    Using integrations is the preferred way to handle credentials for batch exports going forward.
    """

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": databricks_integration.id,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    data = response.json()
    assert data["destination"] == destination_data

    schedule = describe_schedule(temporal, data["id"])
    intervals = schedule.schedule.spec.intervals

    assert len(intervals) == 1
    assert schedule.schedule.spec.intervals[0].every == dt.timedelta(hours=1)
    assert isinstance(schedule.schedule.action, ScheduleActionStartWorkflow)
    assert schedule.schedule.action.workflow == "databricks-export"


def test_creating_databricks_batch_export_fails_if_integration_is_missing(
    client: HttpClient, temporal, organization, team, user
):
    """Test that creating a Databricks batch export fails if the integration is missing.

    Using integrations is the preferred way to handle credentials for batch exports going forward.
    """

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    assert response.json() == {
        "type": "validation_error",
        "code": "invalid_input",
        "detail": "Integration is required for Databricks batch exports",
        "attr": "destination",
    }


def test_creating_databricks_batch_export_fails_if_integration_is_invalid(
    client: HttpClient, temporal, organization, team, user
):
    """Test that creating a Databricks batch export fails if the integration is invalid.

    Using integrations is the preferred way to handle credentials for batch exports going forward.

    In this case, the integration is missing the client_secret. In theory, this shouldn't happen, as we validate the
    integration when creating it via the API.
    """

    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.DATABRICKS,
        integration_id="my-server-hostname",
        config={"server_hostname": "my-server-hostname"},
        sensitive_config={"client_id": "my-client-id"},
        created_by=user,
    )

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": integration.pk,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Databricks integration is not valid: 'client_secret' missing"


def test_creating_databricks_batch_export_fails_if_integration_does_not_exist(
    client: HttpClient,
    temporal,
    organization,
    team,
    user,
):
    """Test that creating a Databricks batch export fails if the integration does not exist in the database.

    Using integrations is the preferred way to handle credentials for batch exports going forward.
    """

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": 999,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    assert response.json() == {
        "type": "validation_error",
        "code": "does_not_exist",
        "detail": 'Invalid pk "999" - object does not exist.',
        "attr": "destination__integration",
    }


def test_creating_databricks_batch_export_fails_if_integration_is_not_the_correct_type(
    client: HttpClient, temporal, organization, team, user
):
    """Test that creating a Databricks batch export fails if the integration is not the correct type.

    Using integrations is the preferred way to handle credentials for batch exports going forward.

    In this case, the integration is not a Databricks integration.
    """

    integration = Integration.objects.create(
        team=team,
        kind=Integration.IntegrationKind.SLACK,
        integration_id="my-server-hostname",
        config={"server_hostname": "my-server-hostname"},
        sensitive_config={"client_id": "my-client-id"},
        created_by=user,
    )

    destination_data = {
        "type": "Databricks",
        "config": {
            "http_path": "my-http-path",
            "catalog": "my-catalog",
            "schema": "my-schema",
            "table_name": "my-table-name",
        },
        "integration": integration.pk,
    }

    batch_export_data = {
        "name": "my-databricks-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    client.force_login(user)
    response = create_batch_export(
        client,
        team.pk,
        batch_export_data,
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
    assert response.json()["detail"] == "Integration is not a Databricks integration."
