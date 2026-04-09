"""CDC prerequisite validator for PostgreSQL.

Checks whether a PostgreSQL database is ready for CDC via logical replication.
Returns a list of user-facing error messages (empty = all checks passed).
"""

from __future__ import annotations

import logging
from typing import Literal

import psycopg
from psycopg import sql

from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import publication_exists, slot_exists

logger = logging.getLogger(__name__)


def validate_cdc_prerequisites(
    conn: psycopg.Connection,
    management_mode: Literal["posthog", "self_managed"],
    tables: list[str],
    schema: str = "public",
    slot_name: str | None = None,
    publication_name: str | None = None,
) -> list[str]:
    """Validate that the database is ready for CDC.

    Returns a list of user-facing error messages. Empty list = valid.
    """
    errors: list[str] = []

    errors.extend(_check_pg_version(conn))
    errors.extend(_check_wal_level(conn))
    errors.extend(_check_tables_have_primary_keys(conn, schema, tables))
    errors.extend(_check_select_permission(conn, schema, tables))

    if management_mode == "posthog":
        errors.extend(_check_replication_role(conn))
        errors.extend(_check_replication_slot_capacity(conn))
    elif management_mode == "self_managed":
        if slot_name:
            errors.extend(_check_slot_exists(conn, slot_name))
        else:
            errors.append("Replication slot name is required for self-managed mode.")
        if publication_name:
            errors.extend(_check_publication_exists(conn, publication_name))
        else:
            errors.append("Publication name is required for self-managed mode.")

    return errors


def _check_pg_version(conn: psycopg.Connection) -> list[str]:
    """PG version >= 13 (required for publish_via_partition_root)."""
    with conn.cursor() as cur:
        cur.execute("SHOW server_version_num")
        row = cur.fetchone()
        if row is None:
            return ["Could not determine PostgreSQL version."]
        version_num = int(row[0])
        if version_num < 130000:
            return [
                f"PostgreSQL 13 or later is required for CDC. Your server is running version {version_num // 10000}."
            ]
    return []


def _check_wal_level(conn: psycopg.Connection) -> list[str]:
    """wal_level must be 'logical'."""
    with conn.cursor() as cur:
        cur.execute("SHOW wal_level")
        row = cur.fetchone()
        if row is None:
            return ["Could not determine wal_level."]
        if row[0] != "logical":
            return [
                f"wal_level must be set to 'logical' (currently '{row[0]}'). "
                "This requires a PostgreSQL server restart after changing the configuration."
            ]
    return []


def _check_tables_have_primary_keys(conn: psycopg.Connection, schema: str, tables: list[str]) -> list[str]:
    """Each target table must have a primary key."""
    if not tables:
        return []

    errors: list[str] = []
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(
                sql.SQL(
                    "SELECT COUNT(*) FROM information_schema.table_constraints "
                    "WHERE table_schema = {} AND table_name = {} AND constraint_type = 'PRIMARY KEY'"
                ).format(sql.Literal(schema), sql.Literal(table))
            )
            row = cur.fetchone()
            if row is None or row[0] == 0:
                errors.append(f"Table '{schema}.{table}' has no primary key. CDC requires a primary key on each table.")
    return errors


def _check_select_permission(conn: psycopg.Connection, schema: str, tables: list[str]) -> list[str]:
    """Check SELECT permission on target tables."""
    errors: list[str] = []
    with conn.cursor() as cur:
        for table in tables:
            try:
                cur.execute(
                    sql.SQL("SELECT 1 FROM {}.{} LIMIT 0").format(sql.Identifier(schema), sql.Identifier(table))
                )
            except psycopg.errors.InsufficientPrivilege:
                conn.rollback()
                errors.append(f"No SELECT permission on table '{schema}.{table}'.")
            except psycopg.errors.UndefinedTable:
                conn.rollback()
                errors.append(f"Table '{schema}.{table}' does not exist.")
    return errors


def _check_replication_role(conn: psycopg.Connection) -> list[str]:
    """Check if current user has REPLICATION role (PostHog-managed mode)."""
    with conn.cursor() as cur:
        cur.execute("SELECT rolreplication FROM pg_roles WHERE rolname = current_user")
        row = cur.fetchone()
        if row is None:
            return ["Could not determine user roles."]
        if not row[0]:
            return [
                "The database user must have the REPLICATION role for PostHog-managed CDC. "
                "Run: ALTER USER <username> WITH REPLICATION;"
            ]
    return []


def _check_replication_slot_capacity(conn: psycopg.Connection) -> list[str]:
    """Check if there's capacity for a new replication slot."""
    with conn.cursor() as cur:
        cur.execute("SHOW max_replication_slots")
        max_row = cur.fetchone()
        if max_row is None:
            return ["Could not determine max_replication_slots."]

        max_slots = int(max_row[0])

        cur.execute("SELECT COUNT(*) FROM pg_replication_slots")
        count_row = cur.fetchone()
        if count_row is None:
            return ["Could not count existing replication slots."]

        current_slots = int(count_row[0])

        if current_slots >= max_slots:
            return [
                f"No replication slot capacity available ({current_slots}/{max_slots} slots in use). "
                "Increase max_replication_slots in your PostgreSQL configuration."
            ]
    return []


def _check_slot_exists(conn: psycopg.Connection, slot_name: str) -> list[str]:
    """Self-managed: verify the provided slot exists."""
    if not slot_exists(conn, slot_name):
        return [
            f"Replication slot '{slot_name}' does not exist. Create it with: SELECT pg_create_logical_replication_slot('{slot_name}', 'pgoutput');"
        ]
    return []


def _check_publication_exists(conn: psycopg.Connection, pub_name: str) -> list[str]:
    """Self-managed: verify the provided publication exists."""
    if not publication_exists(conn, pub_name):
        return [
            f"Publication '{pub_name}' does not exist. Create it with: CREATE PUBLICATION {pub_name} FOR TABLE ...;"
        ]
    return []
