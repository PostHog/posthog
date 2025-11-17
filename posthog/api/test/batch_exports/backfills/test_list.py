import datetime as dt

import pytest

from django.test.client import Client as HttpClient

from posthog.api.test.batch_exports.fixtures import create_backfill, create_batch_export, create_destination
from posthog.api.test.batch_exports.operations import list_batch_export_backfills_ok
from posthog.batch_exports.models import BatchExportBackfill

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

    from posthog.api.test.batch_exports.fixtures import create_organization
    from posthog.api.test.test_team import create_team
    from posthog.api.test.test_user import create_user

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
