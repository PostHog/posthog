# ruff: noqa: T201 allow print statements

import os
import re
import sys
import select
from typing import Optional

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
    tables_created_so_far: list[str] = []
    for operation_sql in operations:
        # Extract table name from queries of this format: ALTER TABLE TABLE "posthog_feature"
        table_being_altered: Optional[str] = (
            re.findall(r"ALTER TABLE \"([a-z_]+)\"", operation_sql)[0] if "ALTER TABLE" in operation_sql else None
        )
        # Extract table name from queries of this format: CREATE TABLE "posthog_feature"
        if "CREATE TABLE" in operation_sql:
            table_name = re.findall(r"CREATE TABLE \"([a-z_]+)\"", operation_sql)[0]
            tables_created_so_far.append(table_name)

            if '"id" serial' in operation_sql or '"id" bigserial' in operation_sql:
                print(
                    f"\n\n\033[91mFound a new table with an integer id. Please use UUIDModel instead.\nSource: `{operation_sql}`"
                )
                return True

        if (
            "ALTER TABLE" in operation_sql  # Only check ALTER TABLE operations
            and re.findall(r"(?<!DROP) (NOT NULL|DEFAULT .* NOT NULL)", operation_sql, re.M & re.I)
            and "-- not-null-ignore" not in operation_sql
            # Ignore for brand-new tables
            and (table_being_altered not in tables_created_so_far or table_being_altered not in new_tables)
        ):
            # Check if this is adding/altering a column with a constant default (safe in PostgreSQL 11+)
            if ("ADD COLUMN" in operation_sql and "DEFAULT" in operation_sql) or (
                "ALTER COLUMN" in operation_sql and "SET DEFAULT" in operation_sql
            ):
                # Extract the default value to check if it's a constant
                # Match DEFAULT followed by either a quoted string or unquoted value including typecast until NOT NULL or end of significant tokens
                # regexr.com is your friend when trying to understand this regex
                default_match = re.search(
                    r"DEFAULT\s+((?:'[^']*')|(?:[^'\s]+(?:\s+[^'\s]+)*?))(\s+|::\w+\s+)(?:NOT\s+NULL|;|$)",
                    operation_sql,
                    re.I,
                )
                if default_match:
                    default_value = default_match.group(1).strip()
                    # Check if it's a constant (string literal, number, boolean, or simple constant like NOW())
                    if (
                        (default_value.startswith("'") and default_value.endswith("'"))  # String literal
                        or re.match(r"^-?\d+(\.\d+)?$", default_value)  # Number
                        or default_value.upper() in ["TRUE", "FALSE", "NULL"]  # Boolean/NULL
                        or default_value.upper()
                        in [
                            "NOW()",
                            "CURRENT_TIMESTAMP",
                            "CURRENT_DATE",
                            "CURRENT_TIME",
                        ]  # Functions marked as stable in postgres
                    ):
                        # This is safe - adding/altering a column with a constant default
                        # doesn't require table rewrite in PostgreSQL 11+
                        continue

            print(
                f"\n\n\033[91mFound a non-null field or default added to an existing model. This will lock up the table while migrating. Please add 'null=True, blank=True' to the field.\nSource: `{operation_sql}`"
            )
            return True

        if "RENAME" in operation_sql:
            print(
                f"\n\n\033[91mFound a RENAME command. This will lock up the table while migrating. Please create a new column and provide alternative method for swapping columns.\nSource: `{operation_sql}`"
            )
            return True

        if "DROP COLUMN" in operation_sql:
            print(
                f"\n\n\033[91mFound a DROP COLUMN command. This will lead to the app crashing while we roll out, and it will mean we can't roll back beyond this PR. Instead, please use the deprecate_field function: `from django_deprecate_fields import deprecate_field` and `your_field = deprecate_field(models.IntegerField(null=True, blank=True))`\nSource: `{operation_sql}`"
            )
            return True

        if "DROP TABLE" in operation_sql:
            print(
                f"\n\n\033[91mFound a DROP TABLE command. This could lead to unsafe states for the app. Please avoid dropping tables.\nSource: `{operation_sql}`"
            )
            return True
        if (
            " CONSTRAINT " in operation_sql
            # Ignore for new foreign key columns that are nullable, as their foreign key constraint does not lock
            and not re.search(r"ADD COLUMN .+ NULL CONSTRAINT", operation_sql)
            and "-- existing-table-constraint-ignore" not in operation_sql
            and " NOT VALID" not in operation_sql
            # VALIDATE CONSTRAINT is a different, non-locking operation
            and " VALIDATE CONSTRAINT " not in operation_sql
            and " DROP CONSTRAINT " not in operation_sql
            and (
                table_being_altered not in tables_created_so_far
                or _get_table("ALTER TABLE", operation_sql) not in new_tables  # Ignore for brand-new tables
            )
        ):
            print(
                f"\n\n\033[91mFound a CONSTRAINT command without NOT VALID. This locks tables which causes downtime. "
                "If adding a foreign key field, see `0415_pluginconfig_match_action` for an example of how to do this safely. "
                "If adding the constraint by itself, please use `AddConstraintNotValid()` of `django.contrib.postgres.operations` instead. "
                "See https://docs.djangoproject.com/en/4.2/ref/contrib/postgres/operations/#adding-constraints-without-enforcing-validation.\n"
                f"Source: `{operation_sql}`"
            )
            return True
        if (
            "CREATE INDEX" in operation_sql
            and "CONCURRENTLY" not in operation_sql
            and _get_table(" ON", operation_sql) not in new_tables
        ):
            print(
                f"\n\n\033[91mFound a CREATE INDEX command that isn't run CONCURRENTLY. This locks tables which causes downtime. "
                "If adding a foreign key field, see `0415_pluginconfig_match_action` for an example of how to do this safely. "
                "If adding the index by itself, please use `AddIndexConcurrently()` of `django.contrib.postgres.operations` instead. "
                "See https://docs.djangoproject.com/en/4.2/ref/contrib/postgres/operations/#concurrent-index-operations.\n"
                f"Source: `{operation_sql}`"
            )
            return True

    # if it isn't already invalid, then the migration is valid
    return False


