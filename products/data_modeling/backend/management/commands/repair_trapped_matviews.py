"""Put materialized saved queries that lost their backing table back on a schedule.

`DataWarehouseSavedQuery.table` is `on_delete=SET_NULL`, so a vanished backing table nulls
`table_id` while `is_materialized` stays True. `node_type_for` reads `table_id`, not the flag, so
the next DAG sync types the node `view`; `get_dag_structure` calls every `view` node ephemeral and
`execute_dag` reports success without materializing and without writing a job row. The model stops
updating silently and can never regain a table, so it can never be retyped back.

Two things are wrong with each one and both must be repaired or the model still never runs: the
node type says ephemeral, and the node carries no frequency target, so it joins no cadence tier.
The target comes from the node itself if it has one, else the query's leftover v1
`sync_frequency_interval`, else daily — what the Materialize button gives a query with no opinion.

Managed viewsets are excluded: the `materialize` action refuses them outright, so their flag is a
provisioning artifact rather than intent to schedule. Endpoint-origin queries are excluded too —
their nodes are typed `endpoint`, which already executes, so a query of theirs with no table is
failing rather than trapped.

Dry-run by default; --apply to mutate; --team-id to scope.

    python manage.py repair_trapped_matviews                  # preview fleet-wide
    python manage.py repair_trapped_matviews --team-id 2 --apply
"""

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Q

import structlog

