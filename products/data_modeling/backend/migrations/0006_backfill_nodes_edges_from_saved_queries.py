# manually created by andrewjmcgehee

import time

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1000
LOG_INTERVAL = 100
BATCH_DELAY_SECONDS = 0.1


def backfill_nodes_and_edges(apps, schema_editor):
    """
    Backfill Node and Edge models from existing SavedQueries.

    Uses a two-pass approach to handle dependency ordering:
    1. First pass: Create all Nodes (without edges)
    2. Second pass: Call sync to create edges (all dependency nodes now exist)

    Only saved queries that don't already have a Node are backfilled.
    Nodes and edges created by this migration are marked with
    {"backfilled": true} in their properties field for easy
    identification and reversibility.
    """
    from products.data_modeling.backend.models import Node, NodeType
    from products.data_modeling.backend.services.saved_query_dag_sync import get_dag_id, sync_saved_query_to_dag
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery

    existing_saved_query_ids = set(Node.objects.values_list("saved_query_id", flat=True))
    saved_queries = DataWarehouseSavedQuery.objects.filter(deleted=False).exclude(id__in=existing_saved_query_ids)
    total_to_backfill = len(saved_queries)
    logger.info("Starting saved_query -> node and edge model backfill...")
    # first pass: create all nodes
    for i, saved_query in enumerate(saved_queries.iterator(chunk_size=BATCH_SIZE)):
        node_type = NodeType.MAT_VIEW if saved_query.table_id else NodeType.VIEW
        Node.objects.create(
            team_id=saved_query.team_id,
            saved_query=saved_query,
            dag_id=get_dag_id(saved_query.team_id),
            name=saved_query.name,
            type=node_type,
            properties={"backfilled": True},
        )
        if (i + 1) % LOG_INTERVAL == 0:
            logger.info("Backfilling nodes...", progress=i + 1, total=total_to_backfill)
        # sleep between batches to reduce load on db
        if (i + 1) % BATCH_SIZE == 0:
            time.sleep(BATCH_DELAY_SECONDS)
    logger.info("All nodes backfilled. Backfilling edges...")
    # second pass: sync to create edges (all nodes now exist)
    for i, saved_query in enumerate(saved_queries.iterator(chunk_size=BATCH_SIZE)):
        sync_saved_query_to_dag(saved_query, extra_properties={"backfilled": True})
        if (i + 1) % LOG_INTERVAL == 0:
            logger.info("Backfilling edges...", progress=i + 1, total=total_to_backfill)
        if (i + 1) % BATCH_SIZE == 0:
            time.sleep(BATCH_DELAY_SECONDS)
    logger.info("Done.")


def reverse_backfill(apps, schema_editor):
    """
    Reverse the backfill by deleting only Nodes and Edges that were
    created by this migration (identified by backfilled=True property).
    """
    Node = apps.get_model("data_modeling", "Node")
    Edge = apps.get_model("data_modeling", "Edge")

    # deleting edges first shouldn't be necessary since nodes should cascade
    # but i'm doing it anyway
    Edge.objects.filter(properties__backfilled=True).delete()
    Node.objects.filter(properties__backfilled=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0005_remove_node_name_unique_within_team_dag_and_more"),
        ("posthog", "0979_survey_enable_iframe_embedding"),  # included just to get the latest team/user migrations
    ]

    operations = [
        migrations.RunPython(backfill_nodes_and_edges, reverse_backfill, elidable=True),
    ]
