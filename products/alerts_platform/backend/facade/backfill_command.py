"""The command-line surface a source's backfill shares: which alerts to copy, and how to stop them.

Each source keeps its own command module, so `manage.py` finds it by name, and subclasses this to
supply the copy and the stop.
"""

from collections.abc import Collection
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError


class BackfillResult(Protocol):
    # Read-only, so a source's frozen counts satisfy it.
    @property
    def created(self) -> int: ...
    @property
    def updated(self) -> int: ...
    @property
    def skipped(self) -> int: ...
    @property
    def failed(self) -> int: ...


class PlatformBackfillCommand(BaseCommand):
    """`--team-id`, `--sample-percent`, `--ids-file` and `--disable`, the same for every source."""

    source_name: str
    sample_unit: str

    def backfill(
        self, *, team_id: int | None, sample_percent: int, alert_ids: Collection[UUID] | None
    ) -> BackfillResult:
        raise NotImplementedError

    def disable(self, *, team_id: int | None, alert_ids: Collection[UUID] | None) -> int:
        raise NotImplementedError

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Copy one team's configurations only.")
        parser.add_argument(
            "--sample-percent",
            type=int,
            default=100,
            help=f"Copy only this percentage of {self.sample_unit}s, chosen by {self.sample_unit} id so a rerun picks the same ones.",
        )
        parser.add_argument(
            "--ids-file",
            default=None,
            help=f"Copy only the {self.source_name} alerts whose ids this file lists, one per line.",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help=f"Copy nothing. Switch off the existing {self.source_name} copies instead, keeping their history.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["sample_percent"] != 100 and (options["disable"] or options["ids_file"] is not None):
            raise CommandError("--disable and --ids-file name what they act on and take no --sample-percent")
        alert_ids = _alert_ids(options["ids_file"])
        if options["disable"]:
            disabled = self.disable(team_id=options["team_id"], alert_ids=alert_ids)
            self.stdout.write(f"Disabled {disabled}")
            return
        try:
            counts = self.backfill(
                team_id=options["team_id"], sample_percent=options["sample_percent"], alert_ids=alert_ids
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f"Created {counts.created}, updated {counts.updated}, skipped {counts.skipped}, failed {counts.failed}"
        )


def _alert_ids(path: str | None) -> list[UUID] | None:
    if path is None:
        return None
    try:
        return [UUID(line.strip()) for line in Path(path).read_text().splitlines() if line.strip()]
    except ValueError as error:
        raise CommandError(f"{path} must hold one alert id per line: {error}") from error
