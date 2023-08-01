import re
import sys
from typing import List, Optional

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


def _get_new_tables(sql: str):
    return re.findall(r'CREATE TABLE "([a-zA-Z0-9_]*)"', sql)


def _get_table(search_string: str, operation_sql: str) -> Optional[str]:
    match = re.match(r'.*{} "([a-zA-Z0-9_]*)"'.format(search_string), operation_sql)
    if match:
        return match[1]
    return None


def validate_migration_sql(sql) -> bool:
    new_tables = _get_new_tables(sql)
    operations = sql.split("\n")
    tables_created_so_far: List[str] = []
    for operation_sql in operations:
        # Extract table name from queries of this format: ALTER TABLE TABLE "posthog_feature"
        table_being_altered: Optional[str] = (
            re.findall(r"ALTER TABLE \"([a-z_]+)\"", operation_sql)[0] if "ALTER TABLE" in operation_sql else None
        )
        # Extract table name from queries of this format: CREATE TABLE "posthog_feature"
        if "CREATE TABLE" in operation_sql:
            table_name = re.findall(r"CREATE TABLE \"([a-z_]+)\"", operation_sql)[0]
            tables_created_so_far.append(table_name)

            if '"id" serial' in operation_sql:
                print(
                    f"\n\n\033[91mFound a new table with an int32 id. Please use an int64 id or use UUIDModel instead.\nSource: `{operation_sql}`"
                )
                return True

        if (
            re.findall(r"(?<!DROP) (NOT NULL|DEFAULT .* NOT NULL)", operation_sql, re.M & re.I)
            and "CREATE TABLE" not in operation_sql
            and "-- not-null-ignore" not in operation_sql
        ):
            print(
                f"\n\n\033[91mFound a non-null field or default added to an existing model. This will lock up the table while migrating. Please add 'null=True, blank=True' to the field.\nSource: `{operation_sql}`"
            )
            return True

        if "RENAME" in operation_sql and "-- rename-ignore" not in operation_sql:
            print(
                f"\n\n\033[91mFound a rename command. This will lock up the table while migrating. Please create a new column and provide alternative method for swapping columns.\nSource: `{operation_sql}`"
            )
            return True

        if "DROP COLUMN" in operation_sql and "-- drop-column-ignore" not in operation_sql:
            print(
                f"\n\n\033[91mFound a drop command. This could lead to unsafe states for the app. Please avoid dropping columns.\nSource: `{operation_sql}`"
            )
            return True

        if "DROP TABLE" in operation_sql:
            print(
                f"\n\n\033[91mFound a DROP TABLE command. This could lead to unsafe states for the app. Please avoid dropping tables.\nSource: `{operation_sql}`"
            )
            return True
        if "CONSTRAINT" in operation_sql and (
            "-- existing-table-constraint-ignore" not in operation_sql
            and (
                table_being_altered not in tables_created_so_far
                or _get_table("ALTER TABLE", operation_sql) not in new_tables
            )  # Ignore for brand-new tables
        ):
            print(
                f"\n\n\033[91mFound a CONSTRAINT command. This locks tables which causes downtime. Please avoid adding constraints to existing tables.\nSource: `{operation_sql}`"
            )
            return True
        if (
            "CREATE INDEX" in operation_sql
            and "CONCURRENTLY" not in operation_sql
            and _get_table(" ON", operation_sql) not in new_tables
        ):
            print(
                f"\n\n\033[91mFound a CREATE INDEX command that isn't run CONCURRENTLY. This locks tables which causes downtime. Please add this index CONCURRENTLY instead.\nSource: `{operation_sql}`"
            )
            return True

    # if it isn't already invalid, then the migration is valid
    return False


class Command(BaseCommand):
    help = "Automated test to make sure there are no non-null, dropping, renaming, or multiple migrations"

    def handle(self, *args, **options):
        def run_and_check_migration(variable):
            try:
                results = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", variable)[0]
                sql = call_command("sqlmigrate", results[0], results[1])
                should_fail = validate_migration_sql(sql)
                if should_fail:
                    sys.exit(1)

            except (IndexError, CommandError):
                pass

        migrations = sys.stdin.readlines()

        if not migrations:
            migrations = ["posthog/migrations/0339_add_session_recording_storage_version.py"]

        if len(migrations) > 1:
            print(
                f"\n\n\033[91mFound multiple migrations. Please scope PRs to one migration to promote easy debugging and revertability"
            )
            sys.exit(1)

        for data in migrations:
            run_and_check_migration(data)
