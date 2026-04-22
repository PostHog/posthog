from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run all migrations (Django, persons, ClickHouse) in a single process"

    def handle(self, *args, **options):
        self.stdout.write("Running Django migrations...")
        call_command("migrate", "--noinput")

        self.stdout.write("Running persons migrations...")
        call_command("apply_persons_migrations", "--database=persons_db_writer", "--ensure-database")

        self.stdout.write("Running ClickHouse migrations...")
        call_command("migrate_clickhouse")

        self.stdout.write(self.style.SUCCESS("All migrations complete"))
