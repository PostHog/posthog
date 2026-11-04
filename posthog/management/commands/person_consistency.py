"""Classify every person and mapping of one team, and write a report grouped by flavor and repair verb.

Usage:
    # One run: plan, both ClickHouse phases, the Postgres phase, and the report.
    python manage.py person_consistency scan --team-id 2 --dir /tmp/scan-2

    # A large team, split into chunks that run in parallel:
    python manage.py person_consistency plan --team-id 2 --dir /tmp/scan-2 --chunks 4
    python manage.py person_consistency scan --dir /tmp/scan-2 --chunk 0   # and 1, 2, 3
    python manage.py person_consistency scan --dir /tmp/scan-2 --phase postgres
    python manage.py person_consistency finalize --dir /tmp/scan-2

    # Repair the rows of one verb: a dry run first, then a canary, then the rest.
    python manage.py person_consistency repair --dir /tmp/scan-2 --verb republish
    python manage.py person_consistency repair --dir /tmp/scan-2 --verb republish --apply --limit 10
    python manage.py person_consistency repair --dir /tmp/scan-2 --verb republish --apply --resume <actions file>

Scans are read-only. A scan that stops resumes with --resume. The report (report.jsonl) holds one row per
key that is not ok, with the raw keys a repair needs; summary.json holds counts and hashed group names, and names no key.
A repair writes nothing without --apply, and records one action per key in an actions file.
Rescan after every repair run. The rescan confirms the fix, and finds any ClickHouse write lost when a run was
killed before it recorded its outcomes.
"""

import time
import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.divergence.team_scan import (
    PLAN_FILE,
    SUMMARY_FILE,
    IdRange,
    ScanError,
    create_plan,
    finalize,
    load_plan,
    run_chunk,
    run_postgres,
)
from posthog.models.person.divergence.verbs import VERBS, VerbError, run_verb


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value} must be 1 or more")
    return number


def _id_range(value: str) -> IdRange:
    start, _, end = value.partition(":")
    try:
        bounds = IdRange(start=int(start), end=int(end))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value} is not START:END") from exc
    if not 1 <= bounds.start < bounds.end:
        raise argparse.ArgumentTypeError(f"{value} must have 1 <= START < END")
    return bounds


