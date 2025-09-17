from posthog.test.base import reset_clickhouse_database

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Resets the ClickHouse database for the test environment"

    # NOTE: This commands enables `TEST=1` environment variable via a hack
    # in posthog/settings/base_variables.py where we pattern match against the command name
    # If you change the command name, you need to update the pattern match.
    def handle(self, *args, **kwargs):
        self.stdout.write("Resetting ClickHouse database...")
        reset_clickhouse_database()
        self.stdout.write(self.style.SUCCESS("Successfully reset ClickHouse database"))
