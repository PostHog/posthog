import json
from argparse import ArgumentParser
from uuid import UUID

from django.core.management.base import BaseCommand

from products.context_layer.backend.facade.api import export_context_selections


class Command(BaseCommand):
    help = "Export internal context-selection evidence and raw task logs as JSON to stdout."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--task-id", type=UUID, required=True)

    def handle(self, *args, **options) -> None:
        self.stdout.write(json.dumps(export_context_selections(options["team_id"], options["task_id"]), default=str))
