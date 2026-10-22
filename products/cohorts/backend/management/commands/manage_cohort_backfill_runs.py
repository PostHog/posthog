"""Ops tooling for the realtime cohort backfill run set, meant for a toolbox pod.

`inventory` lists every backfill run in an active status across all teams, says what each one is
waiting on, and emits the paste-ready `BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST` line for the runs
the finalizer would stamp. `terminalize` cancels the ones that can never finish, releasing the
uniqueness slot that otherwise blocks their cohort or team from backfilling again. Mutating actions
are dry run by default.

`audit` compares each stamped realtime cohort of one team against its batch population and flags the
ones whose `cohort_membership` rows are missing or far off. `--clear-stamps` takes them out of flag
routing and `--rerun` rebuilds them. It reads `BEHAVIORAL_COHORTS_READ_DATABASE_URL`.

Order matters when turning the finalizer on, because a readiness stamp cannot be undone:

  1. Deploy with `BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST` set to a verified list or `none`.
  2. Run `inventory` while the finalizer is still off, so the finalizable set holds still.
  3. Check each finalizable run by hand.
  4. `terminalize --classification seeding-stalled --classification orphaned --live-run`.
  5. Re-run `inventory` and set the allowlist line it prints.
  6. Turn on `BEHAVIORAL_BACKFILL_FINALIZER_ENABLED`, then watch
     `posthog_cohort_backfill_finalizer_held_runs{reason="not_allowlisted"}` drain as the list widens.
"""

import sys
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.serializers.json import DjangoJSONEncoder

import structlog

from products.cohorts.backend.backfill.allowlist import parse_run_allowlist
from products.cohorts.backend.backfill.audit import (
    DEFAULT_DIVERGENCE_THRESHOLD,
    CohortMembershipAuditRow,
    MembershipAuditReport,
    MembershipStoreNotConfigured,
    audit_team_membership,
    clear_readiness_stamps,
    create_rebuild_runs,
    open_realtime_membership_reader,
)
from products.cohorts.backend.backfill.inventory import (
    AGE_GATED_TERMINALIZE_CLASSIFICATIONS,
    DEFAULT_MAX_CHUNK_ATTEMPTS,
    DEFAULT_TERMINALIZE_CLASSIFICATIONS,
    RUN_CLASSIFICATIONS,
    SEEDER_OWNED_CLASSIFICATIONS,
    RunInventoryRow,
    allowlist_env_line,
    collect_run_inventory,
    stampable_now,
    summarize_inventory,
)
from products.cohorts.backend.backfill.runs import cancel_runs
from products.cohorts.backend.models.backfill import ACTIVE_COHORT_BACKFILL_RUN_STATUSES, CohortBackfillKind

logger = structlog.get_logger(__name__)

DEFAULT_REASON = "canceled via manage_cohort_backfill_runs"
DEFAULT_STALLED_FOR_HOURS = 6
MAX_RUNS_DEFAULT = 50
PRINT_LIMIT = 50
DRY_RUN_MESSAGE = "Dry run, nothing written. Re-run with --live-run to apply."


