import datetime as dt

import pytest

from django.test.client import Client as HttpClient

from products.batch_exports.backend.api.batch_export import BackfillsCursorPagination
from products.batch_exports.backend.models.batch_export import BatchExportBackfill
from products.batch_exports.backend.tests.api.fixtures import create_backfill, create_batch_export, create_destination
from products.batch_exports.backend.tests.api.operations import collect_all_pages, list_batch_export_backfills_ok

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


@pytest.mark.parametrize("ordering", [None, "created_at", "-created_at", "start_at", "-start_at"])
def test_list_batch_export_backfills_pages_over_tied_timestamps(
    client: HttpClient, organization, team, user, ordering, monkeypatch: pytest.MonkeyPatch
):
    """Backfills that share a timestamp must each appear once across page boundaries."""
    monkeypatch.setattr(BackfillsCursorPagination, "page_size", 2)

    batch_export = create_batch_export(team, create_destination())
    start_at = dt.datetime(2021, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    end_at = dt.datetime(2021, 1, 1, 1, 0, 0, tzinfo=dt.UTC)
    created_at = dt.datetime(2025, 1, 1, 0, 0, 0, tzinfo=dt.UTC)

    backfills = [
        create_backfill(
            team,
            batch_export,
            start_at,
            end_at,
            BatchExportBackfill.Status.COMPLETED,
            dt.datetime(2025, 1, 1, 1, 0, 0, tzinfo=dt.UTC),
        )
        for _ in range(5)
    ]
    BatchExportBackfill.objects.filter(id__in=[backfill.id for backfill in backfills]).update(created_at=created_at)

    client.force_login(user)
    query_params = {"ordering": ordering} if ordering else {}
    first_page = list_batch_export_backfills_ok(client, team.pk, batch_export.id, **query_params)
    results = collect_all_pages(client, first_page)

    # Every timestamp is tied, so the backfill id alone decides the order.
    descending = ordering is None or ordering.startswith("-")
    expected = sorted((str(backfill.id) for backfill in backfills), reverse=descending)
    assert [backfill["id"] for backfill in results] == expected
