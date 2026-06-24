import datetime as dt

import pytest

from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.data_warehouse.backend.data_load.create_table import aget_live_backing_table_by_name
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def team():
    return create_team(organization=create_organization(name="org"))


@pytest.fixture
def credential(team):
    return DataWarehouseCredential.objects.create(team=team, access_key="k", access_secret="s")


def _make_table(team, name, credential, *, created_at=None, deleted=None, source=None):
    table = DataWarehouseTable.objects.create(
        team=team,
        name=name,
        format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        url_pattern="",
        columns={},
        credential=credential,
        external_data_source=source,
        deleted=deleted,
    )
    if created_at is not None:
        DataWarehouseTable.objects.filter(id=table.id).update(created_at=created_at)
        table.refresh_from_db()
    return table


def test_aget_live_backing_table_by_name_returns_newest_live_self_managed(team, credential):
    now = timezone.now()
    _make_table(team, "v", credential, created_at=now - dt.timedelta(days=2), deleted=True)
    newest = _make_table(team, "v", credential, created_at=now)

    found = async_to_sync(aget_live_backing_table_by_name)(team.id, "v")
    assert found is not None
    assert found.id == newest.id