class Command(BaseCommand):
    help = (
        "Inventory the active cohort backfill runs, cancel the ones that can never finish, "
        "and audit stamped cohorts against their batch population."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        subparsers = parser.add_subparsers(dest="action", required=True)

        inventory = subparsers.add_parser("inventory", help="List and classify the active runs.")
        self._add_target_args(inventory)
        inventory.add_argument("--format", choices=["table", "json"], default="table")
        inventory.add_argument("--limit", type=int, default=None, help="Cap the runs listed per section.")

        terminalize = subparsers.add_parser("terminalize", help="Cancel the targeted runs.")
        self._add_target_args(terminalize)
        terminalize.add_argument("--reason", default=DEFAULT_REASON, help="Recorded on each canceled run.")
        terminalize.add_argument(
            "--include-finalizable",
            action="store_true",
            help="Also cancel runs the finalizer would stamp. Throws away a finished backfill.",
        )
        terminalize.add_argument(
            "--include-seeder-owned",
            action="store_true",
            help="Also cancel runs the seeder is still working. Throws away seeding progress.",
        )
        terminalize.add_argument("--live-run", action="store_true")
        terminalize.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
        terminalize.add_argument("--max-runs", type=int, default=MAX_RUNS_DEFAULT)

        audit = subparsers.add_parser(
            "audit", help="Find stamped realtime cohorts whose realtime membership is empty or far from batch."
        )
        audit.add_argument("--team-id", type=int, required=True)
        audit.add_argument("--cohort-ids", type=int, nargs="+", default=None)
        audit.add_argument(
            "--threshold",
            type=float,
            default=DEFAULT_DIVERGENCE_THRESHOLD,
            help="Flag a cohort when |realtime - batch| / batch is above this.",
        )
        audit.add_argument(
            "--clear-stamps",
            action="store_true",
            help="Null the flagged cohorts' readiness stamps, so flags stop reading their membership table.",
        )
        audit.add_argument(
            "--rerun", action="store_true", help="Create one team backfill run per kind the flagged cohorts need."
        )
        audit.add_argument(
            "--person-horizon-days",
            type=int,
            default=None,
            help="Horizon of a person-property rebuild run. Defaults to BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS.",
        )
        audit.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    def _add_target_args(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None)
        parser.add_argument("--kind", action="append", choices=list(CohortBackfillKind.values), default=None)
        parser.add_argument(
            "--status",
            action="append",
            choices=[status.value for status in ACTIVE_COHORT_BACKFILL_RUN_STATUSES],
            default=None,
            help="Only active statuses: this command drains the active set.",
        )
        parser.add_argument("--classification", action="append", choices=list(RUN_CLASSIFICATIONS), default=None)
        parser.add_argument("--run-id", action="append", default=None)
        parser.add_argument("--older-than-hours", type=float, default=None, help="Only runs created before this.")
        parser.add_argument(
            "--stalled-for-hours",
            type=float,
            default=DEFAULT_STALLED_FOR_HOURS,
            help="How long a seeding run may go without chunk progress before it reads as stalled.",
        )
        parser.add_argument(
            "--max-chunk-attempts",
            type=int,
            default=DEFAULT_MAX_CHUNK_ATTEMPTS,
            # Django cannot read the seeder's config, so the cap it retries chunks up to has to be
            # repeated here. Pass the deployed value if it differs from the seeder's default.
            help="The seeder's SEEDER_MAX_CHUNK_ATTEMPTS, used to spot chunks that can't be reclaimed.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["action"] == "inventory":
            self._inventory(options)
            return
        if options["action"] == "audit":
            self._audit(options)
            return
        self._terminalize(options)

    # -- inventory --------------------------------------------------------------

    def _inventory(self, options: dict[str, Any]) -> None:
        rows = self._collect(options)
        stampable = stampable_now(rows)
        if options["format"] == "json":
            # One document, no headings, so it pipes into jq.
            self.stdout.write(
                json.dumps(
                    {
                        "settings": self._settings_snapshot(),
                        "max_chunk_attempts": options["max_chunk_attempts"],
                        "summary": summarize_inventory(rows),
                        "runs": [asdict(row) for row in rows],
                        "allowlist_line": allowlist_env_line(stampable),
                    },
                    cls=DjangoJSONEncoder,
                )
            )
            return

        limit = PRINT_LIMIT if options["limit"] is None else options["limit"]
        self.stdout.write(self.style.MIGRATE_HEADING("Finalizer settings"))
        for name, value in self._settings_snapshot().items():
            self.stdout.write(f"  {name}={value}")
        self.stdout.write(f"  {self._classification_cap_line(options)}")

        summary = summarize_inventory(rows)
        teams = len({row.team_id for row in rows})
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\nActive runs by classification ({len(rows)} across {teams} team(s))")
        )
        for classification, count in summary.items():
            self.stdout.write(f"  {classification:<22}{count}")

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nFinalizable now ({len(stampable)}). These get stamped as soon as the finalizer is enabled."
            )
        )
        # Never truncated, unlike every other section. These are the runs the allowlist line below
        # carries, and a stamp cannot be undone, so the operator has to see each one to check it.
        self._print_rows(stampable, len(stampable))

        gated = [row for row in rows if row.classification == "finalizable" and row.finalizer_gated]
        if gated:
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"\nFinalizable but held by the person readiness gate ({len(gated)})")
            )
            self._print_rows(gated, limit)

        candidates = [row for row in rows if row.classification in DEFAULT_TERMINALIZE_CLASSIFICATIONS]
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nCancel candidates ({len(candidates)})"))
        self._print_rows(candidates, limit)

        self.stdout.write(self.style.MIGRATE_HEADING("\nAllowlist line. Paste it after checking each run above."))
        self.stdout.write(allowlist_env_line(stampable))

    def _print_rows(self, rows: list[RunInventoryRow], limit: int) -> None:
        for row in rows[:limit]:
            line = (
                f"  run={row.run_id} team={row.team_id} kind={row.backfill_kind} scope={row.scope} "
                f"cohort={row.cohort_id if row.cohort_id is not None else '-'} status={row.status} "
                f"age={_age(row.created_at)} parts={row.participations_open}/{row.participations_total} "
                f"chunks={row.chunks_confirmed}/{row.chunks_total}"
            )
            if row.evidence:
                line += f" why={row.evidence}"
            self.stdout.write(line)
        if len(rows) > limit:
            self.stdout.write(f"  ... and {len(rows) - limit} more")

    # -- terminalize ------------------------------------------------------------

    def _terminalize(self, options: dict[str, Any]) -> None:
        classifications = options["classification"]
        run_ids = options["run_id"]
        if not classifications and not run_ids:
            raise CommandError(
                "Pass --classification or --run-id. There is no cancel-everything mode. A good "
                f"starting point is {' '.join(f'--classification {name}' for name in DEFAULT_TERMINALIZE_CLASSIFICATIONS)}"
            )

        rows = self._collect(options)
        # Guard on what each targeted run actually is, not on what was asked for. Checking the
        # `--classification` values alone would let `--run-id` name a run in a protected
        # classification and skip every rule below.
        for classification in sorted({row.classification for row in rows}):
            if classification in SEEDER_OWNED_CLASSIFICATIONS and not options["include_seeder_owned"]:
                raise CommandError(
                    f"{classification} runs are still owned by the seeder, so canceling one races a live "
                    "worker and discards seeding progress. Target seeding-stalled instead, or pass "
                    "--include-seeder-owned to stop live work deliberately."
                )
            if classification in AGE_GATED_TERMINALIZE_CLASSIFICATIONS and options["older_than_hours"] is None:
                raise CommandError(f"{classification} runs are parked by design, so pass --older-than-hours too")
            if classification == "finalizable" and not options["include_finalizable"]:
                raise CommandError(
                    "finalizable runs are finished backfills the finalizer would stamp. "
                    "Pass --include-finalizable to throw that work away deliberately."
                )

        if not rows:
            self.stdout.write("No runs matched. Run `inventory` to see what is active.")
            return

        # Abort before the prompt, not after: an operator who mistargeted should not be asked to
        # confirm a sweep this command was never going to let through.
        if len(rows) > options["max_runs"]:
            raise CommandError(
                f"{len(rows)} runs matched, over the --max-runs cap of {options['max_runs']}. "
                "Narrow the targeting or raise the cap deliberately."
            )

        self.stdout.write(self.style.MIGRATE_HEADING(f"Runs to cancel ({len(rows)})"))
        self._print_rows(rows, PRINT_LIMIT)

        # The cap only shapes the `seeding-stalled` classification, so it is only worth flagging
        # before the confirmation when one of those runs is in the cancel set.
        if any(row.classification == "seeding-stalled" for row in rows):
            self.stdout.write(f"  {self._classification_cap_line(options)}")

        if not options["live_run"]:
            self.stdout.write(self.style.WARNING(DRY_RUN_MESSAGE))
            return

        self._confirm(f"Cancel {len(rows)} run(s)? Type 'cancel' to continue: ", "cancel", yes=options["yes"])

        classification_by_run = {row.run_id: row.classification for row in rows}
        outcome = cancel_runs(
            [(row.run_id, row.team_id) for row in rows],
            reason=options["reason"],
            allow_finalizable=options["include_finalizable"],
        )
        for run_id in outcome.cancelled_run_ids:
            logger.info(
                "manage_cohort_backfill_runs_cancelled",
                run_id=str(run_id),
                classification=classification_by_run[run_id],
                reason=options["reason"],
            )
        for run_id, refusal in outcome.refused:
            self.stdout.write(self.style.WARNING(f"  run={run_id} not canceled: {refusal}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Canceled {len(outcome.cancelled_run_ids)} run(s), "
                f"resolved {outcome.superseded_participations} participation(s), "
                f"refused {len(outcome.refused)}."
            )
        )

    # -- audit ------------------------------------------------------------------

    def _audit(self, options: dict[str, Any]) -> None:
        team_id: int = options["team_id"]
        if options["threshold"] < 0:
            raise CommandError("--threshold must be 0 or more")
        person_horizon_days: int = (
            settings.BEHAVIORAL_BACKFILL_PERSON_DEFAULT_HORIZON_DAYS
            if options["person_horizon_days"] is None
            else options["person_horizon_days"]
        )

        try:
            with open_realtime_membership_reader() as reader:
                report = audit_team_membership(
                    team_id, reader=reader, cohort_ids=options["cohort_ids"], threshold=options["threshold"]
                )
        except MembershipStoreNotConfigured as error:
            raise CommandError(str(error)) from error

        self._print_audit(report)
        clear_stamps: bool = options["clear_stamps"]
        rerun: bool = options["rerun"]
        if not clear_stamps and not rerun:
            if report.flagged:
                self.stdout.write(
                    "Pass --clear-stamps and --rerun to take the flagged cohorts out of flags and rebuild them."
                )
            return
        if not report.flagged:
            self.stdout.write("Nothing flagged, nothing to change.")
            return

        actions = [label for label, wanted in (("clear the stamps of", clear_stamps), ("rebuild", rerun)) if wanted]
        self._confirm(
            f"{' and '.join(actions).capitalize()} {len(report.flagged)} cohort(s) of team {team_id}? "
            "Type 'apply' to continue: ",
            "apply",
            yes=options["yes"],
        )

        # Stamps first, so readers stop routing the cohorts to the table before the rebuild starts.
        if clear_stamps:
            cleared = clear_readiness_stamps(report)
            self.stdout.write(
                self.style.SUCCESS(f"Cleared the readiness stamps of {len(cleared.cleared_cohort_ids)} cohort(s).")
            )
            if cleared.moved_cohort_ids:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Left {list(cleared.moved_cohort_ids)} alone, because their stamps changed after the audit."
                    )
                )
            if not rerun:
                self.stdout.write(
                    self.style.WARNING(
                        "  No run was created, so these cohorts stay out of flags until a run stamps them. "
                        "Run the audit with --rerun when the pipeline can rebuild them."
                    )
                )

        if rerun:
            for outcome in create_rebuild_runs(report, person_horizon_days=person_horizon_days):
                cohorts = list(outcome.cohort_ids)
                if outcome.run_id is not None:
                    self.stdout.write(self.style.SUCCESS(f"Created {outcome.kind} run {outcome.run_id} for {cohorts}."))
                else:
                    self.stdout.write(self.style.WARNING(f"No {outcome.kind} run for {cohorts}: {outcome.refusal}"))

    def _print_audit(self, report: MembershipAuditReport) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Stamped realtime cohorts of team {report.team_id}: {len(report.rows)}, "
                f"{len(report.flagged)} flagged at threshold {report.threshold}"
            )
        )
        header = ("cohort", "classification", "composed", "realtime", "batch", "batch_age", "needs", "stamps", "name")
        lines = [header, *(_audit_cells(row) for row in report.rows)]
        widths = [max(len(line[index]) for line in lines) for index in range(len(header))]
        for line in lines:
            self.stdout.write("  " + "  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip())
        for row in report.rows:
            if row.detail:
                self.stdout.write(f"  cohort {row.cohort_id}: {row.detail}")
        if report.skipped_cohort_ids:
            self.stdout.write(
                f"Not audited, because they are not stamped realtime cohorts of the team: {list(report.skipped_cohort_ids)}"
            )

    # -- shared -----------------------------------------------------------------

    def _collect(self, options: dict[str, Any]) -> list[RunInventoryRow]:
        older_than_hours = options["older_than_hours"]
        return collect_run_inventory(
            team_id=options["team_id"],
            kinds=options["kind"],
            statuses=options["status"],
            classifications=options["classification"],
            run_ids=_parse_run_ids(options["run_id"]),
            stalled_after=timedelta(hours=options["stalled_for_hours"]),
            older_than=None if older_than_hours is None else timedelta(hours=older_than_hours),
            max_chunk_attempts=options["max_chunk_attempts"],
        )

    def _classification_cap_line(self, options: dict[str, Any]) -> str:
        # The cap Django classified against is invisible in the run listing otherwise, so a
        # `seeding-stalled` reading looks identical whether it rests on the default or a value the
        # operator passed. Surfacing it lets them catch a deployed SEEDER_MAX_CHUNK_ATTEMPTS the
        # inventory undershot, which would misread a still-retryable chunk as provably wedged.
        return (
            f"max_chunk_attempts={options['max_chunk_attempts']} "
            "(assumed seeder cap; pass --max-chunk-attempts if the deployed SEEDER_MAX_CHUNK_ATTEMPTS is higher)"
        )

    def _settings_snapshot(self) -> dict[str, Any]:
        allowlist = parse_run_allowlist(settings.BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST)
        parsed = "every run" if allowlist is None else f"{len(allowlist)} run(s)"
        return {
            "BEHAVIORAL_BACKFILL_FINALIZER_ENABLED": settings.BEHAVIORAL_BACKFILL_FINALIZER_ENABLED,
            "BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED": settings.BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED,
            "BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS": settings.BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS,
            "BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST": (
                f"{settings.BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST} (matches {parsed})"
            ),
        }

    # Mirrors `manage_warehouse_queue._confirm`.
    def _confirm(self, prompt: str, keyword: str, *, yes: bool) -> None:
        if yes:
            return
        if not sys.stdin.isatty():
            raise CommandError("Refusing to apply changes non-interactively without --yes")
        if input(prompt).strip() != keyword:
            raise CommandError("Aborted.")


def _parse_run_ids(raw_ids: list[str] | None) -> list[UUID] | None:
    if not raw_ids:
        return None
    try:
        return [UUID(raw) for raw in raw_ids]
    except ValueError as error:
        raise CommandError(f"--run-id must be a UUID: {error}")


def _audit_cells(row: CohortMembershipAuditRow) -> tuple[str, ...]:
    return (
        str(row.cohort_id),
        row.classification,
        "yes" if row.composed else "no",
        "-" if row.realtime_members is None else str(row.realtime_members),
        "-" if row.batch_members is None else str(row.batch_members),
        "-" if row.batch_calculated_at is None else _age(row.batch_calculated_at),
        ",".join(row.needed_kinds) or "-",
        ",".join(name.removeprefix("last_").removesuffix("_at") for name in row.stamps.set_names()),
        row.name,
    )


def _age(moment: datetime) -> str:
    seconds = abs((datetime.now(UTC) - moment).total_seconds())
    if seconds < 120:
        return f"{int(seconds)}s"
    if seconds < 2 * 3600:
        return f"{int(seconds // 60)}m"
    return f"{seconds / 3600:.1f}h"
