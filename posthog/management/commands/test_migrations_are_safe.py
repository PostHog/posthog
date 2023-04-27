import re
import sys

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Automated test to make sure there are no non-null, dropping, renaming, or multiple migrations"

    def _get_new_tables(self, sql: str):
        return re.findall(r'CREATE TABLE "([a-zA-Z0-9_]*)"', sql)

    def handle(self, *args, **options):
        def run_and_check_migration(variable):
            try:
                results = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", variable)[0]
                sql = call_command("sqlmigrate", results[0], results[1])
                new_tables = self._get_new_tables(sql)
                operations = sql.split("\n")
                for operation_sql in operations:
                    if (
                        re.findall(r"(?<!DROP) (NOT NULL|DEFAULT)", operation_sql, re.M & re.I)
                        and "CREATE TABLE" not in operation_sql
                        and "-- not-null-ignore" not in operation_sql
                    ):
                        print(
                            f"\n\n\033[91mFound a non-null field or default added to an existing model. This will lock up the table while migrating. Please add 'null=True, blank=True' to the field.\nSource: `{operation_sql}`"
                        )
                        sys.exit(1)

                    if "RENAME" in operation_sql and "-- rename-ignore" not in operation_sql:
                        print(
                            f"\n\n\033[91mFound a rename command. This will lock up the table while migrating. Please create a new column and provide alternative method for swapping columns.\nSource: `{operation_sql}`"
                        )
                        sys.exit(1)

                    if "DROP COLUMN" in operation_sql and "-- drop-column-ignore" not in operation_sql:
                        print(
                            f"\n\n\033[91mFound a drop command. This could lead to unsafe states for the app. Please avoid dropping columns.\nSource: `{operation_sql}`"
                        )
                        sys.exit(1)

                    if "DROP TABLE" in operation_sql:
                        print(
                            f"\n\n\033[91mFound a DROP TABLE command. This could lead to unsafe states for the app. Please avoid dropping tables.\nSource: `{operation_sql}`"
                        )
                        sys.exit(1)

                    if (
                        "CONSTRAINT" in operation_sql
                        and re.match(r'ALTER TABLE "([a-zA-Z0-9_]*)"', operation_sql)[1] not in new_tables
                    ):
                        print(
                            f"\n\n\033[91mFound a CONSTRAINT command. This locks tables which causes downtime. Please avoid adding constraints to existing tables.\nSource: `{operation_sql}`"
                        )
                        sys.exit(1)
                    if (
                        "CREATE INDEX" in operation_sql
                        and "CONCURRENTLY" not in operation_sql
                        and re.match(r'.* ON "([a-zA-Z0-9_]*)"', operation_sql)[1] not in new_tables
                    ):
                        print(
                            f"\n\n\033[91mFound a CREATE INDEX command that isn't run CONCURRENTLY. This locks tables which causes downtime. Please add this index CONCURRENTLY instead.\nSource: `{operation_sql}`"
                        )
                        sys.exit(1)

            except (IndexError, CommandError):
                pass

        migrations = sys.stdin.readlines()
        if len(migrations) > 1:
            print(
                f"\n\n\033[91mFound multiple migrations. Please scope PRs to one migration to promote easy debugging and revertability"
            )
            sys.exit(1)

        for data in migrations:
            run_and_check_migration(data)
