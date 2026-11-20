"""The command-line surface each source shares for switching off its legacy rows of the alerts the platform owns.

Each source keeps its own command module, so `manage.py` finds it by name, and passes the function that
switches off its rows.
"""

import argparse
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from django.core.management.base import CommandError, CommandParser

from products.alerts_platform.backend.facade.api import switch_off_legacy_rows
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.created_at_backfill_command import add_copy_backfill_arguments


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def add_switch_off_arguments(parser: CommandParser) -> None:
    add_copy_backfill_arguments(parser)
    parser.add_argument("--batch-size", type=_positive, default=500, help="Rows per update.")


def run_switch_off(
    *,
    source_kind: SourceKind,
    switch_off: Callable[[int, Sequence[UUID], bool], int],
    options: dict[str, Any],
    write: Callable[[str], None],
) -> None:
    run = switch_off_legacy_rows(
        source_kind=source_kind,
        team_ids=options["team_ids"],
        switch_off=switch_off,
        batch_size=options["batch_size"],
        apply=options["apply"],
    )
    for line in run.report(source_kind, applied=options["apply"]):
        write(line)
    if run.failed_team_ids:
        raise CommandError(f"Failed for teams: {', '.join(map(str, run.failed_team_ids))}")
