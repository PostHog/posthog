from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from products.ai_observability.backend.model_breakdown_backfill import fold_model_breakdown


class Command(BaseCommand):
    help = "Fold provider prefixes and case into the model breakdown of AI observability dashboards that already exist"

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            action="append",
            dest="team_ids",
            help="Limit the backfill to this team. Repeat for several teams. Defaults to every team.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the change. Without it the command only reports what it would fold.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = fold_model_breakdown(team_ids=options["team_ids"], apply=options["apply"])
        verb = "folded" if options["apply"] else "would fold"

        self.stdout.write(
            f"{len(report.folded)} of {report.candidates} model tiles {verb}, "
            f"{len(report.skipped)} left alone because their query no longer matches the template"
        )
