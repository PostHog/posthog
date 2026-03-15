# ruff: noqa: T201 allow print statements

"""
Shared SQL migration safety checks.

Pure SQL regex analysis with zero Django dependency. Used by both:
- posthog/management/commands/test_migrations_are_safe.py (Django migrations via sqlmigrate)
- rust/bin/check-migration-safety (raw SQLx .sql files)
"""

import re
from typing import Optional


def _get_new_tables(sql: str) -> list[str]:
    return re.findall(r'CREATE TABLE(?:\s+IF NOT EXISTS)?\s+"?([a-zA-Z0-9_]*)"?', sql)


def _get_table(search_string: str, operation_sql: str) -> Optional[str]:
    match = re.match(r'.*{} "?([a-zA-Z0-9_]*)"?'.format(search_string), operation_sql)
    if match:
        return match[1]
    return None


def normalize_sql_statements(sql: str) -> str:
    """
    Collapse multi-line SQL statements into single lines.

    Hand-written SQL files spread statements across multiple lines, but the
    validation logic expects one statement per line (as Django's sqlmigrate
    produces). This joins continuation lines so that e.g. a CREATE INDEX
    and its ON clause, or an ADD CONSTRAINT and NOT VALID, appear together.
    """
    lines = sql.split("\n")
    normalized: list[str] = []
    current = ""
    for line in lines:
        stripped = line.strip()
        # Skip empty lines and comments
        if not stripped or stripped.startswith("--"):
            if current:
                normalized.append(current)
                current = ""
            normalized.append(line)
            continue
        # A line that starts with a SQL keyword begins a new statement
        # Continuation lines (indented or not starting with a keyword) get joined
        if current and not re.match(
            r"^(CREATE|ALTER|DROP\s+(TABLE|INDEX)|INSERT|UPDATE|DELETE|BEGIN|COMMIT|GRANT|REVOKE|SET|DO|SELECT)\b",
            stripped,
            re.I,
        ):
            current = current + " " + stripped
        else:
            if current:
                normalized.append(current)
            current = stripped
    if current:
        normalized.append(current)
    return "\n".join(normalized)


def strip_plpgsql_blocks(sql: str) -> str:
    """
    Strip DO $$ ... END $$; blocks that use IF NOT EXISTS guards.

    Raw SQLx migrations use PL/pgSQL blocks for idempotent constraint
    additions. These are safe by construction (they check before adding)
    and would otherwise false-positive in line-by-line analysis.

    Blocks without IF NOT EXISTS guards are left in place for checking.
    """

    def _replace_block(match: re.Match) -> str:
        block_body = match.group(1)
        if "IF NOT EXISTS" in block_body or "IF EXISTS" in block_body:
            return ""
        return match.group(0)

    return re.sub(r"DO\s+\$\$(.*?)\$\$;", _replace_block, sql, flags=re.S | re.I)


def validate_migration_sql(sql: str) -> bool:
    """
    Validate migration SQL for unsafe operations.

    Returns True if the migration is unsafe (should fail CI).
    """
    new_tables = _get_new_tables(sql)
    operations = sql.split("\n")
    tables_created_so_far: list[str] = []
    for operation_sql in operations:
        # Extract table name from queries of this format: ALTER TABLE "posthog_feature" or ALTER TABLE posthog_feature
        table_being_altered: Optional[str] = None
        if "ALTER TABLE" in operation_sql:
            matches = re.findall(r'ALTER TABLE(?:\s+IF EXISTS)?\s+"?([a-zA-Z0-9_]+)"?', operation_sql)
            table_being_altered = matches[0] if matches else None
        # Extract table name from queries of this format: CREATE TABLE "posthog_feature" or CREATE TABLE posthog_feature
        if "CREATE TABLE" in operation_sql:
            matches = re.findall(r'CREATE TABLE(?:\s+IF NOT EXISTS)?\s+"?([a-zA-Z0-9_]+)"?', operation_sql)
            if matches:
                table_name = matches[0]
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
            # Ignore constraints inside CREATE TABLE (new table is empty, nothing to validate)
            and "CREATE TABLE" not in operation_sql
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
                "See https://github.com/PostHog/posthog/blob/master/docs/published/safe-django-migrations.md for guidance."
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
                "See https://github.com/PostHog/posthog/blob/master/docs/published/safe-django-migrations.md for guidance."
                "If adding the index by itself, please use `AddIndexConcurrently()` of `django.contrib.postgres.operations` instead. "
                "See https://docs.djangoproject.com/en/4.2/ref/contrib/postgres/operations/#concurrent-index-operations.\n"
                f"Source: `{operation_sql}`"
            )
            return True

    # if it isn't already invalid, then the migration is valid
    return False
