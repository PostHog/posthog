import datetime as dt

import pytest
from django.test.client import Client as HttpClient
from rest_framework import status

from posthog.api.test.batch_exports.fixtures import (
    create_backfill,
    create_batch_export,
    create_destination,
    create_organization,
)
from posthog.api.test.batch_exports.operations import get_batch_export_backfill_ok
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

pytestmark = [
    pytest.mark.django_db,
]


@pytest.mark.parametrize(
    "start_at, end_at, expected_total_runs",
    [
        (dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC), dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC), 1),
        (dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC), dt.datetime(2021, 1, 2, 0, 0, 0, tzinfo=dt.UTC), 24),
        (None, dt.datetime(2021, 1, 2, 0, 0, 0, tzinfo=dt.UTC), None),
        (dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC), None, None),
    ],
)
def test_can_get_backfills_for_your_organizations(client: HttpClient, start_at, end_at, expected_total_runs):
    """Test that we can get backfills for your own organization.

    We parametrize this test so we can test the behaviour of the total_runs field.
    """
    organization = create_organization("Test Org")
    team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        start_at,
        end_at,
        "COMPLETED",
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )

    client.force_login(user)

    backfill_data = get_batch_export_backfill_ok(client, team.pk, batch_export.id, backfill.id)

    # as long as the created_at and last_updated_at are strings, we don't care about their exact values
    created_at = backfill_data.pop("created_at")
    last_updated_at = backfill_data.pop("last_updated_at")
    assert isinstance(created_at, str)
    assert isinstance(last_updated_at, str)

    assert backfill_data == {
        "id": str(backfill.id),
        "batch_export": str(batch_export.id),
        "team": team.pk,
        "start_at": start_at.strftime("%Y-%m-%dT%H:%M:%SZ") if start_at else None,
        "end_at": end_at.strftime("%Y-%m-%dT%H:%M:%SZ") if end_at else None,
        "status": "COMPLETED",
        "finished_at": "2025-01-01T01:00:00Z",
        "total_runs": expected_total_runs,
    }


def test_cannot_get_backfills_for_other_organizations(client: HttpClient):
    organization = create_organization("Test Org")
    team = create_team(organization)
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
        "RUNNING",
        None,
    )

    another_organization = create_organization("Another Org")
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)

    client.force_login(another_user)
    response = client.get(f"/api/projects/{team.pk}/batch_exports/{batch_export.id}/backfills/{backfill.id}")
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_backfills_are_partitioned_by_team(client: HttpClient):
    """Test that backfills can only be accessed through their associated team."""
    organization = create_organization("Test Org")
    team = create_team(organization)
    another_team = create_team(organization)
    user = create_user("test@user.com", "Test User", organization)
    destination = create_destination()

    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
        "RUNNING",
        None,
    )

    client.force_login(user)

    response = client.get(f"/api/projects/{another_team.pk}/batch_exports/{batch_export.id}/backfills/{backfill.id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()

    # And switch the teams around for good measure
    another_batch_export = create_batch_export(another_team, destination)
    another_backfill = create_backfill(
        another_team,
        another_batch_export,
        dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
        "RUNNING",
        None,
    )

    response = client.get(
        f"/api/projects/{team.pk}/batch_exports/{another_batch_export.id}/backfills/{another_backfill.id}"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
