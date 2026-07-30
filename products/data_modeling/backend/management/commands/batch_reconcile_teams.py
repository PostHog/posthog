import json
import dataclasses
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.models.team import Team

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import schedulable_nodes
from products.data_modeling.backend.logic.schedule_reconcile import (
    convert_dag_to_tiers,
    delete_v1_saved_query_schedules,
    list_existing_schedule_ids,
    null_saved_query_intervals,
    preview_dag_schedules,
    tiered_schedules_enabled,
)
from products.data_modeling.backend.models.dag import DAG

logger = structlog.get_logger(__name__)

REPORT_MARKER = "=== BATCH RECONCILE REPORT JSON ==="


class Anomaly(Exception):
    """The team's state diverged from what the plan predicted; halts the batch."""


def _seconds(interval: timedelta) -> int:
    return int(interval.total_seconds())


class Command(BaseCommand):
    help = (
        "Reconcile a batch of teams onto tiered schedules with a built-in circuit breaker. "
        "Each team is planned read-only first (predicted tier set, clamps, invalid targets); "
        "with --apply the plan is executed and the live Temporal schedule set is verified "
        "against the prediction. Any divergence or error halts the batch before the next "
        "team. Emits a JSON report (after the marker line, and to --output when given) for "
        "the rollout tracker."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-ids", type=str, required=True, help="Comma-separated team ids, processed in order")
        parser.add_argument(
            "--apply", action="store_true", default=False, help="Execute the plan; default is plan-only"
        )
        parser.add_argument(
            "--default-interval-seconds",
            type=int,
            default=None,
            help="Target for nodes with no seedable cadence anywhere (must be a supported bucket)",
        )
        parser.add_argument("--output", type=str, default=None, help="Also write the JSON report to this path")

    def handle(self, *args, **options):
        try:
            team_ids = [int(part) for part in options["team_ids"].split(",") if part.strip()]
        except ValueError:
            raise CommandError(f"--team-ids must be comma-separated integers, got {options['team_ids']!r}")
        if not team_ids:
            raise CommandError("--team-ids is empty")

        apply = options["apply"]
        default = (
            timedelta(seconds=options["default_interval_seconds"])
            if options["default_interval_seconds"] is not None
            else None
        )

        report: dict = {"apply": apply, "halted": False, "halt_reason": None, "teams": []}
        halted = False
        for team_id in team_ids:
            if halted:
                report["teams"].append({"team_id": team_id, "status": "skipped", "anomalies": [], "dags": []})
                continue
            record: dict = {"team_id": team_id, "status": "planned", "dags": [], "anomalies": []}
            report["teams"].append(record)
            try:
                self._process_team(team_id, record, apply=apply, default=default)
                if apply:
                    record["status"] = "applied"
                self.stdout.write(f"team {team_id}: {record['status']}")
            except Anomaly as err:
                record["status"] = "anomaly"
                record["anomalies"].append(str(err))
                report["halted"] = True
                report["halt_reason"] = f"team {team_id}: {err}"
                halted = True
                self.stderr.write(self.style.ERROR(f"HALT: team {team_id}: {err}"))
            except Exception as err:
                logger.exception("Unexpected error reconciling team", team_id=team_id)
                record["status"] = "anomaly"
                record["anomalies"].append(f"unexpected error: {err!r}")
                report["halted"] = True
                report["halt_reason"] = f"team {team_id}: unexpected error: {err!r}"
                halted = True
                self.stderr.write(self.style.ERROR(f"HALT: team {team_id}: unexpected error: {err!r}"))

        payload = json.dumps(report, indent=1)
        if options["output"]:
            Path(options["output"]).write_text(payload)
        self.stdout.write(REPORT_MARKER)
        self.stdout.write(payload)

    def _process_team(self, team_id: int, record: dict, *, apply: bool, default: timedelta | None) -> None:
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise Anomaly("team does not exist")
        record["organization_id"] = str(team.organization_id)
        if apply and not tiered_schedules_enabled(team):
            raise Anomaly("team's org is not on the tiered-schedules flag")

        dag_list = list(DAG.objects.filter(team_id=team_id))
        if not dag_list:
            record["note"] = "no DAGs"
            return

        plans = []
        for dag in dag_list:
            preview = preview_dag_schedules(dag, seed=True)
            dag_record = {
                "dag_id": str(dag.id),
                "name": dag.name,
                "planned_tiers": sorted(_seconds(t) for t in preview.desired_tiers),
                "tier_node_counts": {str(_seconds(t)): len(nodes) for t, nodes in preview.desired_tiers.items()},
                "to_create": sorted(preview.plan.to_create),
                "to_update": sorted(preview.plan.to_update),
                "to_delete": sorted(preview.plan.to_delete),
                "clamped": [
                    {
                        **dataclasses.asdict(c),
                        "demanded": _seconds(c.demanded),
                        "source_floor": _seconds(c.source_floor),
                        "clamped_to": _seconds(c.clamped_to),
                    }
                    for c in preview.clamped
                ],
                "invalid_targets": [c.node_id for c in preview.invalid_targets],
                "unsupported_tiers": [_seconds(t) for t in preview.unsupported_tiers],
            }
            record["dags"].append(dag_record)
            plans.append((dag, preview, dag_record))
            if preview.unsupported_tiers:
                raise Anomaly(f"DAG {dag.name}: unsupported tier(s) {[_seconds(t) for t in preview.unsupported_tiers]}")
            if preview.invalid_targets:
                raise Anomaly(f"DAG {dag.name}: {len(preview.invalid_targets)} declared target(s) outside their bounds")

        if not apply:
            return

        # Seed every DAG before sweeping any intervals: a query in two DAGs seeds from the shared
        # interval, so sweeping/nulling mid-loop would corrupt the other DAG's seed.
        for dag, _preview, dag_record in plans:
            dag_record["seeded"] = convert_dag_to_tiers(dag, default=default)
        for dag, _preview, dag_record in plans:
            nodes = list(schedulable_nodes(dag).select_related("saved_query"))
            sq_ids = [str(node.saved_query_id) for node in nodes if node.saved_query_id is not None]
            failed = delete_v1_saved_query_schedules(nodes, team_id=dag.team_id, dag_id=str(dag.id))
            swept = [sq_id for sq_id in sq_ids if sq_id not in failed]
            dag_record["v1_swept"] = len(swept)
            dag_record["intervals_cleared"] = null_saved_query_intervals(dag, only_saved_query_ids=swept)
            if failed:
                raise Anomaly(f"DAG {dag.name}: {len(failed)} v1 schedule(s) failed to delete")

        for dag, preview, dag_record in plans:
            expected = {tier_schedule_id(str(dag.id), interval) for interval in preview.desired_tiers}
            actual = list_existing_schedule_ids(str(dag.id))
            dag_record["live_schedules"] = sorted(actual)
            if actual != expected:
                raise Anomaly(f"DAG {dag.name}: live schedule set {sorted(actual)} != planned {sorted(expected)}")
            dag_record["verified"] = True
