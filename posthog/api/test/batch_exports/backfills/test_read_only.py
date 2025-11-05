import datetime as dt

import pytest

from django.test.client import Client as TestClient

from rest_framework import status

from posthog.api.test.batch_exports.fixtures import create_backfill, create_batch_export, create_destination
from posthog.batch_exports.models import BatchExportBackfill

pytestmark = [pytest.mark.django_db]


def test_cannot_delete_batch_export_backfill(client: TestClient, organization, team, user):
    """
    Should not be able to delete a batch export backfill.
    """
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )

    client.force_login(user)
    response = client.delete(f"/api/projects/{team.pk}/batch_exports/{batch_export.id}/backfills/{backfill.id}")
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_cannot_update_batch_export_backfill(client: TestClient, organization, team, user):
    """
    Should not be able to update a batch export backfill.
    """
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    backfill = create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )

    client.force_login(user)
    response = client.patch(
        f"/api/projects/{team.pk}/batch_exports/{batch_export.id}/backfills/{backfill.id}",
        {"status": "RUNNING"},
        content_type="application/json",
    )
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
