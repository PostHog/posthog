"""Scan for and repair persons whose ClickHouse rows disagree with the persons database.

Usage:
    python manage.py person_divergence scan hidden --output hidden.csv
    python manage.py person_divergence scan swept --output swept.csv
    python manage.py person_divergence scan stale --window-days 60 --output stale.csv
    python manage.py person_divergence scan sample --modulus 20000 --residue 7 --cutoff 2025-12-01 --output sample.csv
    python manage.py person_divergence scan team --team-id 2 --before 2026-08-01T00:00:00 --output team.csv
    python manage.py person_divergence repair --input hidden.csv --output actions.csv
    python manage.py person_divergence repair --input hidden.csv --output actions.csv --apply

While legacy (version 100 or above) tombstones remain in ClickHouse, run the hidden scan and repair
what it finds right before every ClickHouse deletion sweep, which deletes every row of those persons.
Run the swept scan soon after the sweep.
"""

import csv
import time
import argparse
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.divergence import (
    HIDDEN_TEAM_STEP,
    SAMPLE_TEAM_STEP,
    STALE_TEAM_STEP,
    SWEPT_TEAM_STEP,
    DivergentPerson,
    PersonRef,
    RepairAction,
    SampledPerson,
    ScanSummary,
    TeamCheck,
    check_team,
    repair_persons,
    scan_hidden_persons,
    scan_sample,
    scan_stale_persons,
    scan_swept_persons,
)

