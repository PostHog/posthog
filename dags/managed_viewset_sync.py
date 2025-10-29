import dagster
import structlog

from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet

from dags.common import JobOwners

logger = structlog.get_logger(__name__)


@dagster.op(
    config_schema={
        "kind": dagster.Field(
            dagster.String,
            default_value="",
            is_required=False,
            description="Specific kind to sync. If not provided, syncs all kinds.",
        )
    }
)
def sync_managed_viewsets_op(
    context: dagster.OpExecutionContext,
) -> None:
    """
    Sync views for all ManagedViewsets of a specific kind, or all kinds if no kind specified.
    """
    # Build queryset
    queryset = DataWarehouseManagedViewSet.objects.all()
    kind = context.op_config.get("kind", "")
    if kind is not None and kind != "":
        if kind not in DataWarehouseManagedViewSet.Kind.values:
            raise ValueError(f"Invalid kind: {kind}")
        queryset = queryset.filter(kind=kind)
        context.log.info(f"Syncing ManagedViewsets for kind: {kind}")
    else:
        context.log.info("Syncing all ManagedViewsets")

    # Get all viewsets
    count = queryset.count()
    context.log.info(f"Found {count} ManagedViewsets to sync")

    synced_count = 0
    failed_count = 0
    failed_viewsets = []

    for viewset in queryset.iterator():
        try:
            context.log.info(f"Syncing viewset {viewset.id} (kind: {viewset.kind}, team: {viewset.team_id})")
            viewset.sync_views()
            synced_count += 1
            context.log.info(f"Successfully synced viewset {viewset.id}")
        except Exception as e:
            failed_count += 1
            failed_viewsets.append(
                {"viewset_id": str(viewset.id), "kind": viewset.kind, "team_id": viewset.team_id, "error": str(e)}
            )
            logger.error(
                "failed_to_sync_managed_viewset",
                viewset_id=str(viewset.id),
                kind=viewset.kind,
                team_id=viewset.team_id,
                error=str(e),
                exc_info=True,
            )

    # Add output metadata
    context.add_output_metadata(
        {
            "total_viewsets": dagster.MetadataValue.int(count),
            "synced_count": dagster.MetadataValue.int(synced_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
            "kind_filter": dagster.MetadataValue.text(kind or "all"),
            "failed_viewsets": dagster.MetadataValue.json(failed_viewsets)
            if failed_viewsets
            else dagster.MetadataValue.text("None"),
        }
    )

    if failed_count > 0:
        raise dagster.Failure(f"Failed to sync {failed_count} out of {count} viewsets")


@dagster.job(
    name="sync_managed_viewsets",
    tags={"owner": JobOwners.TEAM_DATA_WAREHOUSE.value},
)
def sync_managed_viewsets_job():
    """
    Job that syncs views for ManagedViewsets.

    Can be configured to sync all kinds or a specific kind.
    """
    sync_managed_viewsets_op()
