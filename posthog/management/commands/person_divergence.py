"""Scan for persons whose ClickHouse rows disagree with the persons database.

Usage:
    python manage.py person_divergence scan hidden --output hidden.csv
    python manage.py person_divergence scan swept --output swept.csv
    python manage.py person_divergence scan stale --window-days 60 --output stale.csv

Scans only read.
"""

import csv
import time
import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.divergence import (
    HIDDEN_TEAM_STEP,
    STALE_TEAM_STEP,
    SWEPT_TEAM_STEP,
    DivergentPerson,
    ScanSummary,
    scan_hidden_persons,
    scan_stale_persons,
    scan_swept_persons,
)

_DIVERGENT_SCANS: dict[str, tuple[Callable[..., ScanSummary], int, str]] = {
    "hidden": (
        scan_hidden_persons,
        HIDDEN_TEAM_STEP,
        "Persons live in Postgres whose newest ClickHouse row is a legacy (version 100 or above) tombstone.",
    ),
    "swept": (
        scan_swept_persons,
        SWEPT_TEAM_STEP,
        "Persons live in Postgres whose ClickHouse rows were all lightweight-deleted after a legacy tombstone. "
        "Run it soon after a sweep: once ClickHouse merges remove those rows, no scan finds the person.",
    ),
    "stale": (
        scan_stale_persons,
        STALE_TEAM_STEP,
        "Persons whose live ClickHouse winner outranks Postgres, found through a late lower-version row.",
    ),
}


class Command(BaseCommand):
    help = "Scan for persons whose ClickHouse rows disagree with the persons database. Scans are read-only."

    def add_arguments(self, parser: CommandParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True, metavar="action")

        scan = actions.add_parser("scan", help="Read-only. Write what a scan finds to a CSV.")
        scans = scan.add_subparsers(dest="scan", required=True, metavar="scan")
        for name, (_, team_step, description) in _DIVERGENT_SCANS.items():
            divergent = scans.add_parser(name, help=description)
            self._add_output(divergent)
            self._add_team_range(divergent)
            divergent.add_argument(
                "--team-step", type=int, default=team_step, help="Team ids per ClickHouse query (default: %(default)s)."
            )
            if name == "stale":
                divergent.add_argument(
                    "--window-days",
                    type=int,
                    default=60,
                    help="Only persons written in the last N days (default: %(default)s).",
                )

    @staticmethod
    def _add_output(parser: CommandParser) -> None:
        parser.add_argument("--output", type=Path, required=True, help="CSV to create. Must not exist.")

    @staticmethod
    def _add_team_range(parser: CommandParser) -> None:
        parser.add_argument("--min-team-id", type=int, default=0, help="First team id, inclusive (default: 0).")
        parser.add_argument(
            "--max-team-id",
            type=int,
            default=None,
            help="Last team id, exclusive (default: the highest in ClickHouse).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        with tags_context(product=Product.INTERNAL, feature=Feature.MANAGEMENT_COMMAND):
            self._scan(options)

    def _log(self, message: str) -> None:
        self.stdout.write(f"{time.strftime('%H:%M:%S')} {message}")
        self.stdout.flush()

    def _scan(self, options: dict[str, Any]) -> None:
        name = options["scan"]
        with _open_output(options["output"]) as handle:
            if name in _DIVERGENT_SCANS:
                scan_fn, _, _ = _DIVERGENT_SCANS[name]
                extra = {"window_days": options["window_days"]} if name == "stale" else {}
                summary = scan_fn(
                    min_team_id=options["min_team_id"],
                    max_team_id=options["max_team_id"],
                    team_step=options["team_step"],
                    on_found=_csv_sink(handle, DivergentPerson),
                    log=self._log,
                    **extra,
                )
                self._log(
                    f"{name} scan: {summary.candidates} ClickHouse candidates, {summary.divergent} divergent, "
                    f"skipped teams {summary.skipped_team_ids}"
                )


def _open_output(path: Path) -> TextIO:
    try:
        return path.open("x", newline="")
    except FileExistsError as exc:
        raise CommandError(f"{path} already exists; choose a new --output") from exc


def _csv_sink(handle: TextIO, row_type: type[Any]) -> Callable[[Any], None]:
    writer = csv.DictWriter(handle, fieldnames=[field.name for field in dataclasses.fields(row_type)])
    writer.writeheader()

    def write(row: Any) -> None:
        writer.writerow(dataclasses.asdict(row))
        # Flush each row so a scan that dies part way keeps everything it reported.
        handle.flush()

    return write
