from datetime import timedelta

from unittest import mock

from temporalio.client import ScheduleListActionStartWorkflow

from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


def table_node(team, dag: DAG, name: str, properties: dict) -> Node:
    return Node.objects.create(team=team, dag=dag, name=name, type=NodeType.TABLE, properties=properties)


def saved_query_node(team, dag: DAG, name: str, node_type: str) -> Node:
    saved_query = DataWarehouseSavedQuery.objects.create(
        name=name, team=team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    return Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=node_type)


def warehouse_source_node(
    team,
    dag: DAG,
    *,
    sync_frequency_interval: timedelta | None,
    should_sync: bool = True,
    with_schema: bool = True,
) -> Node:
    table = DataWarehouseTable.objects.create(name="stripe_charges", team=team)
    if with_schema:
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix="posthog_test_",
        )
        ExternalDataSchema.objects.create(
            name="stripe_charges",
            team=team,
            source=source,
            table=table,
            sync_frequency_interval=sync_frequency_interval,
            should_sync=should_sync,
        )
    return table_node(team, dag, "stripe_charges", {"origin": "warehouse", "warehouse_table_id": str(table.id)})


def temporal_listing(schedule_ids):
    """A mocked Temporal client whose list_schedules yields one execute-dag listing per id."""

    def _listing(schedule_id):
        action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow="data-modeling-execute-dag")
        return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action))

    async def fake_list_schedules(*_args, **_kwargs):
        async def gen():
            for schedule_id in schedule_ids:
                yield _listing(schedule_id)

        return gen()

    temporal = mock.Mock()
    temporal.list_schedules = fake_list_schedules
    return temporal


def no_existing_schedules():
    """A mocked Temporal client that reports no existing schedules."""
    return temporal_listing([])
