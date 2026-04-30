# ruff: noqa: T201 allow print statements
"""
Syncs person/group data from ClickHouse into the persons Postgres database
using raw psycopg2, bypassing Django ORM and Django's database configuration.

The persons DB URL is read directly from PERSONS_DATABASE_URL (the same env var
used by Rust/Node services), keeping Django completely decoupled from the
persons database.
"""

import os
import json
from typing import Any

import psycopg2
from psycopg2.extras import execute_values

from posthog.clickhouse.client import query_with_columns


def _get_persons_db_url() -> str:
    url = os.getenv("PERSONS_DATABASE_URL")
    if not url:
        pg_user = os.getenv("PGUSER", "posthog")
        pg_password = os.getenv("PGPASSWORD", "posthog")
        pg_host = os.getenv("PGHOST", "localhost")
        pg_port = os.getenv("PGPORT", "5432")
        url = f"postgres://{pg_user}:{pg_password}@{pg_host}:{pg_port}/posthog_persons"
    return url


def sync_persons_to_postgres(
    source_team_id: int, target_team_id: int, person_table_name: str = "posthog_person"
) -> None:
    from posthog.models.group.sql import SELECT_GROUPS_OF_TEAM
    from posthog.models.person.sql import SELECT_PERSON_DISTINCT_ID2S_OF_TEAM, SELECT_PERSONS_OF_TEAM

    persons_db_url = _get_persons_db_url()
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

    with psycopg2.connect(persons_db_url) as conn:
        with conn.cursor() as cur:
            uuid_to_pk = _insert_persons(cur, clickhouse_persons, target_team_id, person_table_name)
            _insert_person_distinct_ids(cur, clickhouse_distinct_ids, target_team_id, uuid_to_pk)
            _insert_groups(cur, clickhouse_groups, target_team_id)
        conn.commit()


def _insert_persons(
    cur: Any,
    clickhouse_persons: list[dict],
    target_team_id: int,
    person_table_name: str,
) -> dict[str, int]:
    if not clickhouse_persons:
        return {}

    rows = []
    uuids_in_order: list[str] = []
    for row in clickhouse_persons:
        uuid = str(row["uuid"])
        properties = row.get("properties", "{}")
        if isinstance(properties, str):
            properties = json.loads(properties)
        properties_json = json.dumps(properties)

        rows.append(
            (
                target_team_id,
                uuid,
                properties_json,
                row.get("is_identified", False),
                row.get("created_at"),
                row.get("version"),
                row.get("last_seen_at"),
            )
        )
        uuids_in_order.append(uuid)

    result = execute_values(
        cur,
        f"""
        INSERT INTO {person_table_name} (team_id, uuid, properties, is_identified, created_at, version, last_seen_at)
        VALUES %s
        RETURNING id, uuid
        """,
        rows,
        fetch=True,
    )

    uuid_to_pk: dict[str, int] = {}
    for pk, uuid in result:
        uuid_to_pk[str(uuid)] = pk

    return uuid_to_pk


def _insert_person_distinct_ids(
    cur: Any,
    clickhouse_distinct_ids: list[dict],
    target_team_id: int,
    uuid_to_pk: dict[str, int],
) -> None:
    if not clickhouse_distinct_ids:
        return

    rows = []
    for row in clickhouse_distinct_ids:
        person_uuid = str(row.get("person_uuid", ""))
        person_pk = uuid_to_pk.get(person_uuid)
        if person_pk is None:
            continue

        rows.append(
            (
                target_team_id,
                row.get("distinct_id"),
                person_pk,
                row.get("version", 0),
            )
        )

    if rows:
        execute_values(
            cur,
            """
            INSERT INTO posthog_persondistinctid (team_id, distinct_id, person_id, version)
            VALUES %s
            ON CONFLICT DO NOTHING
            """,
            rows,
        )


def _insert_groups(
    cur: Any,
    clickhouse_groups: list[dict],
    target_team_id: int,
) -> None:
    if not clickhouse_groups:
        return

    rows = []
    for row in clickhouse_groups:
        group_properties = row.get("group_properties", "{}")
        if isinstance(group_properties, str):
            group_properties = json.loads(group_properties)

        rows.append(
            (
                target_team_id,
                row.get("group_type_index"),
                row.get("group_key"),
                json.dumps(group_properties),
                row.get("created_at"),
                0,  # version
                json.dumps({}),  # properties_last_updated_at
                json.dumps({}),  # properties_last_operation
            )
        )

    execute_values(
        cur,
        """
        INSERT INTO posthog_group
            (team_id, group_type_index, group_key, group_properties, created_at, version,
             properties_last_updated_at, properties_last_operation)
        VALUES %s
        ON CONFLICT DO NOTHING
        """,
        rows,
    )


def bulk_create_group_type_mappings(
    team_id: int,
    project_id: int,
    mappings: list[dict[str, Any]],
) -> None:
    if not mappings:
        return

    persons_db_url = _get_persons_db_url()
    rows = []
    for m in mappings:
        rows.append(
            (
                team_id,
                project_id,
                m["group_type_index"],
                m["group_type"],
                m.get("name_singular"),
                m.get("name_plural"),
            )
        )

    with psycopg2.connect(persons_db_url) as conn:
        with conn.cursor() as cur:
            try:
                execute_values(
                    cur,
                    """
                    INSERT INTO posthog_grouptypemapping
                        (team_id, project_id, group_type_index, group_type, name_singular, name_plural)
                    VALUES %s
                    """,
                    rows,
                )
            except psycopg2.IntegrityError as e:
                print(f"SKIPPING GROUP TYPE MAPPING CREATION: {e}")
                conn.rollback()
                return
        conn.commit()


def delete_group_type_mappings(project_id: int) -> None:
    persons_db_url = _get_persons_db_url()
    with psycopg2.connect(persons_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM posthog_grouptypemapping WHERE project_id = %s",
                (project_id,),
            )
        conn.commit()


def copy_group_type_mappings(source_project_id: int, target_team_id: int, target_project_id: int) -> None:
    persons_db_url = _get_persons_db_url()
    with psycopg2.connect(persons_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM posthog_grouptypemapping WHERE project_id = %s",
                (target_project_id,),
            )
            cur.execute(
                """
                INSERT INTO posthog_grouptypemapping
                    (team_id, project_id, group_type, group_type_index, name_singular, name_plural)
                SELECT %s, %s, group_type, group_type_index, name_singular, name_plural
                FROM posthog_grouptypemapping
                WHERE project_id = %s
                """,
                (target_team_id, target_project_id, source_project_id),
            )
        conn.commit()


def get_group_type_mapping_count(project_id: int) -> int:
    persons_db_url = _get_persons_db_url()
    with psycopg2.connect(persons_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM posthog_grouptypemapping WHERE project_id = %s",
                (project_id,),
            )
            result = cur.fetchone()
            return result[0] if result else 0
