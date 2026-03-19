from __future__ import annotations

from collections import defaultdict

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from posthog.product_db_router import get_product_db_routes


class Command(BaseCommand):
    help = "Run Django migrations for product-routed databases"

    def handle(self, *args, **options):
        get_product_db_routes.cache_clear()
        routes = get_product_db_routes()

        db_to_apps: dict[str, set[str]] = defaultdict(set)
        for route in routes:
            writer_alias = f"{route.database}_db_writer"
            if writer_alias in settings.DATABASES:
                db_to_apps[writer_alias].add(route.app_label)

        if not db_to_apps:
            self.stdout.write("No configured product databases found.")
            return

        for writer_alias, app_labels in sorted(db_to_apps.items()):
            self.stdout.write(f"Running product migrations on database '{writer_alias}'")
            for app_label in sorted(app_labels):
                call_command("migrate", app_label, database=writer_alias, interactive=False, verbosity=1)
