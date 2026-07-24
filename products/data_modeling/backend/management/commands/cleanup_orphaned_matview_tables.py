"""Finish the delete cascade for materialized saved queries that were only half-deleted.

The proper delete path (`delete_saved_query`) does four things: remove the DAG node
(`delete_node_from_dag`), soft-delete the query's joins, `revert_materialization()` (soft-delete the
backing table + null table_id + drop model paths + clear schedule/tier), and `soft_delete()` (rename
to POSTHOG_DELETED). A query soft-deleted another way — a manual `deleted=True` in a shell, bypassing
the model method — sets only that flag, leaving the table live (leaks into the "self-managed sources"
sidebar), the DAG node in place (a ghost node with no resolvable saved query), and the model paths /
joins dangling.

This finds those half-deleted matviews and runs the rest of the cascade, so each ends in the same
state a proper delete would have produced. Dry-run by default; --apply to mutate; --team-id to scope.

    python manage.py cleanup_orphaned_matview_tables                 # preview fleet-wide
    python manage.py cleanup_orphaned_matview_tables --team-id 2 --apply
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Q, QuerySet

from products.data_modeling.backend.logic.saved_query_dag_sync import HasDependentsError, delete_node_from_dag
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

CLEANED = "cleaned"
SKIPPED_DEPENDENTS = "skipped_has_live_dependents"


def find_half_deleted_matviews(team_id: int | None = None) -> QuerySet[DataWarehouseSavedQuery]:
    """Soft-deleted saved queries that still have a DAG node or a live backing table to clean up.

    A query is "half-deleted" when it was soft-deleted by a path that bypassed the model method:
    `deleted=True` but `deleted_name IS NULL` (a proper `soft_delete()` always records `deleted_name`
    and renames to POSTHOG_DELETED; a raw `deleted=True` sets neither), and it still has a `Node`
    and/or a live (`deleted=False`) backing table to clean up. The `deleted_name IS NULL` filter is
    what distinguishes these from properly-deleted queries that merely kept a ghost node — a separate,
    far larger population this must not touch. Safety guard: a query whose table is *also* referenced
    by a live saved query is excluded, so the cascade can never soft-delete a table something uses.
    """
    deleted = DataWarehouseSavedQuery.objects.filter(deleted=True, deleted_name__isnull=True)
    if team_id is not None:
        deleted = deleted.filter(team_id=team_id)

    # Tables still referenced by a live query must never be touched.
    live_table_ids = set(
        DataWarehouseSavedQuery.objects.exclude(deleted=True)
        .filter(table_id__isnull=False)
        .values_list("table_id", flat=True)
    )
    sq_ids_with_node = set(Node.objects.filter(saved_query__deleted=True).values_list("saved_query_id", flat=True))
    live_table_id_set = set(
        DataWarehouseTable.objects.exclude(deleted=True)
        .filter(id__in=deleted.filter(table_id__isnull=False).values_list("table_id", flat=True))
        .values_list("id", flat=True)
    )

    keep_ids: list[Any] = []
    for sq_id, table_id in deleted.values_list("id", "table_id"):
        if table_id is not None and table_id in live_table_ids:
            continue  # table shared with a live query — leave the whole thing alone
        has_node = sq_id in sq_ids_with_node
        has_live_table = table_id is not None and table_id in live_table_id_set
        if has_node or has_live_table:
            keep_ids.append(sq_id)

    return DataWarehouseSavedQuery.objects.filter(id__in=keep_ids)


def cascade_delete(saved_query: DataWarehouseSavedQuery) -> str:
    """Run the parts of `delete_saved_query` that a bypassed soft-delete skipped."""
    try:
        delete_node_from_dag(saved_query)
    except HasDependentsError:
        return SKIPPED_DEPENDENTS

    for join in DataWarehouseJoin.objects.filter(
        Q(team_id=saved_query.team_id)
        & (Q(source_table_name=saved_query.name) | Q(joining_table_name=saved_query.name))
    ).exclude(deleted=True):
        join.soft_delete()

    saved_query.revert_materialization()  # soft-deletes the table, nulls table_id, drops model paths
    if saved_query.deleted_name is None:  # complete the rename a bypassed delete skipped
        saved_query.soft_delete()
    return CLEANED


class Command(BaseCommand):
    help = "Finish the delete cascade for materialized saved queries that were only half-deleted (deleted flag set, table/node left behind)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Scope to one team (default: all teams).")
        parser.add_argument("--apply", action="store_true", help="Actually run the cascade (default: dry-run).")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options["team_id"]
        apply: bool = options["apply"]

        saved_queries = list(find_half_deleted_matviews(team_id))
        if not saved_queries:
            self.stdout.write("No half-deleted matviews found.")
            return

        node_dag = dict(
            Node.objects.filter(saved_query__in=saved_queries)
            .select_related("dag")
            .values_list("saved_query_id", "dag__name")
        )
        live_table_ids = {
            t.id
            for t in DataWarehouseTable.objects.exclude(deleted=True).filter(
                id__in=[sq.table_id for sq in saved_queries if sq.table_id]
            )
        }

        verb = "Cascading delete for" if apply else "Would cascade delete"
        self.stdout.write(f"{verb} {len(saved_queries)} half-deleted matview(s):")
        for sq in sorted(saved_queries, key=lambda s: (s.team_id, s.name)):
            leftovers = []
            if sq.id in node_dag:
                leftovers.append(f"node in DAG {node_dag[sq.id]!r}")
            if sq.table_id in live_table_ids:
                leftovers.append("live table")
            self.stdout.write(f"  team {sq.team_id}  {sq.name}  ({', '.join(leftovers)})")

        if not apply:
            self.stdout.write("\nDry-run only. Re-run with --apply to cascade.")
            return

        outcomes: dict[str, int] = {CLEANED: 0, SKIPPED_DEPENDENTS: 0}
        for sq in saved_queries:
            outcomes[cascade_delete(sq)] += 1
        self.stdout.write(f"\nCleaned {outcomes[CLEANED]}; skipped (live dependents) {outcomes[SKIPPED_DEPENDENTS]}.")
