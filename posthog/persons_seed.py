"""Direct persons-database reads and writes for local dev and seed management commands.

These helpers read, insert, and update persons/groups straight in the persons database via
a raw psycopg connection (see :mod:`posthog.persons_db`), bypassing the Django ORM so the
persons database can be dropped from Django's ``DATABASES``. They exist only for development
and seed tooling that needs to fabricate or read persons locally — production person
creation flows through ingestion and the personhog service, which has no create RPC by
design.

``created_at`` and ``uuid`` are ``NOT NULL`` with no database default (the ORM fills them
application-side), so the inserts set them explicitly; ``team_id`` is required (and in
production routes the row to the correct hash partition of the persons table).
"""

from __future__ import annotations

import uuid as uuid_lib
import dataclasses
from datetime import datetime
from typing import Any

from django.conf import settings

import psycopg
from psycopg.types.json import Jsonb

from posthog.models.utils import UUIDT
from posthog.persons_db import persons_db_connection

# Not configurable like the person table; the model uses Django's default db_table.
PERSON_DISTINCT_ID_TABLE = "posthog_persondistinctid"


def insert_seed_person(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    properties: dict[str, Any],
    is_identified: bool = False,
    uuid: str | uuid_lib.UUID | None = None,
    version: int | None = None,
    created_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    properties_last_updated_at: dict[str, Any] | None = None,
    properties_last_operation: dict[str, Any] | None = None,
) -> int:
    """Insert one person row and return its database id.

    Pass ``uuid`` when the caller needs to reference the person downstream (e.g. to
    mirror it into ClickHouse); otherwise a fresh ``UUIDT`` is generated. ``created_at``
    defaults to ``now()`` (matching the model's ``auto_now_add``); ``version``,
    ``last_seen_at`` and the ``properties_last_*`` maps default to NULL, mirroring
    ``Person.objects.create`` with no override.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {settings.PERSON_TABLE_NAME} "
            "(created_at, properties, is_identified, uuid, team_id, version, last_seen_at, "
            "properties_last_updated_at, properties_last_operation) "
            "VALUES (COALESCE(%s, now()), %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                created_at,
                Jsonb(properties),
                is_identified,
                uuid or UUIDT(),
                team_id,
                version,
                last_seen_at,
                Jsonb(properties_last_updated_at) if properties_last_updated_at is not None else None,
                Jsonb(properties_last_operation) if properties_last_operation is not None else None,
            ),
        )
        row = cursor.fetchone()
        assert row is not None  # RETURNING always yields a row on a successful insert
        return row[0]


def insert_seed_distinct_id(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    person_id: int,
    distinct_id: str,
    version: int | None = 0,
) -> None:
    """Insert one distinct-id row linking ``distinct_id`` to ``person_id``.

    ``version`` defaults to 0 but accepts ``None`` to write a NULL version (the column is
    nullable), mirroring ``PersonDistinctId.objects.create(version=None)``.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {PERSON_DISTINCT_ID_TABLE} (distinct_id, person_id, team_id, version) VALUES (%s, %s, %s, %s)",
            (distinct_id, person_id, team_id, version),
        )


def insert_seed_group(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    group_key: str,
    group_type_index: int,
    group_properties: dict[str, Any],
    version: int = 0,
    created_at: datetime | None = None,
) -> int:
    """Insert one group row and return its id. ``created_at`` defaults to ``now()``; ``version`` is NOT NULL."""
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO posthog_group "
            "(team_id, group_key, group_type_index, group_properties, created_at, version) "
            "VALUES (%s, %s, %s, %s, COALESCE(%s, now()), %s) RETURNING id",
            (team_id, group_key, group_type_index, Jsonb(group_properties), created_at, version),
        )
        row = cursor.fetchone()
        assert row is not None  # RETURNING always yields a row on a successful insert
        return row[0]


def insert_seed_group_type_mapping(
    conn: psycopg.Connection[Any],
    *,
    project_id: int,
    team_id: int | None,
    group_type: str,
    group_type_index: int,
    name_singular: str | None = None,
    name_plural: str | None = None,
    default_columns: list[str] | None = None,
    detail_dashboard_id: int | None = None,
    created_at: datetime | None = None,
) -> int:
    """Insert one group-type-mapping row and return its id.

    ``created_at`` is written as given (``None`` stays NULL — the model's custom ``save()`` stamps
    created_at only on insert, which this bypasses); callers pass ``now()`` for the normal case.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO posthog_grouptypemapping "
            "(project_id, team_id, group_type, group_type_index, name_singular, name_plural, "
            "default_columns, detail_dashboard_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                project_id,
                team_id,
                group_type,
                group_type_index,
                name_singular,
                name_plural,
                default_columns,
                detail_dashboard_id,
                created_at,
            ),
        )
        row = cursor.fetchone()
        assert row is not None  # RETURNING always yields a row on a successful insert
        return row[0]


def update_seed_person(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    uuid: str | uuid_lib.UUID,
    properties: dict[str, Any],
    is_identified: bool,
) -> None:
    """Overwrite ``properties`` and ``is_identified`` for an existing person."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {settings.PERSON_TABLE_NAME} "
            "SET properties = %s, is_identified = %s WHERE team_id = %s AND uuid = %s",
            (Jsonb(properties), is_identified, team_id, uuid),
        )


@dataclasses.dataclass
class PersonData:
    """A person fetched from the persons database for dev/seed event generation."""

    distinct_id: str
    person_uuid: str
    properties: dict[str, Any]
    created_at: Any


def fetch_recent_persons_with_distinct_id(team_id: int, *, limit: int = 50) -> list[PersonData]:
    """Return up to ``limit`` most-recently-created persons that have a distinct ID.

    Each person is paired with one of its distinct IDs; the inner lateral join drops
    persons without one, so the result may be shorter than ``limit``.
    """
    query = (
        "SELECT p.uuid, p.properties, p.created_at, pdi.distinct_id "
        f"FROM (SELECT id, uuid, properties, created_at FROM {settings.PERSON_TABLE_NAME} "
        "WHERE team_id = %(team_id)s ORDER BY created_at DESC LIMIT %(limit)s) p "
        "JOIN LATERAL (SELECT distinct_id FROM posthog_persondistinctid "
        "WHERE team_id = %(team_id)s AND person_id = p.id LIMIT 1) pdi ON true"
    )
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(query, {"team_id": team_id, "limit": limit})
        rows = cursor.fetchall()
    return [
        PersonData(person_uuid=str(row[0]), properties=row[1] or {}, created_at=row[2], distinct_id=row[3])
        for row in rows
    ]
