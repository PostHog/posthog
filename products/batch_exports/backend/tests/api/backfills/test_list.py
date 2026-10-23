import datetime as dt

import pytest
from unittest.mock import patch

from django.test.client import Client as HttpClient

from products.batch_exports.backend.models.batch_export import BatchExportBackfill
from products.batch_exports.backend.presentation.views.batch_export.backfills import BackfillsCursorPagination
from products.batch_exports.backend.tests.api.fixtures import create_backfill, create_batch_export, create_destination
from products.batch_exports.backend.tests.api.operations import list_batch_export_backfills_ok

pytestmark = [pytest.mark.django_db]


def test_list_batch_export_backfills(client: HttpClient, organization, team, user):
    """Test that we can list batch export backfills."""
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )
    create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 3, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )

    client.force_login(user)
    response = list_batch_export_backfills_ok(client, team.pk, batch_export.id)
    assert len(response["results"]) == 2


@pytest.mark.parametrize("ordering", ["start_at", "-start_at"])
def test_list_batch_export_backfills_pages_through_tied_values(client: HttpClient, team, user, ordering):
    batch_export = create_batch_export(team, create_destination())
    early = dt.datetime(2021, 1, 1, tzinfo=dt.UTC)
    late = dt.datetime(2021, 1, 2, tzinfo=dt.UTC)
    backfill_ids = {
        str(create_backfill(team, batch_export, start_at, None, BatchExportBackfill.Status.COMPLETED, None).id)
        for start_at in [early, early, early, late, late]
    }

    client.force_login(user)
    pages = []
    with patch.object(BackfillsCursorPagination, "page_size", 2):
        page = client.get(
            f"/api/projects/{team.pk}/batch_exports/{batch_export.id}/backfills/?ordering={ordering}"
        ).json()
        pages.append(page)
        # Bounded, so a cursor that never advances fails instead of hanging.
        while page["next"] and len(pages) <= len(backfill_ids):
            page = client.get(page["next"]).json()
            pages.append(page)

    listed = [backfill["id"] for page in pages for backfill in page["results"]]
    assert sorted(listed) == sorted(backfill_ids)


def test_cannot_list_batch_export_backfills_for_other_organizations(client: HttpClient, organization, team, user):
    """
    Should not be able to list batch export backfills for other organizations.
    """
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )
    create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 3, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )

    from posthog.api.test.test_team import create_team
    from posthog.api.test.test_user import create_user

    from products.batch_exports.backend.tests.api.fixtures import create_organization

    other_organization = create_organization("Other Test Org")
    other_team = create_team(other_organization)
    other_user = create_user("another-test@user.com", "Another Test User", other_organization)

    client.force_login(user)

    # Make sure we can list batch export backfills for our own team.
    response = list_batch_export_backfills_ok(client, team.pk, batch_export.id)
    assert len(response["results"]) == 2

    client.force_login(other_user)
    response = list_batch_export_backfills_ok(client, other_team.pk, batch_export.id)
    assert len(response["results"]) == 0


def test_list_is_partitioned_by_team(client: HttpClient, organization, team, user):
    """
    Should be able to list batch export backfills for a specific team.
    """
    from posthog.api.test.test_team import create_team

    another_team = create_team(organization)
    destination = create_destination()
    batch_export = create_batch_export(team, destination)
    create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )
    create_backfill(
        team,
        batch_export,
        dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2021, 1, 1, 3, 0, 0, tzinfo=dt.UTC),
        BatchExportBackfill.Status.COMPLETED,
        dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
    )

    client.force_login(user)

    # Make sure we can list batch export backfills for that team.
    response = list_batch_export_backfills_ok(client, team.pk, batch_export.id)
    assert len(response["results"]) == 2

    # Make sure we can't see these batch export backfills for the other team.
    response = list_batch_export_backfills_ok(client, another_team.pk, batch_export.id)
    assert len(response["results"]) == 0