from products.data_modeling.backend.logic.freshness import UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.node_frequency import get_declared_target, saved_query_target_bounds
from products.data_modeling.backend.logic.saved_query_dag_sync import update_node_type
from products.data_modeling.backend.logic.schedule_reconcile import (
    apply_saved_query_frequency_target,
    reconcile_dag_schedules,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType

logger = structlog.get_logger(__name__)

DEFAULT_TARGET = timedelta(days=1)

REPAIRED = "repaired"
SKIPPED_NO_NODE = "skipped_no_dag_node"
SKIPPED_REFUSED = "skipped_cadence_refused"
SKIPPED_ERROR = "skipped_error"


def trapped_saved_queries(team_id: int | None) -> list[DataWarehouseSavedQuery]:
    """Materialized queries with no backing table whose graph still calls them ephemeral views."""
    trapped_node_ids = Node.objects.filter(type=NodeType.VIEW).values("saved_query_id")
    queryset = (
        DataWarehouseSavedQuery.objects.exclude(deleted=True)
        .filter(
            Q(is_materialized=True),
            Q(table_id__isnull=True),
            Q(managed_viewset__isnull=True),
            Q(id__in=trapped_node_ids),
        )
        # `origin` is nullable and was never backfilled, so name the origins that own their own
        # lifecycle and let everything else through: a null-origin row is an ordinary saved query.
        .exclude(
            origin__in=[
                DataWarehouseSavedQuery.Origin.ENDPOINT,
                DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET,
            ]
        )
        .select_related("team")
        .order_by("team_id", "id")
    )
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    return list(queryset)


def target_for(saved_query: DataWarehouseSavedQuery) -> timedelta:
    """The cadence to restore: what the node already declares, else the query's, else daily."""
    for node in Node.objects.filter(team_id=saved_query.team_id, saved_query=saved_query):
        declared = get_declared_target(node)
        if declared is not None:
            return declared
    return saved_query.sync_frequency_interval or DEFAULT_TARGET


def clamp_to_bounds(saved_query: DataWarehouseSavedQuery, preferred: timedelta) -> timedelta | None:
    """The nearest cadence this query's DAGs accept, or None when they accept none.

    A trapped query usually declares no cadence of its own, so `target_for` falls back to a guess,
    and the write refuses a guess that a consumer downstream needs beaten. Ask the read-side twin
    of that write what it permits and move the guess inside it, rather than offering a cadence the
    next line is going to reject.
    """
    bounds = saved_query_target_bounds(saved_query.team_id, saved_query.id)
    if bounds is None:
        return preferred  # no node carries it; the apply below reports that better than we can
    allowed = bounds.bounds.allowed
    if not allowed:
        return None
    # `allowed` is ascending, and a v1 `sync_frequency_interval` need not be a bucket at all, so
    # land on a real member: the cheapest run that still honours the ceiling, else the fastest.
    within = [option for option in allowed if option <= preferred]
    return within[-1] if within else allowed[0]


class Command(BaseCommand):
    help = "Re-schedule materialized saved queries trapped as ephemeral views after losing their table"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only this team")
        parser.add_argument("--apply", action="store_true", help="Mutate; otherwise preview only")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many queries")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int | None = options["team_id"]
        apply: bool = options["apply"]
        limit: int | None = options["limit"]

        saved_queries = trapped_saved_queries(team_id)
        if limit is not None:
            saved_queries = saved_queries[:limit]

        counts: dict[str, int] = {}
        # Retyping a node changes what the DAG's existing schedule runs, so every DAG touched is
        # reconciled once at the end: a legacy whole-DAG schedule otherwise starts firing for real
        # and reconcile then refuses to tier the DAG while that schedule stands.
        repaired_dags: set[DAG] = set()
        for saved_query in saved_queries:
            preferred = target_for(saved_query)
            target = clamp_to_bounds(saved_query, preferred)
            label = f"team {saved_query.team_id} {saved_query.name} ({saved_query.id})"

            if target is None:
                self.stdout.write(f"skipped {label}: no cadence satisfies both its sources and its consumers")
                counts[SKIPPED_REFUSED] = counts.get(SKIPPED_REFUSED, 0) + 1
                continue

            at = f"at {int(target.total_seconds())}s"
            if target != preferred:
                at += f" (asked for {int(preferred.total_seconds())}s, bounded by the DAG)"

            if not apply:
                self.stdout.write(f"would repair {label} {at}")
                counts[REPAIRED] = counts.get(REPAIRED, 0) + 1
                continue

            try:
                # Both writes or neither: a cadence on a node still typed `view` leaves the query
                # trapped, and neither call reaches Temporal, so nothing outside the DB to undo.
                with transaction.atomic():
                    written = apply_saved_query_frequency_target(saved_query, target, reconcile=False)
                    if written == 0:
                        self.stdout.write(f"skipped {label}: no DAG node to write a target to")
                        counts[SKIPPED_NO_NODE] = counts.get(SKIPPED_NO_NODE, 0) + 1
                        continue
                    update_node_type(saved_query, NodeType.MAT_VIEW)
                repaired_dags.update(
                    node.dag
                    for node in Node.objects.filter(team_id=saved_query.team_id, saved_query=saved_query)
                    .select_related("dag", "dag__team")
                    .exclude(dag__isnull=True)
                )
            except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as e:
                # The query's own declared interval can be faster than its sources allow, which is a
                # refusal to report rather than a failure to retry.
                self.stdout.write(f"skipped {label}: {e}")
                counts[SKIPPED_REFUSED] = counts.get(SKIPPED_REFUSED, 0) + 1
                continue
            except Exception as e:
                self.stdout.write(f"skipped {label}: {e}")
                logger.warning("repair_trapped_matviews_skipped", saved_query_id=str(saved_query.id), error=str(e))
                counts[SKIPPED_ERROR] = counts.get(SKIPPED_ERROR, 0) + 1
                continue

            self.stdout.write(f"repaired {label} {at}")
            counts[REPAIRED] = counts.get(REPAIRED, 0) + 1

        unreconciled: list[DAG] = []
        for dag in repaired_dags:
            try:
                reconcile_dag_schedules(dag)
            except Exception as e:
                # Re-running this command will not retry it: the retype took the query out of the
                # candidate set, so the only way back is reconciling the DAG directly.
                unreconciled.append(dag)
                self.stdout.write(f"failed to reconcile DAG {dag.id} (team {dag.team_id}): {e}")
                logger.warning("repair_trapped_matviews_reconcile_failed", dag_id=str(dag.id), error=str(e))

        verb = "repaired" if apply else "would repair"
        self.stdout.write(f"\n{len(saved_queries)} trapped queries, {verb} {counts.get(REPAIRED, 0)}")
        for outcome in (SKIPPED_NO_NODE, SKIPPED_REFUSED, SKIPPED_ERROR):
            if counts.get(outcome):
                self.stdout.write(f"  {outcome}: {counts[outcome]}")

        if unreconciled:
            recovery = "\n".join(
                f"  python manage.py reconcile_freshness_schedules --team-id {dag.team_id} --dag-id {dag.id}"
                for dag in unreconciled
            )
            raise CommandError(
                f"{len(unreconciled)} DAG(s) were retyped but not reconciled, and this command cannot "
                f"retry them. Reconcile each one directly:\n{recovery}"
            )
