from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.logic.legacy_config_drift import registered_sources, report_drift


class Command(BaseCommand):
    help = (
        "Compare every setting of each platform-owned alert's source row with its platform copy. "
        "Writes nothing, and exits non-zero when any setting differs."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Report one team only.")
        parser.add_argument(
            "--source",
            choices=[kind.value for kind in registered_sources()],
            action="append",
            default=None,
            help="Report one source only. Repeat for several. Defaults to every source.",
        )
        parser.add_argument("--batch-size", type=int, default=500, help="Source rows read per query.")
        parser.add_argument("--sample-size", type=int, default=5, help="Alert ids listed per team and setting.")

    def handle(self, *args: Any, **options: Any) -> None:
        sources = [SourceKind(value) for value in options["source"] or ()] or list(registered_sources())
        report = report_drift(
            source_kinds=sources,
            team_id=options["team_id"],
            batch_size=options["batch_size"],
            sample_size=options["sample_size"],
            now=timezone.now(),
        )
        for drift in report.drifts:
            sample = ", ".join(str(alert_id) for alert_id in drift.sample_ids)
            self.stdout.write(
                f"team={drift.team_id} source={drift.source_kind.value} setting={drift.setting} "
                f"alerts={drift.count} sample=[{sample}]"
            )
        self.stdout.write(
            f"Compared {report.compared} platform-owned alerts across {', '.join(sources)}: "
            f"{report.drifted} differ from their source row"
        )
        if report.drifted:
            raise CommandError(f"{report.drifted} platform-owned alerts drifted from their source row", returncode=1)
