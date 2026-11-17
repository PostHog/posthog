from django.core.management.base import BaseCommand

from posthog.temporal.workflow_catalog import CATALOG_PATH, render_catalog


class Command(BaseCommand):
    help = "Write the Temporal workflow type -> product catalog to posthog/temporal/workflow_catalog.json"

    def handle(self, *args, **options):
        CATALOG_PATH.write_text(render_catalog())
        self.stdout.write(f"Wrote {CATALOG_PATH}")
