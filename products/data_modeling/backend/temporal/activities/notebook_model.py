from uuid import UUID

from django.db import transaction

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.event_usage import report_team_action
from posthog.models import User
from posthog.models.scoping import team_scope
from posthog.temporal.common.utils import close_db_connections

from products.data_modeling.backend.facade.notebook_model_hooks import notebook_model_executor
from products.data_modeling.backend.logic.notebook_model import require_table_access
from products.data_modeling.backend.models import DataModelingJob, NotebookModel
from products.data_modeling.backend.temporal.activities.utils import update_node_system_properties
from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.facade.api import MAX_FILE_UPLOAD_SIZE_BYTES, build_file_upload_s3_path
from products.warehouse_sources.backend.facade.contracts import UploadedFileRef
from products.warehouse_sources.backend.facade.file_upload_sources import discard_replaced_upload, warehouse_output_url
from products.warehouse_sources.backend.facade.hogql import get_view_or_table_by_name
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


@frozen
class ModelRun:
    team_id: int
    node_id: str
    dag_id: str
    run_id: UUID
    triggered_by_id: int | None
    parent_workflow_id: str | None = None


@frozen
class PreparedNotebookModel:
    node_ids: list[str]
    previous_generation: UUID | None


@frozen
class RetiredNotebookUpload:
    team_id: int
    generation: UUID


def _binding(run: ModelRun, *, lock: bool = False) -> NotebookModel:
    qs = NotebookModel.objects.for_team(run.team_id).select_related("node", "team")
    if lock:
        qs = qs.select_for_update(of=("self", "node"))
    return qs.get(node_id=run.node_id, node__dag_id=run.dag_id)


@activity.defn
@close_db_connections
def prepare_notebook_model(run: ModelRun) -> PreparedNotebookModel | None:
    with team_scope(run.team_id, canonical=True), transaction.atomic():
        binding = _binding(run, lock=True)
        if run.triggered_by_id is not None and run.triggered_by_id != binding.owner_id:
            raise ValueError("Only the model author can trigger an unattended notebook run.")
        if (
            binding.latest_run_id is not None
            and binding.latest_run_id != run.run_id
            and DataModelingJob.objects.filter(
                team_id=run.team_id, id=binding.latest_run_id, status=DataModelingJob.Status.RUNNING
            ).exists()
        ):
            raise ValueError("Another run is publishing this model.")
        job, created = DataModelingJob.objects.get_or_create(
            team_id=run.team_id,
            id=run.run_id,
            defaults={
                "manually_triggered_by_id": run.triggered_by_id,
                "parent_workflow_id": run.parent_workflow_id,
                "workflow_id": activity.info().workflow_id,
                "workflow_run_id": activity.info().workflow_run_id,
            },
        )
        if not created and binding.latest_run_id != job.id:
            raise ValueError("This run has been superseded.")
        binding.latest_run_id = run.run_id
        binding.save(update_fields=["latest_run_id"])
    with team_scope(run.team_id, canonical=True), transaction.atomic():
        binding = _binding(run, lock=True)
        if binding.latest_run_id != run.run_id:
            raise ValueError("This run has been superseded.")
        user = User.objects.get(pk=binding.owner_id, is_active=True)
        require_table_access(binding, user)
        nodes = notebook_model_executor().prepare(
            run.team_id, binding.notebook_id, binding.output_cell, binding.definition_hash, user.pk, run.run_id
        )
        return (
            PreparedNotebookModel(node_ids=nodes, previous_generation=binding.published_run_id)
            if nodes is not None
            else None
        )


def _staged_upload(generation: UUID) -> UploadedFileRef:
    return UploadedFileRef(upload_id=str(generation), filename="output.parquet", file_format="parquet")


@activity.defn
@close_db_connections
def remove_retired_notebook_upload(retired: RetiredNotebookUpload) -> None:
    with team_scope(retired.team_id, canonical=True):
        discard_replaced_upload(
            retired.team_id, warehouse_output_url(retired.team_id, _staged_upload(retired.generation))
        )


