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

import structlog

from products.data_modeling.backend.logic.saved_query_dag_sync import HasDependentsError, delete_node_from_dag
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node
from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

logger = structlog.get_logger(__name__)

CLEANED = "cleaned"
SKIPPED_DEPENDENTS = "skipped_has_live_dependents"
SKIPPED_MANAGED = "skipped_managed_viewset"
SKIPPED_SHARED_TABLE = "skipped_table_shared_with_live_query"
SKIPPED_ERROR = "skipped_error"


def table_shared_with_live_query(saved_query: DataWarehouseSavedQuery) -> bool:
    """Whether a live saved query points at this query's backing table. Checked at batch selection
    AND again inside the cascade: a live query can acquire the table in between, and reverting it
    then would soft-delete a table something uses.
    """
    if saved_query.table_id is None:
        return False
    return (
        DataWarehouseSavedQuery.objects.exclude(deleted=True)
        .filter(team_id=saved_query.team_id, table_id=saved_query.table_id)
        .exists()
    )


def has_live_dependents(saved_query: DataWarehouseSavedQuery) -> bool:
    """Whether any live saved query depends on *any* of this query's nodes.

    `delete_node_from_dag` deletes every Node the query has, but the `HasDependentsError` guard it
    relies on only inspects one arbitrary node (`get_dependent_saved_queries` does a `.first()`). A
    query with nodes in several DAGs — the exact population `consolidate_dags` exists for — can
    therefore pass that guard while a real dependent sits in another DAG, and the cascade would
    delete its edge and revert the table underneath it. Check the full blast radius first.
    """
    nodes = Node.objects.filter(team_id=saved_query.team_id, saved_query=saved_query)
    return (
        Node.objects.filter(
            team_id=saved_query.team_id,
            incoming_edges__source__in=nodes,
            saved_query__isnull=False,
        )
        .exclude(saved_query__deleted=True)
        .exists()
    )


def find_half_deleted_matviews(team_id: int | None = None) -> QuerySet[DataWarehouseSavedQuery]:
    """Saved queries soft-deleted by a path that bypassed the model method, with cleanup pending.

    The signature is `deleted=True` but `deleted_name IS NULL`: a proper `soft_delete()` always
    records `deleted_name` and renames to POSTHOG_DELETED, a raw `deleted=True` does neither. That
    filter is also what distinguishes these from properly-deleted queries that merely kept a ghost
    node — a separate, far larger population this must not touch. Managed-viewset rows are excluded
    because their viewset owns their lifecycle.

    Every signature row stays selected regardless of which leftovers (node, live table, joins,
    rename) it still has: the cascade's stages commit independently, so a run that failed partway
    can leave a row with no node and no live table but live joins or an unfreed name. `soft_delete`
    runs last in the cascade and records `deleted_name` — the terminal marker that removes the row
    from this population — and every earlier stage is a no-op once done, so re-running the command
    resumes any partial cleanup.

    Safety guard: a query whose table is *also* referenced by a live saved query is excluded, so
    the cascade can never soft-delete a table something uses. The guard lookup is scoped by
    `--team-id` too: unscoped it reads the whole fleet on a single-team run, and tables are
    team-owned so another team's rows can never be the ones at risk.
    """
    deleted = DataWarehouseSavedQuery.objects.filter(
        deleted=True, deleted_name__isnull=True, managed_viewset__isnull=True
    )
    live = DataWarehouseSavedQuery.objects.exclude(deleted=True)
    if team_id is not None:
        deleted = deleted.filter(team_id=team_id)
        live = live.filter(team_id=team_id)

    # Tables still referenced by a live query must never be touched.
    live_table_ids = set(live.filter(table_id__isnull=False).values_list("table_id", flat=True))
    keep_ids: list[Any] = [
        sq_id
        for sq_id, table_id in deleted.values_list("id", "table_id")
        if table_id is None or table_id not in live_table_ids
    ]
    return DataWarehouseSavedQuery.objects.filter(id__in=keep_ids)


def cascade_delete(saved_query: DataWarehouseSavedQuery) -> str:
    """Run the parts of `delete_saved_query` that a bypassed soft-delete skipped.

    The stages commit independently, so ordering is the retry mechanism: every stage is a no-op
    once done, and `soft_delete` — whose `deleted_name` removes the row from
    `find_half_deleted_matviews` — must stay LAST, so a failure at any earlier stage leaves the
    row selected for the next run to resume.
    """
    # `delete_saved_query` refuses these outright: the managed viewset owns the lifecycle and
    # reconciles its own views, so tearing one down out-of-band leaves sync_views() to discover a
    # view it believes it owns already gone.
    if saved_query.managed_viewset is not None:
        return SKIPPED_MANAGED
    if table_shared_with_live_query(saved_query):
        return SKIPPED_SHARED_TABLE
    if has_live_dependents(saved_query):
        return SKIPPED_DEPENDENTS

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
            if not leftovers:
                leftovers.append("unfinished rename only")
            self.stdout.write(f"  team {sq.team_id}  {sq.name}  ({', '.join(leftovers)})")

        if not apply:
            self.stdout.write("\nDry-run only. Re-run with --apply to cascade.")
            return

        # Per-item isolation: a fleet-wide run must not lose the work it already did (or the record
        # of what it did) because one query failed halfway down the list.
        outcomes: dict[str, int] = {CLEANED: 0, SKIPPED_DEPENDENTS: 0, SKIPPED_MANAGED: 0, SKIPPED_ERROR: 0}
        for sq in saved_queries:
            try:
                outcomes[cascade_delete(sq)] += 1
            except Exception as e:
                outcomes[SKIPPED_ERROR] += 1
                self.stderr.write(f"  team {sq.team_id}  {sq.name}: {type(e).__name__}: {e}")
                logger.exception(
                    "cleanup_orphaned_matview_tables_failed", team_id=sq.team_id, saved_query_id=str(sq.id)
                )
        self.stdout.write(
            f"\nCleaned {outcomes[CLEANED]}; skipped — live dependents {outcomes[SKIPPED_DEPENDENTS]}, "
            f"managed viewset {outcomes[SKIPPED_MANAGED]}, errored {outcomes[SKIPPED_ERROR]}."
        )
        if outcomes[SKIPPED_ERROR]:
            self.stdout.write("Re-run to retry the failures — the cascade is idempotent per query.")
