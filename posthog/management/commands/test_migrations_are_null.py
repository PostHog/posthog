import re
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team


class Command(BaseCommand):
    help = "Automated test to make sure there are no non-null migrations"

    def handle(self, *args, **options):
        def run_and_check_migration(variable):
            try:
                results = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", variable)[0]
                sql = call_command("sqlmigrate", results[0], results[1])
                if "NOT NULL" in sql and "Create model" not in sql and "-- not-null-ignore" not in sql:
                    print(
                        f"\n\n\033[91mFound a non-null field added to an existing model. This will lock up the table while migrating. Please add 'null=True, blank=True' to the field",
                        "red",
                    )
                    sys.exit(1)
            except (IndexError, CommandError):
                pass

        for data in sys.stdin:
            run_and_check_migration(data)
