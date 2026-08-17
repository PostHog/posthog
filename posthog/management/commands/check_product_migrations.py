from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.product_db_migrations import collect_unapplied_product_migrations
from posthog.product_db_router import get_product_db_routes


class Command(BaseCommand):
    help = (
        "Exit non-zero if any configured product-routed database has unapplied migrations. "
        "Read-only: never applies anything (the migration owner does, via bin/migrate)."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        get_product_db_routes.cache_clear()
        unapplied = collect_unapplied_product_migrations()

        if not unapplied:
            self.stdout.write("Product database migrations are up to date.")
            return

        for alias, migrations in unapplied.items():
            for migration in migrations:
                self.stderr.write(f"Unapplied migration on '{alias}': {migration}")
        raise CommandError(
            "Product database(s) have unapplied migrations: "
            + "; ".join(f"{alias}: {', '.join(migrations)}" for alias, migrations in unapplied.items())
        )
