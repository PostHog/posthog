from __future__ import annotations

from collections import defaultdict

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

import psycopg
from psycopg import sql

from posthog.product_db_router import get_product_db_routes


def ensure_database_exists(db_alias: str) -> None:
    db_settings = settings.DATABASES[db_alias]
    target_db = db_settings["NAME"]

    with psycopg.connect(
        dbname="postgres",
        host=db_settings.get("HOST") or "localhost",
        port=int(db_settings.get("PORT") or 5432),
        user=db_settings.get("USER") or "posthog",
        password=db_settings.get("PASSWORD") or "posthog",
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            if cur.fetchone():
                return

            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            owner = db_settings.get("USER")
            if owner:
                cur.execute(
                    sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                        sql.Identifier(target_db),
                        sql.Identifier(owner),
                    )
                )


class Command(BaseCommand):
    help = "Run Django migrations for product-routed databases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ensure-databases",
            action="store_true",
            help="Create missing product databases before running migrations.",
        )

    def handle(self, *args, **options):
        get_product_db_routes.cache_clear()
        routes = get_product_db_routes()

        aliases_to_apps: dict[str, set[str]] = defaultdict(set)
        for route in routes:
            if route.database in settings.DATABASES:
                aliases_to_apps[route.database].add(route.app_label)

        if not aliases_to_apps:
            self.stdout.write("No configured product databases found.")
            return

        for alias, app_labels in sorted(aliases_to_apps.items()):
            if options["ensure_databases"]:
                ensure_database_exists(alias)

            self.stdout.write(f"Running product migrations on database '{alias}'")
            for app_label in sorted(app_labels):
                call_command("migrate", app_label, database=alias, interactive=False, verbosity=1)
