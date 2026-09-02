import uuid
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import structlog

from posthog.models.team import Team

from products.data_modeling.backend.logic.cohort_scheduling import (
    MINUTES_PER_DAY,
    bucket_into_cadence_tiers,
    format_tier,
    tier_sort_key,
)
from products.data_modeling.backend.logic.freshness import clamp_to_source_floor, compute_effective_cadences
from products.data_modeling.backend.logic.node_frequency import (
    build_frequency_graph,
    schedulable_nodes,
    set_declared_anchor,
)
from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_schedules, tiered_schedules_enabled
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node

logger = structlog.get_logger(__name__)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKLY = timedelta(days=7)


class Command(BaseCommand):
    help = (
        "Pin (or clear) the schedule anchor on a DAG's nodes or a set of saved queries, then "
        "reconcile the affected DAGs' cadence-tier schedules. An anchored cohort fires at the "
        "given UTC time instead of its hash-spread slot: a daily node anchored at 00:00 runs at "
        "midnight UTC, a 6-hourly one at 00/06/12/18. Ordering is guaranteed only within one "
        "cohort (same cadence + same anchor); anchored cohorts at different cadences fire "
        "concurrently. Operator-only: anchors concentrate load, so hand them out deliberately."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--dag-id", type=str, default=None, help="Anchor every schedulable node in this DAG")
        parser.add_argument(
            "--saved-query-names", nargs="+", default=None, help="Anchor only these saved queries' nodes"
        )
        parser.add_argument(
            "--at",
            type=str,
            default=None,
            help="UTC time to anchor to, HH:MM (e.g. 00:00). Monthly-cadence nodes run every 30 days at this time, on the same 30-day grid their sources sync on",
        )
        parser.add_argument(
            "--on",
            type=str,
            default=None,
            choices=WEEKDAYS,
            help="Day of week for weekly-cadence nodes (required when the target set contains one)",
        )
        parser.add_argument(
            "--with-upstream",
            action="store_true",
            default=False,
            help="Also anchor each target's ancestor cone so the whole pipeline runs as one ordered cohort",
        )
        parser.add_argument("--clear", action="store_true", default=False, help="Clear anchors back to hash-spread")
        parser.add_argument(
            "--dry-run", action="store_true", default=False, help="Print the resulting tiers; write nothing"
        )

    def handle(self, *args, **options):
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team with id {options['team_id']}")
        if bool(options["dag_id"]) == bool(options["saved_query_names"]):
            raise CommandError("Pass exactly one of --dag-id or --saved-query-names")
        if options["clear"] == bool(options["at"]):
            raise CommandError("Pass exactly one of --at or --clear")
        if options["clear"] and options["on"]:
            raise CommandError("--on has no effect with --clear")
        if not tiered_schedules_enabled(team):
            raise CommandError(
                f"Team {team.pk} is not on the tiered-schedules flag; anchors only apply to cadence-tier schedules"
            )

        anchor = None if options["clear"] else self._parse_anchor(options["at"], options["on"])
        nodes_by_dag = self._resolve_target_nodes(team, options)

        # Validate every DAG before writing to any: a refusal on the second DAG must not leave the
        # first one already anchored and reconciled.
        plans: list[tuple[DAG, set[str], str]] = []
        for dag, node_ids in sorted(nodes_by_dag.items(), key=lambda kv: str(kv[0].id)):
            graph = build_frequency_graph(dag)
            effective = compute_effective_cadences(
                nodes=graph.nodes, edges=graph.edges, declared_targets=graph.declared_targets
            )
            effective, _clamped = clamp_to_source_floor(
                effective, edges=graph.edges, source_intervals=graph.source_intervals
            )

            if options["with_upstream"]:
                node_ids = self._expand_with_upstream(graph.edges, node_ids, graph.nodes)
                cadences = {cadence for node_id in node_ids if (cadence := effective.get(node_id)) is not None}
                # clearing cannot create ordering expectations, so it must stay possible
                # on a cone whose cadences have drifted apart since it was anchored
                if anchor is not None and len(cadences) > 1:
                    labels = ", ".join(str(c) for c in sorted(cadences))
                    raise CommandError(
                        f"DAG {dag.name} ({dag.id}): the upstream cone spans cadences ({labels}), so the "
                        "anchored cohorts would fire concurrently instead of in dependency order. Align the "
                        "cone's targets first, or anchor each cadence's nodes explicitly."
                    )

            if anchor is not None and options["on"] is None:
                weekly = [node_id for node_id in node_ids if effective.get(node_id) == WEEKLY]
                if weekly:
                    raise CommandError(
                        f"DAG {dag.name} ({dag.id}): {len(weekly)} target node(s) are on a weekly cadence; "
                        "pass --on to pick their day instead of having one picked silently"
                    )

            anchors = dict(graph.declared_anchors)
            if anchor is None:
                for node_id in node_ids:
                    anchors.pop(node_id, None)
            else:
                anchors.update(dict.fromkeys(node_ids, anchor))
            tiers = bucket_into_cadence_tiers(effective, anchors)
            tier_line = "  ".join(
                f"{format_tier(tier)} x{len(members)}"
                for tier, members in sorted(tiers.items(), key=lambda kv: tier_sort_key(kv[0]))
            )
            plans.append((dag, node_ids, tier_line))

        infinitive, past = ("clear", "cleared") if anchor is None else ("anchor", "anchored")
        if options["dry_run"]:
            for dag, node_ids, tier_line in plans:
                self.stdout.write(
                    f"DAG {dag.name} ({dag.id}): would {infinitive} {len(node_ids)} node(s) → {tier_line}"
                )
            self.stdout.write("(dry run: nothing was written)")
            return

        for dag, node_ids, tier_line in plans:
            written = 0
            # locked so a concurrent frequency-target write on the same node cannot lose either
            # key of the shared properties blob
            with transaction.atomic():
                for node in Node.objects.select_for_update().filter(
                    dag=dag, id__in=[uuid.UUID(node_id) for node_id in node_ids]
                ):
                    set_declared_anchor(node, anchor)
                    written += 1
            # require_tiered makes reconcile skip an unconverted DAG; saying "reconciled" there
            # would tell the operator a pin took effect when it didn't
            if reconcile_dag_schedules(dag, require_tiered=True):
                self.stdout.write(f"DAG {dag.name} ({dag.id}): {past} {written} node(s), reconciled → {tier_line}")
            else:
                self.stdout.write(
                    f"DAG {dag.name} ({dag.id}): {past} {written} node(s), but the DAG is not on cadence-tier "
                    "schedules yet; anchors apply once it is converted (reconcile_freshness_schedules)"
                )

    def _parse_anchor(self, at: str, on: str | None) -> int:
        try:
            hour_text, minute_text = at.split(":")
            hour, minute = int(hour_text), int(minute_text)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            raise CommandError(f"--at must be HH:MM (24h UTC), got {at!r}")
        day = WEEKDAYS.index(on) if on is not None else 0
        return day * MINUTES_PER_DAY + hour * 60 + minute

    def _resolve_target_nodes(self, team: Team, options: dict) -> dict[DAG, set[str]]:
        nodes_by_dag: dict[DAG, set[str]] = defaultdict(set)
        if options["dag_id"]:
            try:
                dag = DAG.objects.get(team_id=team.pk, id=uuid.UUID(options["dag_id"]))
            except (DAG.DoesNotExist, ValueError):
                raise CommandError(f"No DAG {options['dag_id']!r} on team {team.pk}")
            for node_id in schedulable_nodes(dag).values_list("id", flat=True):
                nodes_by_dag[dag].add(str(node_id))
        else:
            names = options["saved_query_names"]
            queries = list(DataWarehouseSavedQuery.objects.filter(team_id=team.pk, name__in=names, deleted=False))
            missing = set(names) - {query.name for query in queries}
            if missing:
                raise CommandError(f"No saved query named: {', '.join(sorted(missing))}")
            nodes = Node.objects.filter(team_id=team.pk, saved_query__in=queries).select_related("dag")
            for node in nodes:
                nodes_by_dag[node.dag].add(str(node.id))
            if not nodes_by_dag:
                raise CommandError("The named saved queries have no DAG nodes to anchor")
        return dict(nodes_by_dag)

    def _expand_with_upstream(
        self, edges: list[tuple[str, str]], node_ids: set[str], schedulable: set[str]
    ) -> set[str]:
        parents: dict[str, list[str]] = defaultdict(list)
        for upstream, downstream in edges:
            parents[downstream].append(upstream)
        cone = set(node_ids)
        frontier = list(node_ids)
        while frontier:
            for parent in parents.get(frontier.pop(), []):
                # source TABLE nodes have no schedule, so the cone stays within schedulable nodes
                if parent in schedulable and parent not in cone:
                    cone.add(parent)
                    frontier.append(parent)
        return cone
