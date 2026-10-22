"""Classify every person and mapping of one team, and write a report grouped by flavor and repair verb.

Usage:
    # One run: plan, both ClickHouse phases, the Postgres phase, and the report.
    python manage.py person_consistency scan --team-id 2 --dir /tmp/scan-2

    # A large team, split into chunks that run in parallel:
    python manage.py person_consistency plan --team-id 2 --dir /tmp/scan-2 --chunks 4
    python manage.py person_consistency scan --dir /tmp/scan-2 --chunk 0   # and 1, 2, 3
    python manage.py person_consistency scan --dir /tmp/scan-2 --phase postgres
    python manage.py person_consistency finalize --dir /tmp/scan-2

Read-only. A run that stops resumes with --resume. The report (report.jsonl) holds one row per key that
is not ok, with the raw keys a repair needs; summary.json holds counts and hashed group names, and names no key.
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
    help = "Read-only. Classify every person and mapping of one team and write a report grouped by repair verb."

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
                else:
                    self._finalize(options["dir"], partial=options["partial"])
            except ScanError as exc:
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