_DIVERGENT_SCANS: dict[str, tuple[Callable[..., ScanSummary], int, str]] = {
    "hidden": (
        scan_hidden_persons,
        HIDDEN_TEAM_STEP,
        "Persons live in Postgres whose newest ClickHouse row is a legacy (version 100 or above) tombstone. "
        "Run it right before every ClickHouse deletion sweep: the sweep deletes the rows of every person it finds.",
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


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class Command(BaseCommand):
    help = (
        "Scan for persons whose ClickHouse rows disagree with the persons database, and repair them. "
        "Scans are read-only. A repair is a dry run unless --apply is passed."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        actions = parser.add_subparsers(dest="action", required=True, metavar="action")

        scan = actions.add_parser("scan", help="Read-only. Write what a scan finds to a CSV.")
        scans = scan.add_subparsers(dest="scan", required=True, metavar="scan")
        for name, (_, team_step, description) in _DIVERGENT_SCANS.items():
            divergent = scans.add_parser(name, help=description)
            self._add_output(divergent)
            self._add_team_range(divergent)
            divergent.add_argument(
                "--team-step",
                type=_positive_int,
                default=team_step,
                help="Team ids per ClickHouse query (default: %(default)s).",
            )
            if name == "stale":
                divergent.add_argument(
                    "--window-days",
                    type=_positive_int,
                    default=60,
                    help="Only persons written in the last N days (default: %(default)s).",
                )

        sample = scans.add_parser(
            "sample", help="Classify a uniform sample of live ClickHouse persons against Postgres."
        )
        self._add_output(sample)
        self._add_team_range(sample)
        sample.add_argument(
            "--modulus",
            type=_positive_int,
            required=True,
            help="Sample the persons where cityHash64(id) %% MODULUS = RESIDUE.",
        )
        sample.add_argument("--residue", type=int, required=True, help="See --modulus.")
        sample.add_argument(
            "--team-step",
            type=_positive_int,
            default=SAMPLE_TEAM_STEP,
            help="Team ids per ClickHouse query (default: %(default)s).",
        )
        sample.add_argument(
            "--written-within-days",
            type=_positive_int,
            default=None,
            help="Only persons whose winner was written in the last N days.",
        )
        sample.add_argument(
            "--cutoff",
            type=_parse_utc,
            default=None,
            help="Split each class by whether the winner was written before this ISO date or datetime (UTC if no zone).",
        )

        team = scans.add_parser(
            "team", help="Per team, count how many old live ClickHouse persons and mappings Postgres still holds."
        )
        self._add_output(team)
        team.add_argument("--team-id", type=int, action="append", required=True, help="Team to check. Repeatable.")
        team.add_argument(
            "--sample-size",
            type=_positive_int,
            default=200,
            help="Persons and mappings per team (default: %(default)s).",
        )
        team.add_argument(
            "--before",
            type=_parse_utc,
            required=True,
            help="Only rows last written before this ISO datetime (UTC if no zone).",
        )

        repair_help = (
            "DRY RUN unless --apply is passed. Republish the Postgres state of the persons in --input, "
            "and their distinct ids, to ClickHouse where ClickHouse disagrees."
        )
        repair = actions.add_parser("repair", help=repair_help, description=repair_help)
        repair.add_argument(
            "--input", type=Path, required=True, help="A CSV with team_id and person_uuid columns, e.g. a scan output."
        )
        self._add_output(repair)
        repair.add_argument("--team-id", type=int, default=None, help="Only repair persons of this team.")
        repair.add_argument(
            "--apply",
            action="store_true",
            help="Write to Postgres and ClickHouse. Without it the repair only reports what it would do.",
        )
        repair.add_argument(
            "--include-stale",
            action="store_true",
            help="Also repair persons a scan classified stale. Their repair replaces the ClickHouse properties "
            "with the Postgres ones for good, so never use it on a team waiting for a restore from ClickHouse.",
        )
        repair.add_argument(
            "--max-writes-per-second",
            type=_positive_float,
            default=50.0,
            help="Divergent persons and distinct ids repaired per second, each one a Postgres write (default: %(default)s).",
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
            if options["action"] == "repair":
                self._repair(options)
            else:
                self._scan(options)

    def _log(self, message: str) -> None:
        self.stdout.write(f"{time.strftime('%H:%M:%S')} {message}")
        self.stdout.flush()

    def _scan(self, options: dict[str, Any]) -> None:
        name = options["scan"]
        # An empty team range scans nothing and would read as a clean fleet. The team scan takes no range.
        max_team_id = options.get("max_team_id")
        if max_team_id is not None and max_team_id <= options["min_team_id"]:
            raise CommandError("--max-team-id must be above --min-team-id")
        # A residue outside the modulus samples nothing and would read as a clean fleet.
        if name == "sample" and not 0 <= options["residue"] < options["modulus"]:
            raise CommandError(f"--residue must be between 0 and {options['modulus'] - 1}")
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
            elif name == "sample":
                sample_summary = scan_sample(
                    modulus=options["modulus"],
                    residue=options["residue"],
                    written_within_days=options["written_within_days"],
                    cutoff=options["cutoff"],
                    min_team_id=options["min_team_id"],
                    max_team_id=options["max_team_id"],
                    team_step=options["team_step"],
                    on_sampled=_csv_sink(handle, SampledPerson),
                    log=self._log,
                )
                counts = ", ".join(
                    f"{bucket.classification}/{bucket.era}={count}"
                    for bucket, count in sorted(
                        sample_summary.counts.items(), key=lambda item: (item[0].classification, item[0].era)
                    )
                )
                self._log(
                    f"sample scan: {sample_summary.sampled} persons: {counts}, "
                    f"skipped teams {sample_summary.skipped_team_ids}"
                )
            else:
                write = _csv_sink(handle, TeamCheck)
                for team_id in options["team_id"]:
                    result = check_team(team_id=team_id, sample_size=options["sample_size"], before=options["before"])
                    write(result)
                    self._log(
                        f"team {team_id}: persons live in Postgres {result.persons_live_in_postgres}/{result.persons_sampled}, "
                        f"mappings live in Postgres {result.distinct_ids_live_in_postgres}/{result.distinct_ids_sampled}"
                    )

    def _repair(self, options: dict[str, Any]) -> None:
        targets = _read_targets(options["input"], options["team_id"])
        apply = options["apply"]
        self._log(f"repair {'APPLY' if apply else 'DRY RUN'}: {len(targets)} persons from {options['input']}")
        with _open_output(options["output"]) as handle:
            summary = repair_persons(
                targets,
                apply=apply,
                include_stale=options["include_stale"],
                max_writes_per_second=options["max_writes_per_second"],
                on_action=_csv_sink(handle, RepairAction),
                log=self._log,
            )
        self._log(
            f"repair {'APPLY' if apply else 'DRY RUN'}: {summary.persons} persons, "
            f"person outcomes {summary.person_outcomes}, mapping outcomes {summary.mapping_outcomes}, "
            f"undelivered messages {summary.undelivered}"
        )
        if not apply:
            self._log("Dry run: nothing was written. Pass --apply to write.")
        if summary.undelivered:
            raise CommandError(f"{summary.undelivered} ClickHouse messages were not delivered; rerun the same input")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value} must be 1 or more")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if not number > 0:
        raise argparse.ArgumentTypeError(f"{value} must be above 0")
    return number


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
        # Flush each row so a scan or repair that dies part way keeps everything it reported.
        handle.flush()

    return write


def _read_targets(path: Path, team_id: int | None) -> list[PersonRef]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"team_id", "person_uuid"} - set(reader.fieldnames or [])
        if missing:
            raise CommandError(f"{path} has no {', '.join(sorted(missing))} column")
        targets: list[PersonRef] = []
        for line, row in enumerate(reader, start=2):
            try:
                target = PersonRef(team_id=int(row["team_id"]), person_uuid=str(UUID(row["person_uuid"])))
            # A short row leaves its missing cells as None, which raises TypeError instead of ValueError.
            except (TypeError, ValueError) as exc:
                raise CommandError(f"{path}:{line}: {exc}") from exc
            if team_id is None or target.team_id == team_id:
                targets.append(target)
    return targets
