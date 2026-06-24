"""Direct person/distinct-id writes for local dev and seed management commands.

These helpers insert and update persons straight in the persons database via a raw
psycopg connection (see :mod:`posthog.persons_db`), bypassing the Django ORM so the
persons database can be dropped from Django's ``DATABASES``. They exist only for
development and seed tooling that needs to fabricate persons locally — production
person creation flows through ingestion and the personhog service, which has no
create RPC by design.

``created_at`` and ``uuid`` are ``NOT NULL`` with no database default (the ORM fills
them application-side), so the inserts set them explicitly; ``team_id`` is required to
route the row to the correct hash partition of the persons table.
"""

from __future__ import annotations

import uuid as uuid_lib
from typing import Any

from django.conf import settings

import psycopg
from psycopg.types.json import Jsonb

from posthog.models.utils import UUIDT

# Not configurable like the person table; the model uses Django's default db_table.
PERSON_DISTINCT_ID_TABLE = "posthog_persondistinctid"


def insert_seed_person(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    properties: dict[str, Any],
    is_identified: bool = False,
    uuid: str | uuid_lib.UUID | None = None,
) -> int:
    """Insert one person row and return its database id.

    Pass ``uuid`` when the caller needs to reference the person downstream (e.g. to
    mirror it into ClickHouse); otherwise a fresh ``UUIDT`` is generated.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {settings.PERSON_TABLE_NAME} "  # nosemgrep: no-direct-persons-db-orm
            "(created_at, properties, is_identified, uuid, team_id) "
            "VALUES (now(), %s, %s, %s, %s) RETURNING id",
            (Jsonb(properties), is_identified, uuid or UUIDT(), team_id),
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
) -> None:
    """Insert one distinct-id row linking ``distinct_id`` to ``person_id``."""
    with conn.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {PERSON_DISTINCT_ID_TABLE} "  # nosemgrep: no-direct-persons-db-orm
            "(distinct_id, person_id, team_id) VALUES (%s, %s, %s)",
            (distinct_id, person_id, team_id),
        )


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
            f"UPDATE {settings.PERSON_TABLE_NAME} "  # nosemgrep: no-direct-persons-db-orm
            "SET properties = %s, is_identified = %s WHERE team_id = %s AND uuid = %s",
            (Jsonb(properties), is_identified, team_id, uuid),
        )
