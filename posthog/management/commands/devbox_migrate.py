from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run Django and ClickHouse migrations in a single process"

    def handle(self, *args, **options):
        self.stdout.write("Running Django migrations...")
        call_command("migrate", "--noinput")

        self.stdout.write("Running ClickHouse migrations...")
        call_command("migrate_clickhouse")

        self.stdout.write(self.style.SUCCESS("All migrations complete"))
