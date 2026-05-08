from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

from celery import shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit

if TYPE_CHECKING:
    from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

logger = get_logger(__name__)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def cleanup_expired_test_saved_queries() -> None:
    """Hard-delete test saved queries whose expires_at has passed, along with downstream objects.

    Processes queries iteratively in topological order: on each pass we only delete
    queries that have no remaining dependents (other non-deleted saved queries that
    reference them via DAG edges). This handles chains of test queries that depend
    on each other.
    """
    from products.data_modeling.backend.models.node import Node
    from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    now = timezone.now()
    expired_qs = DataWarehouseSavedQuery.objects.filter(
        is_test=True,
        expires_at__lte=now,
        deleted=False,
    )

    expired_ids = set(expired_qs.values_list("id", flat=True))
    if not expired_ids:
        return

    total_deleted = 0

    # Iteratively delete leaf nodes first (those with no dependents among the expired set).
    # This ensures we respect the Node PROTECT constraint and handle chains properly.
    while expired_ids:
        deleted_this_pass: set = set()

        for saved_query in DataWarehouseSavedQuery.objects.filter(id__in=expired_ids).select_related("table"):
            # Check if any non-deleted saved query depends on this one via DAG edges
            node = Node.objects.filter(team=saved_query.team, saved_query=saved_query).first()
            if node:
                has_dependents = (
                    Node.objects.filter(
                        team=saved_query.team,
                        incoming_edges__source=node,
                        saved_query__isnull=False,
                    )
                    .exclude(
                        saved_query__deleted=True,
                    )
                    .exclude(
                        # Ignore dependents that are also expired and pending deletion
                        saved_query__id__in=expired_ids - {saved_query.id},
                    )
                    .exists()
                )

                if has_dependents:
                    # Skip for now — will be retried on the next daily run
                    continue

            _hard_delete_saved_query(saved_query)
            deleted_this_pass.add(saved_query.id)

        if not deleted_this_pass:
            # No progress — remaining queries have non-test dependents, skip them
            if expired_ids:
                logger.warning(
                    "Could not delete some expired test saved queries due to dependents",
                    remaining_ids=[str(id) for id in expired_ids],
                )
            break

        expired_ids -= deleted_this_pass
        total_deleted += len(deleted_this_pass)

    logger.info("Cleaned up expired test saved queries", deleted_count=total_deleted)


def _hard_delete_saved_query(saved_query: "DataWarehouseSavedQuery") -> None:
    """Hard-delete a single saved query and all downstream objects."""
    from products.data_modeling.backend.models.node import Node
    from products.data_warehouse.backend.models.join import DataWarehouseJoin
    from products.data_warehouse.backend.models.modeling import DataWarehouseModelPath

    logger.info("Hard-deleting expired test saved query", saved_query_id=str(saved_query.id), name=saved_query.name)

    # 1. Delete the DAG node (must happen before saved query deletion due to PROTECT).
    #    EndpointVersion.saved_query has on_delete=SET_NULL, so Django handles that automatically.
    Node.objects.filter(team=saved_query.team, saved_query=saved_query).delete()
    # 2. Delete joins that reference this saved query by name
    DataWarehouseJoin.objects.filter(
        Q(team_id=saved_query.team_id)
        & (Q(source_table_name=saved_query.name) | Q(joining_table_name=saved_query.name))
    ).delete()
    # 3. Delete model paths
    DataWarehouseModelPath.objects.filter(team=saved_query.team, path__lquery=f"*{{1,}}.{saved_query.id.hex}").delete()
    # 4. Revert materialization (drops schedule, soft-deletes the table)
    table_to_delete = saved_query.table
    saved_query.revert_materialization()
    # 5. Delete S3 data for the materialized view
    _delete_s3_data(saved_query)
    # 6. Hard-delete the materialized table if it exists
    if table_to_delete is not None:
        table_to_delete.delete()
    # 7. Hard-delete the saved query itself
    saved_query.delete()


def _delete_s3_data(saved_query: "DataWarehouseSavedQuery") -> None:
    """Delete S3 Delta Lake files for a materialized saved query."""
    from django.conf import settings

    from posthog.exceptions_capture import capture_exception

    from products.data_warehouse.backend.s3 import get_s3_client

    # The materialization workflow writes to:
    #   {BUCKET_URL}/team_{team_id}_model_{saved_query_id_hex}/modeling/{normalized_name}
    # We delete the entire model directory for this saved query.
    s3_prefix = f"{settings.BUCKET_URL}/team_{saved_query.team_id}_model_{saved_query.id.hex}"

    try:
        client = get_s3_client()
        client.delete(s3_prefix, recursive=True)
        logger.info("Deleted S3 data for test saved query", saved_query_id=str(saved_query.id), s3_prefix=s3_prefix)
    except FileNotFoundError:
        # No S3 data to clean up (query was never materialized)
        pass
    except Exception as e:
        capture_exception(e)
        logger.exception(
            "Failed to delete S3 data for test saved query",
            saved_query_id=str(saved_query.id),
            s3_prefix=s3_prefix,
        )
