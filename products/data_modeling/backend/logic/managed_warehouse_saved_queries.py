from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.data_modeling.backend.facade.contracts import ManagedWarehouseSavedQueryRecord
from products.data_modeling.backend.logic.saved_query_dag_sync import delete_node_from_dag
from products.data_modeling.backend.models import (
    DAG,
    DataModelingJob,
    DataWarehouseModelPath,
    DataWarehouseSavedQuery,
    Node,
    NodeType,
)
from products.data_modeling.backend.models.data_modeling_job import DataModelingJobRunMode
from products.data_modeling.backend.models.datawarehouse_saved_query import validate_saved_query_name
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def _to_record(saved_query: DataWarehouseSavedQuery) -> ManagedWarehouseSavedQueryRecord:
    table = saved_query.table
    return ManagedWarehouseSavedQueryRecord(
        id=saved_query.id,
        team_id=saved_query.team_id,
        name=saved_query.name,
        status=saved_query.status,
        last_run_at=saved_query.last_run_at,
        latest_error=saved_query.latest_error,
        table_id=saved_query.table_id,
        row_count=table.row_count if table is not None else None,
        deleted=bool(saved_query.deleted),
    )


def active_saved_query_name_exists(*, team_id: int, name: str) -> bool:
    return DataWarehouseSavedQuery.objects.filter(team_id=team_id, name=name, deleted=False).exists()


@transaction.atomic
def create_managed_warehouse_saved_query(
    *,
    team_id: int,
    name: str,
    source_schema_name: str,
    source_table_name: str,
    created_by_id: int | None = None,
) -> ManagedWarehouseSavedQueryRecord:
    validate_saved_query_name(name)
    saved_query = DataWarehouseSavedQuery.objects.create(
        team_id=team_id,
        name=name,
        query={
            "kind": "ManagedWarehouseSource",
            "source_schema_name": source_schema_name,
            "source_table_name": source_table_name,
        },
        status=DataWarehouseSavedQuery.Status.MODIFIED,
        is_materialized=True,
        origin=DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE,
        created_by_id=created_by_id,
    )
    DataWarehouseModelPath.objects.create(
        team_id=team_id,
        saved_query=saved_query,
        path=[saved_query.id.hex],
        created_by_id=created_by_id,
    )
    Node.objects.create(
        team_id=team_id,
        saved_query=saved_query,
        dag=DAG.get_or_create_default(saved_query.team),
        name=name,
        type=NodeType.MAT_VIEW,
        properties={"origin": "managed_warehouse"},
    )
    return _to_record(saved_query)


def get_managed_warehouse_saved_query(
    team_id: int, saved_query_id: UUID | str
) -> ManagedWarehouseSavedQueryRecord | None:
    saved_query = (
        DataWarehouseSavedQuery.objects.select_related("table")
        .filter(team_id=team_id, id=saved_query_id, origin=DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE)
        .first()
    )
    return _to_record(saved_query) if saved_query is not None else None


@transaction.atomic
def start_managed_warehouse_saved_query_publish(team_id: int, saved_query_id: UUID | str, workflow_id: str) -> UUID:
    saved_query = DataWarehouseSavedQuery.objects.select_for_update().get(
        team_id=team_id,
        id=saved_query_id,
        origin=DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE,
        deleted=False,
    )
    saved_query.status = DataWarehouseSavedQuery.Status.RUNNING
    saved_query.latest_error = None
    saved_query.save(update_fields=["status", "latest_error", "updated_at"])
    existing_job = (
        DataModelingJob.objects.filter(
            team_id=team_id,
            saved_query=saved_query,
            status=DataModelingJob.Status.RUNNING,
            workflow_id=workflow_id,
        )
        .order_by("-created_at")
        .first()
    )
    if existing_job is not None:
        return existing_job.id
    job = DataModelingJob.objects.create(
        team_id=team_id,
        saved_query=saved_query,
        status=DataModelingJob.Status.RUNNING,
        engine=DataModelingJob.Engine.DUCKGRES,
        run_mode=DataModelingJobRunMode.FULL_REFRESH,
        workflow_id=workflow_id,
    )
    return job.id


@transaction.atomic
def complete_managed_warehouse_saved_query_publish(
    *, team_id: int, saved_query_id: UUID | str, table_id: UUID, job_id: UUID | None
) -> ManagedWarehouseSavedQueryRecord:
    saved_query = DataWarehouseSavedQuery.objects.select_for_update().get(
        team_id=team_id,
        id=saved_query_id,
        origin=DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE,
        deleted=False,
    )
    table = DataWarehouseTable.objects.get(team_id=team_id, id=table_id, deleted=False)
    saved_query.table = table
    saved_query.set_columns(table.columns or {})
    saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
    saved_query.last_run_at = timezone.now()
    saved_query.latest_error = None
    saved_query.save(
        update_fields=[
            "table",
            "columns",
            "column_order",
            "status",
            "last_run_at",
            "latest_error",
            "updated_at",
        ]
    )
    if job_id is not None:
        DataModelingJob.objects.filter(id=job_id, team_id=team_id, saved_query=saved_query).update(
            status=DataModelingJob.Status.COMPLETED,
            rows_materialized=table.row_count or 0,
            last_run_at=saved_query.last_run_at,
            error=None,
        )
    return _to_record(saved_query)


@transaction.atomic
def fail_managed_warehouse_saved_query_publish(
    *, team_id: int, saved_query_id: UUID | str, error: str, job_id: UUID | None
) -> None:
    saved_query = (
        DataWarehouseSavedQuery.objects.select_for_update()
        .filter(
            team_id=team_id,
            id=saved_query_id,
            origin=DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE,
            deleted=False,
        )
        .first()
    )
    if saved_query is None:
        return
    saved_query.status = DataWarehouseSavedQuery.Status.FAILED
    saved_query.latest_error = error
    saved_query.save(update_fields=["status", "latest_error", "updated_at"])
    if job_id is not None:
        DataModelingJob.objects.filter(id=job_id, team_id=team_id, saved_query=saved_query).update(
            status=DataModelingJob.Status.FAILED,
            error=error,
            last_run_at=timezone.now(),
        )


@transaction.atomic
def delete_managed_warehouse_saved_query(team_id: int, saved_query_id: UUID | str) -> bool:
    saved_query = (
        DataWarehouseSavedQuery.objects.select_for_update()
        .filter(
            team_id=team_id,
            id=saved_query_id,
            origin=DataWarehouseSavedQuery.Origin.MANAGED_WAREHOUSE,
            deleted=False,
        )
        .first()
    )
    if saved_query is None:
        return False
    delete_node_from_dag(saved_query)
    DataWarehouseModelPath.objects.filter(team_id=team_id, saved_query=saved_query).delete()
    saved_query.table_id = None
    saved_query.soft_delete()
    return True
