from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.ownership.table_owners import OUTPUT_PATH, render_json, table_owners, unowned_report


class Command(BaseCommand):
    help = "Write rust/pgcollector/ownership/table_owners.json from the Django model registry and owners.yaml"

    def add_arguments(self, parser):
        parser.add_argument("--report", action="store_true", help="List tables with no owner instead of writing")

    def handle(self, *args, **options):
        repo_root = Path(settings.BASE_DIR)
        records = table_owners(repo_root)
        unowned = unowned_report(records)
        if options["report"]:
            self.stdout.write("\n".join(unowned))
            return
        out = repo_root / OUTPUT_PATH
        out.write_text(render_json(records))
        self.stdout.write(f"wrote {out} ({len(records)} tables, {len(unowned)} unowned)")