class Command(BaseCommand):
    help = (
        "Classify every person and mapping of one team into a report grouped by repair verb, and repair them. "
        "Scans are read-only; repair writes only with --apply."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True, metavar="action")

        plan = actions.add_parser("plan", help="Create a scan directory and split the team into chunks.")
        self._add_dir(plan)
        self._add_plan_options(plan, team_required=True)
        plan.add_argument(
            "--chunks",
            type=_positive_int,
            default=1,
            help="ClickHouse key ranges that can run in parallel (default: %(default)s).",
        )

        scan = actions.add_parser(
            "scan",
            help="Run a scan. Without --chunk and --phase it runs every phase and writes the report.",
        )
        self._add_dir(scan)
        self._add_plan_options(scan, team_required=False)
        scan.add_argument("--chunk", type=int, default=None, help="Run only this chunk's ClickHouse phases.")
        scan.add_argument(
            "--phase",
            choices=["all", "clickhouse", "postgres"],
            default="all",
            help="clickhouse runs the chunks; postgres runs after every chunk finished (default: %(default)s).",
        )
        scan.add_argument(
            "--pg-id-range",
            type=_id_range,
            default=None,
            help="START:END. Limit the Postgres phase to person ids in [START, END), to split it across runs.",
        )
        scan.add_argument("--resume", action="store_true", help="Continue runs that already started.")
        scan.add_argument(
            "--pause-seconds",
            type=float,
            default=0.2,
            help="Pause between pages, to limit load on ClickHouse and personhog (default: %(default)s).",
        )

        repair = actions.add_parser(
            "repair",
            help="DRY RUN unless --apply is passed. Repair the report rows that name one verb.",
        )
        self._add_dir(repair)
        repair.add_argument("--verb", choices=sorted(VERBS), required=True, help="The repair to run.")
        repair.add_argument("--group", action="append", default=[], help="Only rows of this group. Repeatable.")
        repair.add_argument("--key", action="append", default=[], help="Only rows with this key. Repeatable.")
        repair.add_argument(
            "--pair",
            action="append",
            default=[],
            metavar="OLD_UUID>NEW_UUID",
            help="fold or merge: repair an ambiguous old person into this survivor. Repeatable.",
        )
        repair.add_argument("--limit", type=_positive_int, default=None, help="At most this many rows, for a canary.")
        repair.add_argument("--apply", action="store_true", help="Write. Without it the repair only reports.")
        repair.add_argument(
            "--max-calls-per-second",
            type=float,
            default=20.0,
            help="Personhog write calls per second (default: %(default)s).",
        )
        repair.add_argument(
            "--resume",
            type=Path,
            default=None,
            help="An actions file of an earlier run: append to it and skip the keys it records as done.",
        )
        repair.add_argument(
            "--force",
            action="store_true",
            help="bury: tombstone new persons even past the share limit that protects a team needing a restore.",
        )

        final = actions.add_parser("finalize", help="Join every run's rows into report.jsonl and summary.json.")
        self._add_dir(final)
        final.add_argument(
            "--partial", action="store_true", help="Write the report even if some runs have not finished."
        )

    @staticmethod
    def _add_dir(parser: CommandParser) -> None:
        parser.add_argument("--dir", type=Path, required=True, help="The scan directory.")

    @staticmethod
    def _add_plan_options(parser: CommandParser, *, team_required: bool) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=team_required,
            default=None,
            help="Team to scan." + ("" if team_required else " Creates a one-chunk plan when --dir has none."),
        )
        parser.add_argument(
            "--purged-at",
            type=_parse_utc,
            default=None,
            help="When the team's Postgres persons were purged; dates each ghost as after_purge or historical.",
        )
        parser.add_argument(
            "--ch-page-rows",
            type=_positive_int,
            default=100_000,
            help="ClickHouse rows per page. Each page also reads about one granule per part, which larger pages "
            "amortize (default: %(default)s).",
        )
        parser.add_argument(
            "--pg-page-size",
            type=_positive_int,
            default=5_000,
            help="Postgres persons per page, at most 10000 (default: %(default)s).",
        )

    def _log(self, message: str) -> None:
        self.stdout.write(f"{time.strftime('%H:%M:%S')} {message}")
        self.stdout.flush()

    def handle(self, *args: Any, **options: Any) -> None:
        with tags_context(product=Product.INTERNAL, feature=Feature.MANAGEMENT_COMMAND):
            try:
                if options["action"] == "plan":
                    self._plan(options, chunks=options["chunks"])
                elif options["action"] == "scan":
                    self._scan(options)
                elif options["action"] == "repair":
                    self._repair(options)
                else:
                    self._finalize(options["dir"], partial=options["partial"])
            except (ScanError, VerbError) as exc:
                raise CommandError(str(exc)) from exc

    def _plan(self, options: dict[str, Any], *, chunks: int) -> None:
        if options["pg_page_size"] > 10_000:
            raise CommandError("--pg-page-size must be at most 10000")
        plan = create_plan(
            options["dir"],
            options["team_id"],
            chunks=chunks,
            purged_at=options["purged_at"],
            ch_page_rows=options["ch_page_rows"],
            pg_page_size=options["pg_page_size"],
        )
        self._log(f"plan: team {plan.team_id}, {len(plan.chunks)} chunks, team exists {plan.team_exists}")

    def _scan(self, options: dict[str, Any]) -> None:
        scan_dir: Path = options["dir"]
        chunk, phase = options["chunk"], options["phase"]
        if chunk is not None and phase == "postgres":
            raise CommandError("--chunk selects ClickHouse phases; drop it to run the Postgres phase")
        if options["pg_id_range"] is not None and phase != "postgres":
            raise CommandError("--pg-id-range applies to --phase postgres only")
        if not (scan_dir / PLAN_FILE).exists():
            if options["team_id"] is None:
                raise CommandError(f"{scan_dir} has no plan; pass --team-id to create one, or run plan first")
            self._plan(options, chunks=1)
        plan = load_plan(scan_dir)
        if options["team_id"] is not None and options["team_id"] != plan.team_id:
            raise CommandError(f"{scan_dir} holds a scan of team {plan.team_id}, not {options['team_id']}")
        run_options = {"resume": options["resume"], "pause_seconds": options["pause_seconds"], "log": self._log}

        if phase in ("all", "clickhouse"):
            for index in [chunk] if chunk is not None else range(len(plan.chunks)):
                run_chunk(scan_dir, index, **run_options)
        if phase == "postgres" or (phase == "all" and chunk is None):
            if plan.team_exists:
                run_postgres(scan_dir, id_range=options["pg_id_range"], **run_options)
            else:
                self._log(f"postgres: team {plan.team_id} does not exist, skipped")
        if phase == "all" and chunk is None:
            self._finalize(scan_dir, partial=False)

    def _finalize(self, scan_dir: Path, *, partial: bool) -> None:
        summary = finalize(scan_dir, partial=partial)
        rows = sum(entry["rows"] for entry in summary["reported"])
        verbs = ", ".join(
            f"{verb}={counts.get('person_rows', 0)}p/{counts.get('mapping_rows', 0)}m"
            for verb, counts in summary["verbs"].items()
        )
        self._log(
            f"report: {rows} rows, {summary['groups']['count']} groups, complete {summary['complete']}; "
            f"by verb {verbs or 'none'}; see {scan_dir / SUMMARY_FILE}"
        )

    def _repair(self, options: dict[str, Any]) -> None:
        scan_dir: Path = options["dir"]
        if not options["max_calls_per_second"] > 0:
            raise CommandError("--max-calls-per-second must be above 0")
        mode = "apply" if options["apply"] else "dry-run"
        actions_path = options["resume"] or scan_dir / (
            f"actions-{options['verb']}-{mode}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        )
        counts = run_verb(
            scan_dir,
            options["verb"],
            apply=options["apply"],
            actions_path=actions_path,
            resume=options["resume"] is not None,
            groups=options["group"],
            keys=options["key"],
            limit=options["limit"],
            max_calls_per_second=options["max_calls_per_second"],
            force=options["force"],
            pairs=options["pair"],
            log=self._log,
        )
        outcomes = ", ".join(f"{outcome}={n}" for outcome, n in sorted(counts.items())) or "nothing to do"
        label = "APPLY" if options["apply"] else "DRY RUN"
        self._log(f"{options['verb']} {label}: {outcomes}; actions in {actions_path}")
        if not options["apply"]:
            self._log("Dry run: nothing was written. Pass --apply to write.")
        if counts.get("undelivered"):
            raise CommandError("Some ClickHouse messages were not delivered; rerun with --resume")
