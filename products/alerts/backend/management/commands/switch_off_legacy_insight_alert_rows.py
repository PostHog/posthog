from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.legacy_row_switch_off import switch_off_rows
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.legacy_row_switch_off_command import (
    add_switch_off_arguments,
    run_switch_off,
)


class Command(BaseCommand):
    help = (
        "Switch off the insight row of every insight alert the alerts platform owns, per team, in batches. "
        "The platform copy, which every reader shows, is not changed. Writes nothing without --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        add_switch_off_arguments(parser)

    def handle(self, *args: Any, **options: Any) -> None:
        run_switch_off(
            source_kind=SourceKind.INSIGHT, switch_off=switch_off_rows, options=options, write=self.stdout.write
        )