class Command(BaseCommand):
    help = "Automated test to make sure there are no non-null, dropping, renaming, or multiple migrations"

    def handle(self, *args, **options):
        def run_and_check_migration(variable):
            try:
                # Handle both posthog/migrations and products/*/backend/migrations paths
                # For products: products/product_name/backend/migrations/0001_initial.py -> (product_name, 0001_initial)
                # For posthog: posthog/migrations/0001_initial.py -> (posthog, 0001_initial)
                products_match = re.findall(r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py", variable)
                if products_match:
                    results = products_match[0]
                else:
                    results = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", variable)[0]

                sql = call_command("sqlmigrate", results[0], results[1])
                should_fail = validate_migration_sql(sql)
                if should_fail:
                    sys.exit(1)

            except IndexError:
                print(f"\n\n\033[93m⚠️  WARNING: Could not parse migration path: {variable.strip()}\033[0m")
                print(
                    "Expected format: posthog/migrations/NNNN_name.py or products/name/backend/migrations/NNNN_name.py"
                )
                if os.getenv("CI"):
                    print("\033[91mFailing in CI due to unparseable migration path\033[0m")
                    sys.exit(1)
            except CommandError as e:
                print(f"\n\n\033[93m⚠️  WARNING: Failed to run sqlmigrate for {variable.strip()}\033[0m")
                print(f"Error: {e}")
                if os.getenv("CI"):
                    print("\033[91mFailing in CI due to sqlmigrate error\033[0m")
                    sys.exit(1)

        # Wait for stdin with 1 second timeout
        if select.select([sys.stdin], [], [], 1)[0]:
            migrations = sys.stdin.readlines()
        else:
            if os.getenv("CI"):
                print("\n\n\033[91mNo migrations provided in CI - this is likely a mistake")
                sys.exit(1)
            print("No stdin detected, using default migrations - only useful for testing purposes.")
            migrations = []

        if not migrations:
            migrations = ["posthog/migrations/0770_teamrevenueanalyticsconfig_filter_test_accounts_and_more.py"]

        if len(migrations) > 1:
            print(
                f"\n\n\033[91mFound multiple migrations. Please scope PRs to one migration to promote easy debugging and revertability"
            )
            sys.exit(1)

        for data in migrations:
            data = data.strip()
            # Skip empty lines
            if not data:
                continue
            # Validate file extension
            if not data.endswith(".py"):
                print(f"\033[93m⚠️  Skipping non-Python file: {data}\033[0m")
                continue
            # Prevent path traversal
            if ".." in data or data.startswith("/"):
                print(f"\033[91m⚠️  Skipping suspicious path: {data}\033[0m")
                if os.getenv("CI"):
                    sys.exit(1)
                continue
            run_and_check_migration(data)
