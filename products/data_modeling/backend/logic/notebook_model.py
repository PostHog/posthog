import asyncio
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.hogql.database.database import Database

from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.notebook_model_permissions import can_read_model_upstream_views, can_replace_model_output
from posthog.temporal.common.client import sync_connect

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.contracts import NotebookModelBinding
from products.data_modeling.backend.facade.notebook_model_hooks import notebook_model_executor
from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.logic.saved_query_dag_sync import lock_dag
from products.data_modeling.backend.logic.schedule_reconcile import maybe_reconcile_dag
from products.data_modeling.backend.models import (
    DAG,
    CycleDetectionError,
    DataModelingJob,
    Edge,
    Node,
    NodeType,
    NotebookModel,
)
from products.warehouse_sources.backend.facade.hogql import get_view_or_table_by_name
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def notebook_dag_workflow_id(team_id: int, node_id: UUID, request_id: UUID) -> str:
    return f"notebook-model-dag-{team_id}-{node_id}-{request_id}"


def notebook_dag_status(team_id: int, node_id: UUID, request_id: UUID) -> dict[str, str | None]:
    from products.data_modeling.backend.temporal.workflows.execute_dag import ExecuteDAGResult

    client = sync_connect()
    handle = client.get_workflow_handle(
        notebook_dag_workflow_id(team_id, node_id, request_id), result_type=ExecuteDAGResult
    )

    async def read() -> dict[str, str | None]:
        info = await handle.describe()
        if info.status != WorkflowExecutionStatus.COMPLETED:
            return {"status": info.status.name.lower() if info.status else "unknown", "reason": None}
        result = await handle.result()
        node = next((entry for entry in result.node_results if entry.node_id == str(node_id)), None)
        if node is None:
            return {"status": "skipped", "reason": "The DAG did not select this model."}
        return {
            "status": "skipped" if node.skipped else "completed" if node.success else "failed",
            "reason": node.skip_reason or node.error,
        }

    try:
        return asyncio.run(read())
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            raise NotFound("This DAG run does not exist for this model.") from exc
        raise


def require_table_access(model: NotebookModel, user: User) -> None:
    if model.table_id:
        table = DataWarehouseTable.objects.filter(team_id=model.team_id, pk=model.table_id, deleted=False).first()
        if table is None or not can_replace_model_output(table, user_id=user.pk):
            raise PermissionDenied("You need edit access to the output table.")


def require_notebook_node_edit_access(
    team_id: int, access: UserAccessControl, node_ids: list[UUID], *, deleting_nodes: bool = False
) -> None:
    affected = Q(node_id__in=node_ids)
    if deleting_nodes:
        affected |= Q(node__incoming_edges__source_id__in=node_ids) | Q(node__outgoing_edges__target_id__in=node_ids)
    for model in NotebookModel.objects.for_team(team_id).filter(affected).distinct():
        if model.owner_id != access.user.pk:
            raise PermissionDenied("Only the notebook model owner can change its node or dependencies.")
        notebook_model_executor().authorize(team_id, model.notebook_id, access.user)
        require_table_access(model, access.user)


def _binding(model: NotebookModel) -> NotebookModelBinding:
    return NotebookModelBinding(
        node_id=model.node_id,
        table_id=model.table_id,
        latest_run_id=model.latest_run_id,
        published_run_id=model.published_run_id,
    )


def owned_notebook_model(team_id: int, notebook_id: UUID, node_id: UUID, user: User) -> NotebookModelBinding:
    model = (
        NotebookModel.objects.for_team(team_id)
        .filter(notebook_id=notebook_id, node_id=node_id, owner_id=user.pk)
        .first()
    )
    if model is None:
        raise ValidationError("Choose a warehouse model you declared for this notebook.")
    require_table_access(model, user)
    return _binding(model)


def declare_notebook_model(
    *,
    team: Team,
    user: User,
    notebook_id: UUID,
    output_cell: str,
    definition_hash: str,
    name: str,
    upstream_node_ids: list[UUID],
    daily_refresh: bool,
) -> NotebookModelBinding:
    database = Database.create_for(team_id=team.pk, user=user)
    parents = set(upstream_node_ids)
    with transaction.atomic():
        dag = DAG.get_or_create_default(team)
        lock_dag(team.pk, dag.pk)
        nodes = Node.objects.filter(team=team, dag=dag)
        upstream = list(nodes.filter(id__in=parents).select_related("saved_query"))
        unpublished = set(
            NotebookModel.objects.for_team(team.pk)
            .filter(node_id__in=parents, owner_id=user.pk, table_id__isnull=True)
            .values_list("node_id", flat=True)
        )
        if (
            len(upstream) != len(parents)
            or any(parent.pk not in unpublished and not database.has_table(parent.name) for parent in upstream)
            or not can_read_model_upstream_views(
                (parent.saved_query for parent in upstream if parent.saved_query is not None), user_id=user.pk
            )
        ):
            raise ValidationError("Choose upstream nodes you can read in this project's modeling DAG.")
        model = (
            NotebookModel.objects.for_team(team.pk).select_for_update().filter(node__dag=dag, node__name=name).first()
        )
        if model:
            if model.notebook_id != notebook_id or model.owner_id != user.pk:
                raise PermissionDenied("This output name already belongs to another model.")
            require_table_access(model, user)
            node = model.node
        else:
            if nodes.filter(name=name).exists() or database.has_table(name) or get_view_or_table_by_name(team.pk, name):
                raise ValidationError("This table or model name is already in use.")
            node = nodes.create(team=team, dag=dag, name=name, type=NodeType.TABLE, created_by=user)
            model = NotebookModel(node=node, team=team, notebook_id=notebook_id, owner_id=user.pk)
        set_declared_target(node, timedelta(days=1) if daily_refresh else None)
        incoming = Edge.objects.filter(team=team, dag=dag, target=node)
        existing = set(incoming.values_list("source_id", flat=True))
        if existing != parents or model.definition_hash != definition_hash or model.output_cell != output_cell:
            if (
                model.latest_run_id is not None
                and DataModelingJob.objects.filter(
                    team_id=team.pk, pk=model.latest_run_id, status=DataModelingJob.Status.RUNNING
                ).exists()
            ):
                raise ValidationError("Wait for the current run to finish before changing the model definition.")
        model.definition_hash = definition_hash
        model.output_cell = output_cell
        model.save()
        incoming.exclude(source_id__in=parents).delete()
        try:
            for source_id in sorted(parents - existing):
                Edge.objects.create(team=team, dag=dag, source_id=source_id, target=node)
        except CycleDetectionError as exc:
            raise ValidationError("The declared dependencies would create a cycle.") from exc
        maybe_reconcile_dag(dag)
        transaction.on_commit(
            lambda: report_user_action(
                user,
                "notebook warehouse model declared",
                {"node_id": str(node.id), "upstream_count": len(parents), "daily_refresh": daily_refresh},
                team=team,
            ),
            robust=True,
        )
    return _binding(model)
