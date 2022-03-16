import re
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Automated test to make sure there are no non-null, dropping, renaming, or multiple migrations"

    def handle(self, *args, **options):
        def run_and_check_migration(variable):
            try:
                results = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", variable)[0]
                sql = call_command("sqlmigrate", results[0], results[1])
                if (
                    ("NOT NULL" in sql or "DEFAULT" in sql)
                    and "Create model" not in sql
                    and "-- not-null-ignore" not in sql
                ):
                    print(
                        f"\n\n\033[91mFound a non-null field added to an existing model. This will lock up the table while migrating. Please add 'null=True, blank=True' to the field",
                    )
                    sys.exit(1)

                if "RENAME" in sql:
                    print(
                        f"\n\n\033[91mFound a rename command. This will lock up the table while migrating. Please create a new column and provide alternative method for swapping columns",
                    )
                    sys.exit(1)

                if "DROP COLUMN" in sql:
                    print(
                        f"\n\n\033[91mFound a drop command. This could lead to unsafe states for the app. Please avoid dropping columns",
                    )
                    sys.exit(1)
            except (IndexError, CommandError):
                pass

        migrations = sys.stdin.readlines()
        if len(migrations) > 1:
            print(
                f"\n\n\033[91mFound multiple migrations. Please scope PRs to one migration to promote easy debugging and revertability",
            )
            sys.exit(1)

        for data in migrations:
            run_and_check_migration(data)
