"""Audit stored membership; repair explicitly selected cohorts with resumable operations."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.serializers.json import DjangoJSONEncoder

import structlog

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.population import operation as operation_lifecycle
from products.cohorts.backend.population.reconcile import (
    MembershipAudit,
    audit_candidates,
    audit_cohort,
    log_audit,
    start_reconciliation,
)
from products.cohorts.backend.population.runner import dispatch_operation

logger = structlog.get_logger(__name__)

DEFAULT_LIMIT = 100
DRY_RUN_MESSAGE = "Dry run, nothing written. Re-run with --live-run to start the repairs."


class Command(BaseCommand):
    help = "Audit static cohort membership across the two stores, and repair the drift."

    def add_arguments(self, parser: CommandParser) -> None:
        subparsers = parser.add_subparsers(dest="action", required=True)

        audit = subparsers.add_parser("audit", help="Report the drift. Reads only.")
        audit.add_argument("--team-id", type=int, action="append", dest="team_ids")
        audit.add_argument("--since", help="Only cohorts created, calculated or errored on or after this date.")
        audit.add_argument(
            "--after-cohort-id",
            type=int,
            default=0,
            help="Resume point. Pass the `next-cursor` the previous batch printed.",
        )
        audit.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Cohorts to audit in this batch.")
        audit.add_argument("--format", choices=["table", "json"], default="table")

        repair = subparsers.add_parser("repair", help="Write the missing ClickHouse members into Postgres.")
        repair.add_argument("--cohort-id", type=int, action="append", dest="cohort_ids", required=True)
        repair.add_argument("--live-run", action="store_true", help="Actually start the repairs.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["action"] == "audit":
            self._audit(options)
        else:
            self._repair(options)

    def _audit(self, options: dict[str, Any]) -> None:
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        since = _parse_since(options.get("since"))
        cohorts = audit_candidates(
            team_ids=options.get("team_ids"),
            since=since,
            after_cohort_id=options["after_cohort_id"],
            limit=options["limit"],
        )
        if not cohorts:
            self.stdout.write("No static cohorts matched.")
            return

        audits = []
        for cohort in cohorts:
            audit = audit_cohort(cohort)
            log_audit(audit)
            audits.append(audit)

        if options["format"] == "json":
            self.stdout.write(json.dumps([asdict(audit) for audit in audits], cls=DjangoJSONEncoder))
        else:
            self._print_table(audits)

        drifting = [audit for audit in audits if audit.needs_repair]
        self.stdout.write("")
        self.stdout.write(f"{len(drifting)} of {len(audits)} cohorts need repair.")
        if drifting:
            self.stdout.write("Repair them with:")
            flags = " ".join(f"--cohort-id {audit.cohort_id}" for audit in drifting)
            self.stdout.write(f"  manage.py reconcile_static_cohort_membership repair {flags} --live-run")

        incomplete = [audit for audit in audits if audit.import_complete is not True]
        if incomplete:
            self.stdout.write(
                f"{len(incomplete)} cohorts have incomplete or unknown original population. "
                "Repair only restores the stored subset. Lost upload input requires the original file."
            )
        self.stdout.write(f"next-cursor: {cohorts[-1].pk}")

    def _repair(self, options: dict[str, Any]) -> None:
        cohort_ids = options["cohort_ids"]
        cohorts = list(Cohort.objects.filter(pk__in=cohort_ids, is_static=True, deleted=False).order_by("pk"))
        missing = sorted(set(cohort_ids) - {cohort.pk for cohort in cohorts})
        if missing:
            raise CommandError(f"Not live static cohorts: {missing}")

        started = 0
        for cohort in cohorts:
            audit = audit_cohort(cohort)
            log_audit(audit)
            if not audit.needs_repair:
                self.stdout.write(f"cohort {cohort.pk}: already consistent, skipping")
                continue

            self.stdout.write(
                f"cohort {cohort.pk} (team {cohort.team_id}): {audit.missing_from_postgres:,} resolvable members "
                f"missing from Postgres, {audit.unresolvable_members:,} unresolvable and skipped"
            )
            if not options["live_run"]:
                continue

            try:
                operation = start_reconciliation(cohort)
            except operation_lifecycle.CohortPopulationConflict as conflict:
                self.stdout.write(f"cohort {cohort.pk}: skipped, operation {conflict.operation.pk} is already running")
                continue

            dispatch_operation(operation.pk)
            started += 1
            self.stdout.write(f"cohort {cohort.pk}: started reconciliation {operation.pk}")

        if not options["live_run"]:
            self.stdout.write(DRY_RUN_MESSAGE)
        else:
            self.stdout.write(f"Started {started} reconciliations.")

    def _print_table(self, audits: list[MembershipAudit]) -> None:
        header = (
            f"{'cohort':>8} {'team':>7} {'ch':>8} {'resolvable':>11} {'pg':>8} "
            f"{'missing_pg':>11} {'ghosts':>7} {'import':>10}  name"
        )
        self.stdout.write(header)
        for audit in audits:
            self.stdout.write(
                f"{audit.cohort_id:>8} {audit.team_id:>7} {audit.clickhouse_members:>8} "
                f"{audit.resolvable_members:>11} {audit.postgres_members:>8} "
                f"{audit.missing_from_postgres:>11} {audit.unresolvable_members:>7} "
                f"{'unknown' if audit.import_complete is None else 'complete' if audit.import_complete else 'incomplete':>10}  {audit.name!r}"
            )


def _parse_since(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as err:
        raise CommandError(f"--since must be an ISO date or datetime, got {raw!r}") from err
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
