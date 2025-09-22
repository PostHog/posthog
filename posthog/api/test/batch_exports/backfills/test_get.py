import datetime as dt

import pytest

from django.test.client import Client as HttpClient

from rest_framework import status

from posthog.api.test.batch_exports.fixtures import create_backfill, create_batch_export, create_destination, create_run
from posthog.api.test.batch_exports.operations import get_batch_export_backfill_ok
from posthog.batch_exports.models import BatchExportBackfill, BatchExportRun

pytestmark = [
    pytest.mark.django_db,
]

TEST_TIME = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)


@pytest.mark.parametrize(
    "status, start_at, end_at, completed_runs, expected_progress",
    [
        # a completed backfill with 1 run but no runs in the DB with backfill_id (this wasn't populated in the past, so
        # useful to test backwards compatibility)
        (
            BatchExportBackfill.Status.COMPLETED,
            dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
            0,
            {
                "total_runs": 1,
                "finished_runs": 1,
                "progress": 1,
            },
        ),
        (
            BatchExportBackfill.Status.COMPLETED,
            dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
            1,
            {
                "total_runs": 1,
                "finished_runs": 1,
                "progress": 1,
            },
        ),
        # backfill failed so progress is not meaningful
        (
            BatchExportBackfill.Status.FAILED,
            dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
            0,
            None,
        ),
        # backfill was cancelled so progress is not meaningful
        (
            BatchExportBackfill.Status.CANCELLED,
            dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 1, 2, 0, 0, tzinfo=dt.UTC),
            1,
            None,
        ),
        # backfill is half way through so progress is 0.5
        (
            BatchExportBackfill.Status.RUNNING,
            dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 1, 2, 0, 0, tzinfo=dt.UTC),
            1,
            {
                "total_runs": 2,
                "finished_runs": 1,
                "progress": 0.5,
            },
        ),
        (
            BatchExportBackfill.Status.STARTING,
            dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2021, 1, 1, 2, 0, 0, tzinfo=dt.UTC),
            0,
            {
                "total_runs": 2,
                "finished_runs": 0,
                "progress": 0,
            },
        ),
        # backfill is just a single run from earliest date so not possible to calculate progress
        (BatchExportBackfill.Status.RUNNING, None, dt.datetime(2021, 1, 1, 2, 0, 0, tzinfo=dt.UTC), 0, None),
        # backfill is a single run from earliest date which has completed
        (
            BatchExportBackfill.Status.COMPLETED,
            None,
            dt.datetime(2021, 1, 1, 2, 0, 0, tzinfo=dt.UTC),
            1,
            {
                "total_runs": 1,
                "finished_runs": 1,
                "progress": 1,
            },
        ),
        # backfill is a continuous hourly backfill up to the current time. It started 100 minutes ago so we expect there
        # to be 2 runs, 1 of which is completed, so progress is 0.5
        (
            BatchExportBackfill.Status.RUNNING,
            TEST_TIME - dt.timedelta(minutes=100),
            None,
            1,
            {
                "total_runs": 2,
                "finished_runs": 1,
                "progress": 0.5,
            },
        ),
        # backfill is a continuous hourly backfill up to the current time. It started 119 minutes ago and has status completed
        # so we expect there to be 2 runs (we round up) and we expect progress to be 1
        # (we set completed runs to 0 to simulate legacy runs which didn't have backfill_id populated)
        (
            BatchExportBackfill.Status.COMPLETED,
            TEST_TIME - dt.timedelta(minutes=119),
            None,
            0,
            {
                "total_runs": 2,
                "finished_runs": 2,
                "progress": 1,
            },
        ),
    ],
)
def test_can_get_backfills_for_your_organizations(
    client: HttpClient, organization, team, user, status, start_at, end_at, completed_runs, expected_progress
):
    """Test that we can get backfills for your own organization.

    We parametrize this test so we can test the behaviour of the total_runs, finished_runs and progress fields.
    """
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    finished_at = TEST_TIME if status == BatchExportBackfill.Status.COMPLETED else None
    backfill = create_backfill(
        team=team,
        batch_export=batch_export,
        start_at=start_at,
        end_at=end_at,
        status=status,
        finished_at=finished_at,
    )
    for _ in range(completed_runs):
        create_run(
            batch_export=batch_export,
            status=BatchExportRun.Status.COMPLETED,
            data_interval_start=start_at if start_at else None,
            data_interval_end=end_at if end_at else TEST_TIME,
            backfill=backfill,
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
        "status": status.value,
        "finished_at": finished_at.strftime("%Y-%m-%dT%H:%M:%SZ") if finished_at else None,
        "progress": expected_progress,
    }


def test_cannot_get_backfills_for_other_organizations(client: HttpClient, organization, team):
    from posthog.api.test.batch_exports.fixtures import create_organization
    from posthog.api.test.test_user import create_user

    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.RUNNING,
        None,
    )

    another_organization = create_organization("Another Org")
    another_user = create_user("another-test@user.com", "Another Test User", another_organization)

    client.force_login(another_user)
    response = client.get(f"/api/projects/{team.pk}/batch_exports/{batch_export.id}/backfills/{backfill.id}")
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()


def test_backfills_are_partitioned_by_team(client: HttpClient, organization, team, user):
    """Test that backfills can only be accessed through their associated team."""
    from posthog.api.test.test_team import create_team

    another_team = create_team(organization)
    destination = create_destination()

    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        dt.datetime(2023, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2023, 1, 2, 0, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.RUNNING,
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
        BatchExportBackfill.Status.RUNNING,
        None,
    )

    response = client.get(
        f"/api/projects/{team.pk}/batch_exports/{another_batch_export.id}/backfills/{another_backfill.id}"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.json()
