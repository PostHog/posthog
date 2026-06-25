import uuid
import datetime as dt

import pytest
from unittest.mock import AsyncMock, patch

from django.db import IntegrityError, transaction
from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.data_load.create_table import (
    aget_live_backing_table_by_name,
    create_table_from_saved_query,
)
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
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


def test_unique_constraint_blocks_a_second_live_self_managed_table(team, credential):
    _make_table(team, "tb_p3a_agg_torrent", credential)

    with pytest.raises(IntegrityError), transaction.atomic():
        _make_table(team, "tb_p3a_agg_torrent", credential)


@pytest.mark.parametrize(
    "first_deleted,second_source",
    [
        (True, None),  # first soft-deleted -> a new live self-managed row is fine
        (None, "stripe"),  # second is source-backed -> partial index excludes it
    ],
)
def test_unique_constraint_scope(team, credential, first_deleted, second_source):
    _make_table(team, "ride_duration", credential, deleted=first_deleted)

    source = None
    if second_source:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="Completed",
            source_type=ExternalDataSourceType.STRIPE,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={},
        )

    _make_table(team, "ride_duration", credential, source=source)


def test_create_soft_deletes_leftover_then_creates_new(team, credential):
    saved_query = DataWarehouseSavedQuery.objects.create(
        team=team,
        name="ride_duration",
        query={"query": "SELECT 1", "kind": "HogQLQuery"},
        is_materialized=True,
    )
    job = DataModelingJob.objects.create(
        team=team, saved_query=saved_query, status=DataModelingJob.Status.RUNNING, workflow_id="wf"
    )
    leftover = _make_table(team, "ride_duration", credential)

    with (
        patch.object(DataWarehouseTable, "get_columns", lambda self, *a, **k: {}),
        patch.object(DataWarehouseTable, "get_count", lambda self, *a, **k: 0),
        patch(
            "products.data_warehouse.backend.data_load.create_table.calculate_table_size",
            AsyncMock(return_value=0.0),
        ),
    ):
        result = async_to_sync(create_table_from_saved_query)(
            str(job.id), str(saved_query.id), team.id, "ride_duration__query_1"
        )

    leftover.refresh_from_db()
    saved_query.refresh_from_db()

    assert leftover.deleted is True
    assert result.table.id != leftover.id
    assert saved_query.table_id == result.table.id

    live = list(
        DataWarehouseTable.objects.filter(
            team_id=team.id, name="ride_duration", external_data_source__isnull=True
        ).exclude(deleted=True)
    )
    assert live == [result.table]
