"""
PostgreSQL partition enforcement for partitioned tables.

This module provides a database execute wrapper that enforces partition key presence
in queries against partitioned tables to prevent full partition scans.
"""

import re
import traceback
from typing import Any

# Partition key for person tables
PARTITION_KEY = "team_id"

# Tables that are partitioned by team_id (hash partitioned with 64 partitions)
# Note: posthog_person_new is the actual partitioned table, but we also check
# posthog_person since that's the model's db_table name that appears in queries
PARTITIONED_TABLES = [
    "posthog_person_new",
    "posthog_person",
]

# SQL patterns that should bypass partition checking
SQL_WHITELIST = [
    "django_migrations",
    "django_content_type",
    "django_session",
    "pg_catalog",
    "information_schema",
    "auth_",
    "_sequence",
    "SAVEPOINT",
    "RELEASE SAVEPOINT",
    "ROLLBACK TO SAVEPOINT",
    "SET ",
    "SHOW ",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
]

# Compile regex for partition key detection
PARTITION_KEY_REGEX = re.compile(rf"\b{PARTITION_KEY}\b", re.IGNORECASE)


class PartitionEnforcementWrapper:
    """
    Database execute wrapper that enforces partition key presence in queries.

    Raises RuntimeError if a query against a partitioned table is missing
    the partition key in the WHERE clause, which would cause a scan of all
    64 partitions instead of a single partition.
    """

    def __call__(
        self,
        execute: Any,
        sql: str,
        params: Any,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        # Skip Django internal/meta queries
        if any(pattern in sql for pattern in SQL_WHITELIST):
            return execute(sql, params, many, context)

        # Check if query hits any partitioned table
        hits_partitioned_table = False
        matched_table = None
        for table in PARTITIONED_TABLES:
            if table in sql or f'"{table}"' in sql:
                hits_partitioned_table = True
                matched_table = table
                break

        if not hits_partitioned_table:
            return execute(sql, params, many, context)

        # Check for partition key in WHERE clause
        # Need to be careful: team_id in SELECT list doesn't count, must be in WHERE
        sql_upper = sql.upper()
        if "WHERE" not in sql_upper:
            # No WHERE clause at all - definitely missing partition key
            stack = "".join(traceback.format_stack(limit=15))
            raise RuntimeError(
                f"Missing partition key '{PARTITION_KEY}' in query to {matched_table}.\n"
                f"Query has no WHERE clause, will scan all 64 partitions.\n\n"
                f"SQL: {sql[:500]}\n\n"
                f"Stack:\n{stack}"
            )

        # Extract WHERE clause portion
        where_index = sql_upper.index("WHERE")
        where_clause = sql[where_index:]

        # Remove clauses that come after WHERE to avoid false positives
        for keyword in ["ORDER BY", "LIMIT", "OFFSET", "FOR UPDATE", "GROUP BY", "HAVING"]:
            keyword_upper = keyword.upper()
            if keyword_upper in where_clause.upper():
                idx = where_clause.upper().index(keyword_upper)
                where_clause = where_clause[:idx]

        # Check if partition key appears in WHERE clause
        if not PARTITION_KEY_REGEX.search(where_clause):
            stack = "".join(traceback.format_stack(limit=15))
            raise RuntimeError(
                f"Missing partition key '{PARTITION_KEY}' in WHERE clause for {matched_table}.\n"
                f"This will scan all 64 partitions (~64x performance degradation).\n\n"
                f"SQL: {sql[:500]}\n\n"
                f"WHERE clause: {where_clause[:300]}\n\n"
                f"Stack:\n{stack}"
            )

        return execute(sql, params, many, context)


def install_partition_enforcement() -> None:
    """
    Install partition enforcement wrapper on person database connections.

    Installs on persons_db_writer and persons_db_reader if they exist,
    otherwise falls back to default database.

    Should be called during Django startup to enforce partition key presence
    in all queries to partitioned tables.
    """
    from django.db import connections

    wrapper = PartitionEnforcementWrapper()

    # Install on persons_db_writer and persons_db_reader if they exist
    if "persons_db_writer" in connections:
        connections["persons_db_writer"].execute_wrapper(wrapper)
    if "persons_db_reader" in connections:
        connections["persons_db_reader"].execute_wrapper(wrapper)

    # Also install on default if persons databases don't exist (local dev)
    if "persons_db_writer" not in connections:
        connections["default"].execute_wrapper(wrapper)
