import json
import time
import dataclasses
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import structlog
from asgiref.sync import async_to_sync
from temporalio.service import RPCError, RPCStatusCode

from posthog.models.team import Team
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.schedule import a_schedule_exists

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import schedulable_nodes
from products.data_modeling.backend.logic.schedule_reconcile import (
    convert_dag_to_tiers,
    delete_v1_saved_query_schedules,
    null_saved_query_intervals,
    preview_dag_schedules,
    tiered_schedules_enabled,
)
from products.data_modeling.backend.models.dag import DAG

logger = structlog.get_logger(__name__)

REPORT_MARKER = "=== BATCH RECONCILE REPORT JSON ==="

RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BASE_WAIT_SECONDS = 10


class Anomaly(Exception):
    """The team's state diverged from what the plan predicted; halts the batch."""


def _seconds(interval: timedelta) -> int:
    return int(interval.total_seconds())


@async_to_sync
async def _verify_schedules(expected: list[str], deleted: list[str]) -> tuple[list[str], list[str]]:
    """Point-read every id: planned schedules must exist, swept ones must be gone. Listing
    would go through the eventually-consistent visibility store and can return a pre-apply
    snapshot, halting the batch on a conversion that actually succeeded."""
    temporal = await async_connect()
    missing = [sid for sid in expected if not await a_schedule_exists(temporal, sid)]
    lingering = [sid for sid in deleted if await a_schedule_exists(temporal, sid)]
    return missing, lingering


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
        parser.add_argument("--output", type=str, default=None, help="Also write the JSON report to this path")

    def handle(self, *args, **options):
        try:
            team_ids = [int(part) for part in options["team_ids"].split(",") if part.strip()]
        except ValueError:
            raise CommandError(f"--team-ids must be comma-separated integers, got {options['team_ids']!r}")
        if not team_ids:
            raise CommandError("--team-ids is empty")

        apply = options["apply"]
        report: dict = {"apply": apply, "halted": False, "halt_reason": None, "teams": []}
        halted = False
        for team_id in team_ids:
            if halted:
                report["teams"].append({"team_id": team_id, "status": "skipped", "anomalies": [], "dags": []})
                continue
            record: dict = {"team_id": team_id, "status": "planned", "dags": [], "anomalies": []}
            report["teams"].append(record)
            try:
                self._process_team_with_retry(team_id, record, apply=apply)
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

    def _process_team_with_retry(self, team_id: int, record: dict, *, apply: bool) -> None:
        """Retry a rate-limited team instead of halting the batch: both phases are
        idempotent per team (plan is read-only; re-applying converges on the same
        tier set), so on RESOURCE_EXHAUSTED the whole team is safely re-run after
        a backoff. Any other error propagates to the per-team handler."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                self._process_team(team_id, record, apply=apply)
                return
            except RPCError as err:
                if err.status != RPCStatusCode.RESOURCE_EXHAUSTED or attempt == RATE_LIMIT_RETRIES:
                    raise
                wait = RATE_LIMIT_BASE_WAIT_SECONDS * (2**attempt)
                self.stderr.write(f"team {team_id}: temporal rate limited, retrying in {wait}s")
                record["dags"].clear()
                time.sleep(wait)

    def _process_team(self, team_id: int, record: dict, *, apply: bool) -> None:
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
            dag_record: dict = {
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
                # pre-existing declared-target drift is common and non-blocking (the effective
                # cadence wins; floor violations clamp at schedule time), so it is reported for
                # review rather than halting the batch
                "invalid_targets": [
                    {
                        "node_id": c.node_id,
                        "declared": _seconds(c.declared),
                        "source_floor": _seconds(c.source_floor),
                        "consumer_ceiling": _seconds(c.consumer_ceiling) if c.consumer_ceiling is not None else None,
                    }
                    for c in preview.invalid_targets
                ],
                "unsupported_tiers": [_seconds(t) for t in preview.unsupported_tiers],
            }
            record["dags"].append(dag_record)
            plans.append((dag, preview, dag_record))
            if preview.unsupported_tiers:
                raise Anomaly(f"DAG {dag.name}: unsupported tier(s) {[_seconds(t) for t in preview.unsupported_tiers]}")

        if not apply:
            return

        # Seed every DAG before sweeping any intervals: a query in two DAGs seeds from the shared
        # interval, so sweeping/nulling mid-loop would corrupt the other DAG's seed.
        for dag, _preview, dag_record in plans:
            dag_record["seeded"] = convert_dag_to_tiers(dag)
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
            expected = sorted(tier_schedule_id(str(dag.id), interval) for interval in preview.desired_tiers)
            missing, lingering = _verify_schedules(expected, sorted(preview.plan.to_delete))
            dag_record["verified"] = not missing and not lingering
            if missing or lingering:
                raise Anomaly(
                    f"DAG {dag.name}: missing planned schedule(s) {missing}; lingering swept schedule(s) {lingering}"
                )
