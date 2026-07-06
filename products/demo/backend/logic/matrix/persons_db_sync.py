# ruff: noqa: T201 allow print statements
"""
Syncs person/group data from ClickHouse into the persons Postgres database
using raw psycopg, bypassing Django ORM and Django's database configuration.

Uses the persons_db_connection utility from posthog.persons_db for connections,
keeping Django completely decoupled from the persons database.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from posthog.clickhouse.client import query_with_columns
from posthog.persons_db import persons_db_connection


def sync_persons_to_postgres(
    source_team_id: int, target_team_id: int, person_table_name: str = "posthog_person"
) -> None:
    from posthog.models.group.sql import SELECT_GROUPS_OF_TEAM
    from posthog.models.person.sql import SELECT_PERSON_DISTINCT_ID2S_OF_TEAM, SELECT_PERSONS_OF_TEAM

    list_params = {"source_team_id": source_team_id}

    clickhouse_persons = query_with_columns(
        SELECT_PERSONS_OF_TEAM,
        list_params,
        columns_to_rename={"id": "uuid"},
    )

    clickhouse_distinct_ids = query_with_columns(
        SELECT_PERSON_DISTINCT_ID2S_OF_TEAM,
        list_params,
        ["team_id", "is_deleted", "_timestamp", "_offset", "_partition"],
        {"person_id": "person_uuid"},
    )

    clickhouse_groups = query_with_columns(
        SELECT_GROUPS_OF_TEAM,
        list_params,
        ["team_id", "_timestamp", "_offset", "is_deleted"],
    )

    with persons_db_connection(writer=True) as conn:
        with conn.cursor() as cur:
            uuid_to_pk = _insert_persons(cur, clickhouse_persons, target_team_id, person_table_name)
            _insert_person_distinct_ids(cur, clickhouse_distinct_ids, target_team_id, uuid_to_pk)
            _insert_groups(cur, clickhouse_groups, target_team_id)


def _insert_persons(
    cur: psycopg.Cursor[Any],
    clickhouse_persons: list[dict[str, Any]],
    target_team_id: int,
    person_table_name: str,
) -> dict[str, int]:
    if not clickhouse_persons:
        return {}

    insert_query = sql.SQL(
        "INSERT INTO {} (team_id, uuid, properties, is_identified, created_at, version, last_seen_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
    ).format(sql.Identifier(person_table_name))

    uuid_to_pk: dict[str, int] = {}
    for row in clickhouse_persons:
        uuid = str(row["uuid"])
        properties = row.get("properties", "{}")
        if isinstance(properties, str):
            properties = json.loads(properties)

        cur.execute(
            insert_query,
            (
                target_team_id,
                uuid,
                Jsonb(properties),
                bool(row.get("is_identified", False)),
                row.get("created_at"),
                row.get("version"),
                row.get("last_seen_at"),
            ),
        )
        result = cur.fetchone()
        assert result is not None
        uuid_to_pk[uuid] = result[0]

    return uuid_to_pk


def _insert_person_distinct_ids(
    cur: psycopg.Cursor[Any],
    clickhouse_distinct_ids: list[dict[str, Any]],
    target_team_id: int,
    uuid_to_pk: dict[str, int],
) -> None:
    if not clickhouse_distinct_ids:
        return

    rows = []
    for row in clickhouse_distinct_ids:
        person_uuid = str(row["person_uuid"])
        person_pk = uuid_to_pk.get(person_uuid)
        if person_pk is None:
            continue

        rows.append((target_team_id, row["distinct_id"], person_pk, row["version"]))

    if rows:
        cur.executemany(
            "INSERT INTO posthog_persondistinctid (team_id, distinct_id, person_id, version) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )


def _insert_groups(
    cur: psycopg.Cursor[Any],
    clickhouse_groups: list[dict[str, Any]],
    target_team_id: int,
) -> None:
    if not clickhouse_groups:
        return

    for row in clickhouse_groups:
        group_properties = row.get("group_properties", "{}")
        if isinstance(group_properties, str):
            group_properties = json.loads(group_properties)

        cur.execute(
            "INSERT INTO posthog_group "
            "(team_id, group_type_index, group_key, group_properties, created_at, version, "
            "properties_last_updated_at, properties_last_operation) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (
                target_team_id,
                row["group_type_index"],
                row["group_key"],
                Jsonb(group_properties),
                row["created_at"],
                0,
                Jsonb({}),
                Jsonb({}),
            ),
        )


def bulk_create_group_type_mappings(
    team_id: int,
    project_id: int,
    mappings: list[dict[str, Any]],
) -> None:
    if not mappings:
        return

    rows = [
        (
            team_id,
            project_id,
            m["group_type_index"],
            m["group_type"],
            m.get("name_singular"),
            m.get("name_plural"),
        )
        for m in mappings
    ]

    try:
        with persons_db_connection(writer=True) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO posthog_grouptypemapping "
                    "(team_id, project_id, group_type_index, group_type, name_singular, name_plural) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    rows,
                )
    except psycopg.errors.IntegrityError as e:
        print(f"SKIPPING GROUP TYPE MAPPING CREATION: {e}")


def delete_group_type_mappings(project_id: int) -> None:
    with persons_db_connection(writer=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM posthog_grouptypemapping WHERE project_id = %s",
                (project_id,),
            )


def copy_group_type_mappings(source_project_id: int, target_team_id: int, target_project_id: int) -> None:
    with persons_db_connection(writer=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM posthog_grouptypemapping WHERE project_id = %s",
                (target_project_id,),
            )
            cur.execute(
                "INSERT INTO posthog_grouptypemapping "
                "(team_id, project_id, group_type, group_type_index, name_singular, name_plural) "
                "SELECT %s, %s, group_type, group_type_index, name_singular, name_plural "
                "FROM posthog_grouptypemapping "
                "WHERE project_id = %s",
                (target_team_id, target_project_id, source_project_id),
            )


def get_group_type_mapping_count(project_id: int) -> int:
    with persons_db_connection(writer=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM posthog_grouptypemapping WHERE project_id = %s",
                (project_id,),
            )
            result = cur.fetchone()
            return result[0] if result else 0