def publish_frame(run: ModelRun, upload: UploadedFileRef, row_count: int) -> None:
    binding = _binding(run)
    url = warehouse_output_url(run.team_id, upload)
    probe = DataWarehouseTable(team=binding.team, name=binding.node.name, format="Parquet", url_pattern=url)
    columns = probe.get_columns()
    if probe.get_count() != row_count:
        raise ValueError("The number of rows in the warehouse differs from the notebook output.")
    with transaction.atomic():
        binding = _binding(run, lock=True)
        if binding.latest_run_id != run.run_id:
            raise ValueError("The model changed while this run was publishing.")
        if binding.published_run_id == run.run_id:
            return
        job = DataModelingJob.objects.select_for_update().get(team_id=run.team_id, id=run.run_id)
        if job.status != DataModelingJob.Status.RUNNING:
            raise ValueError("This model run is already closed.")
        owner = User.objects.get(pk=binding.owner_id, is_active=True)
        notebook_model_executor().authorize(run.team_id, binding.notebook_id, owner)
        if binding.table_id:
            table = DataWarehouseTable.objects.select_for_update(of=("self",)).get(
                pk=binding.table_id, team_id=run.team_id, deleted=False
            )
            require_table_access(binding, owner)
            if table.name != binding.node.name or table.external_data_source_id or table.credential_id:
                raise ValueError("The output table changed. Check the model destination before retrying.")
        else:
            if get_view_or_table_by_name(run.team_id, binding.node.name):
                raise ValueError("The output name is already in use. Choose a different name.")
            table = DataWarehouseTable(team_id=run.team_id, name=binding.node.name, created_by=owner)
        table.url_pattern = url
        table.format = "Parquet"
        table.row_count = row_count
        table.set_columns(columns)
        table.save(internally_computed_url_pattern=True)
        binding.table_id = table.pk
        binding.published_run_id = run.run_id
        binding.save(update_fields=["table_id", "published_run_id"])
        node = binding.node
        node.properties = {**node.properties, "origin": "warehouse", "warehouse_table_id": str(table.pk)}
        update_node_system_properties(
            node, status=DataModelingJob.Status.COMPLETED, job_id=str(run.run_id), rows=row_count
        )
        node.save(update_fields=["properties"])
        transaction.on_commit(
            lambda: report_team_action(
                binding.team,
                "notebook warehouse model published",
                {"node_id": str(node.id), "row_count": row_count, "manual": run.triggered_by_id is not None},
            ),
            robust=True,
        )
        job.status = DataModelingJob.Status.COMPLETED
        job.rows_materialized = row_count
        job.save(update_fields=["status", "rows_materialized"])


@activity.defn
@close_db_connections
def publish_notebook_model(run: ModelRun) -> int:
    with team_scope(run.team_id, canonical=True):
        binding = _binding(run)
        if binding.published_run_id == run.run_id:
            return DataModelingJob.objects.get(team_id=run.team_id, pk=run.run_id).rows_materialized
        if binding.latest_run_id != run.run_id:
            raise ValueError("This run has been superseded.")
        upload = _staged_upload(run.run_id)
        try:
            with notebook_model_executor().open_output(
                run.team_id, binding.notebook_id, run.run_id, MAX_FILE_UPLOAD_SIZE_BYTES
            ) as (source, rows):
                path = build_file_upload_s3_path(run.team_id, upload.upload_id, upload.filename)
                with get_s3_client().open(path, "wb") as destination:
                    written = 0
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > MAX_FILE_UPLOAD_SIZE_BYTES:
                            raise ValueError("The notebook output exceeds the warehouse file size limit.")
                        destination.write(chunk)
                        activity.heartbeat()
            publish_frame(run, upload, rows)
        except Exception:
            discard_replaced_upload(run.team_id, warehouse_output_url(run.team_id, upload))
            raise
        return rows


@frozen
class ModelFailure:
    run: ModelRun
    error: str


@activity.defn
@close_db_connections
def fail_notebook_model(failure: ModelFailure) -> None:
    run = failure.run
    with team_scope(run.team_id, canonical=True):
        with transaction.atomic():
            model = (
                NotebookModel.objects.for_team(run.team_id)
                .select_related("node", "team")
                .select_for_update(of=("self", "node"))
                .filter(node_id=run.node_id, node__dag_id=run.dag_id)
                .first()
            )
            failed = DataModelingJob.objects.filter(
                team_id=run.team_id, id=run.run_id, status=DataModelingJob.Status.RUNNING
            ).update(status=DataModelingJob.Status.FAILED, error=failure.error)
            if failed and model is not None and model.latest_run_id == run.run_id:
                update_node_system_properties(
                    model.node, status=DataModelingJob.Status.FAILED, job_id=str(run.run_id), error=failure.error
                )
                model.node.save(update_fields=["properties"])
            if failed and model is not None:
                transaction.on_commit(
                    lambda: report_team_action(
                        model.team,
                        "notebook warehouse model failed",
                        {"node_id": str(model.node_id), "run_id": str(run.run_id)},
                    ),
                    robust=True,
                )
        notebook_model_executor().stop(run.team_id, run.run_id)
        if failed:
            discard_replaced_upload(run.team_id, warehouse_output_url(run.team_id, _staged_upload(run.run_id)))
