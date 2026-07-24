"""Report whether a data-modeling node is actually materialized by a cadence-tier schedule.

Reads the live `node_ids` out of each execute-dag schedule's (encrypted) Temporal payload — the only
authoritative record of what a tier will run — and compares it against what a reconcile would
schedule for the node right now. Read-only. Run where the prod Temporal credentials live (the same
place `reconcile_freshness_schedules` runs), because it connects through the codec-configured client
to decrypt the payloads.

    python manage.py check_node_tier_schedule --team-id 2 --name managed_product_lifecycle
    python manage.py check_node_tier_schedule --team-id 2 --dag-id <uuid>        # every node in a DAG
"""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.temporal.common.client import async_connect

from products.data_modeling.backend.logic.tier_membership import (
    STALE_NEEDS_RECONCILE,
    LiveTier,
    classify_node,
    expected_tier_by_node,
    format_interval,
    read_live_tiers,
)
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node, NodeType


class Command(BaseCommand):
    help = "Show which cadence-tier schedule (if any) materializes a data-modeling node, from Temporal."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        selector = parser.add_mutually_exclusive_group()
        selector.add_argument("--node-id", help="Node UUID.")
        selector.add_argument("--saved-query-id", help="Saved query UUID (resolves to its node(s)).")
        selector.add_argument("--name", help="Node name (may match several across DAGs).")
        parser.add_argument(
            "--dag-id", help="Restrict to this DAG, or inspect all its nodes when no selector is given."
        )
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    def handle(self, *args: Any, **options: Any) -> None:
        team_id: int = options["team_id"]
        dag_id: str | None = options["dag_id"]

        nodes = self._resolve_nodes(team_id, options)
        if nodes:
            node_list = list(nodes)
            dag_ids = {str(node.dag_id) for node in nodes}
        elif dag_id:
            node_list = self._dag_nodes(team_id, dag_id)
            dag_ids = {dag_id}
        else:
            raise CommandError("No matching node — refine the selector, or pass --dag-id to inspect a whole DAG.")

        dags_by_id = {str(dag.id): dag for dag in DAG.objects.filter(team_id=team_id, id__in=dag_ids)}

        live_by_dag = self._read_live_tiers(dag_ids)
        # Compute each DAG's expected tiers once — the frequency graph is per-DAG, not per-node.
        expected_by_dag = {known_id: expected_tier_by_node(dag) for known_id, dag in dags_by_id.items()}

        statuses = []
        for node in node_list:
            dag = dags_by_id.get(str(node.dag_id))
            if dag is None:
                continue
            expected = expected_by_dag.get(str(node.dag_id), {}).get(str(node.id))
            statuses.append(
                classify_node(
                    node_id=str(node.id),
                    name=node.name,
                    node_type=node.type,
                    dag_id=str(node.dag_id),
                    dag_name=dag.name,
                    live_tiers=live_by_dag.get(str(node.dag_id), []),
                    expected_interval=expected,
                )
            )

        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "tiers": {
                            dag_id: [self._tier_dict(tier) for tier in tiers] for dag_id, tiers in live_by_dag.items()
                        },
                        "nodes": [status.__dict__ for status in statuses],
                    },
                    indent=2,
                )
            )
            return

        self._print_human(live_by_dag, dags_by_id, statuses)

    def _resolve_nodes(self, team_id: int, options: dict[str, Any]) -> list[Node]:
        qs = Node.objects.filter(team_id=team_id).exclude(type=NodeType.TABLE)
        if options["node_id"]:
            qs = qs.filter(id=options["node_id"])
        elif options["saved_query_id"]:
            qs = qs.filter(saved_query_id=options["saved_query_id"])
        elif options["name"]:
            qs = qs.filter(name=options["name"])
        else:
            return []
        if options["dag_id"]:
            qs = qs.filter(dag_id=options["dag_id"])
        return list(qs.select_related("dag"))

    def _dag_nodes(self, team_id: int, dag_id: str) -> list[Node]:
        return list(
            Node.objects.filter(team_id=team_id, dag_id=dag_id).exclude(type=NodeType.TABLE).select_related("dag")
        )

    @staticmethod
    @async_to_sync
    async def _read_live_tiers(dag_ids: set[str]) -> dict[str, list[LiveTier]]:
        temporal = await async_connect()
        return {dag_id: await read_live_tiers(temporal, dag_id) for dag_id in dag_ids}

    @staticmethod
    def _tier_dict(tier: LiveTier) -> dict[str, Any]:
        return {
            "schedule_id": tier.schedule_id,
            "interval_seconds": tier.interval_seconds,
            "covers_whole_dag": tier.covers_whole_dag,
            "node_count": None if tier.node_ids is None else len(tier.node_ids),
        }

    def _print_human(
        self,
        live_by_dag: dict[str, list[LiveTier]],
        dags_by_id: dict[str, DAG],
        statuses: list[Any],
    ) -> None:
        for dag_id, tiers in live_by_dag.items():
            dag_name = dags_by_id[dag_id].name if dag_id in dags_by_id else "?"
            self.stdout.write(f"\nDAG {dag_name} ({dag_id}) — {len(tiers)} live execute-dag schedule(s):")
            for tier in sorted(tiers, key=lambda t: (t.interval_seconds is None, t.interval_seconds or 0)):
                count = "whole DAG" if tier.node_ids is None else f"{len(tier.node_ids)} nodes"
                self.stdout.write(f"  {format_interval(tier.interval_seconds):>10}  {tier.schedule_id}  ({count})")

        self.stdout.write("")
        for status in statuses:
            live = ", ".join(format_interval(i) for i in status.live_intervals) or "—"
            expected = (
                format_interval(status.expected_interval) if status.expected_interval is not None else "none (opt-out)"
            )
            marker = " ⚠️" if status.verdict == STALE_NEEDS_RECONCILE else ""
            self.stdout.write(
                f"{status.name} [{status.node_type}] {status.node_id}\n"
                f"    live tier: {live} | reconcile would schedule: {expected} | verdict: {status.verdict}{marker}"
            )
