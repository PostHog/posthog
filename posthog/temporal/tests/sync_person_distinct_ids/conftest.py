"""Shared fixtures and utilities for sync_person_distinct_ids tests."""

import uuid
from datetime import datetime

import pytest

from posthog.clickhouse.client.execute import sync_execute

# ============================================================================
# ClickHouse Helper Functions
# ============================================================================


def insert_person_to_ch(team_id: int, person_uuid: str, version: int = 0, is_deleted: int = 0) -> None:
    """Insert a person directly into ClickHouse person table."""
    sync_execute(
        """
        INSERT INTO person (id, team_id, properties, is_deleted, is_identified, version, _timestamp, _offset)
        VALUES (%(uuid)s, %(team_id)s, '{}', %(is_deleted)s, 0, %(version)s, now(), 0)
        """,
        {
            "uuid": person_uuid,
            "team_id": team_id,
            "version": version,
            "is_deleted": is_deleted,
        },
    )


def insert_persons_to_ch_batch(team_id: int, person_uuids: list[str], version: int = 0, is_deleted: int = 0) -> None:
    """Insert multiple persons directly into ClickHouse person table in a single batch."""
    if not person_uuids:
        return
    now = datetime.now()
    values = [(person_uuid, team_id, "{}", is_deleted, 0, version, now, 0) for person_uuid in person_uuids]
    sync_execute(
        "INSERT INTO person (id, team_id, properties, is_deleted, is_identified, version, _timestamp, _offset) VALUES",
        values,
    )


def insert_distinct_id_to_ch(team_id: int, person_uuid: str, distinct_id: str, version: int = 0) -> None:
    """Insert a distinct ID directly into ClickHouse person_distinct_id2 table."""
    sync_execute(
        """
        INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset, _partition)
        VALUES (%(team_id)s, %(distinct_id)s, %(person_id)s, 0, %(version)s, now(), 0, 0)
        """,
        {
            "team_id": team_id,
            "distinct_id": distinct_id,
            "person_id": person_uuid,
            "version": version,
        },
    )


def get_ch_person(team_id: int, person_uuid: str) -> dict | None:
    """Get a person from ClickHouse."""
    result = sync_execute(
        """
        SELECT id, team_id, is_deleted, version
        FROM person FINAL
        WHERE team_id = %(team_id)s AND id = %(person_uuid)s
        """,
        {"team_id": team_id, "person_uuid": person_uuid},
    )
    if result:
        return {"id": result[0][0], "team_id": result[0][1], "is_deleted": result[0][2], "version": result[0][3]}
    return None


def get_ch_distinct_id(team_id: int, distinct_id: str) -> dict | None:
    """Get a distinct ID from ClickHouse."""
    result = sync_execute(
        """
        SELECT person_id, distinct_id, version, is_deleted
        FROM person_distinct_id2 FINAL
        WHERE team_id = %(team_id)s AND distinct_id = %(distinct_id)s
        """,
        {"team_id": team_id, "distinct_id": distinct_id},
    )
    if result:
        return {
            "person_id": result[0][0],
            "distinct_id": result[0][1],
            "version": result[0][2],
            "is_deleted": result[0][3],
        }
    return None


def cleanup_ch_test_data(team_id: int, person_uuids: list[str], distinct_ids: list[str]) -> None:
    """Mark test persons as deleted in ClickHouse using batch inserts."""
    now = datetime.now()
    null_uuid = "00000000-0000-0000-0000-000000000000"

    if person_uuids:
        person_values = [(person_uuid, team_id, "{}", 1, 0, 1000, now, 0) for person_uuid in person_uuids]
        sync_execute(
            "INSERT INTO person (id, team_id, properties, is_deleted, is_identified, version, _timestamp, _offset) VALUES",
            person_values,
        )
    if distinct_ids:
        did_values = [(team_id, distinct_id, null_uuid, 1, 1000, now, 0, 0) for distinct_id in distinct_ids]
        sync_execute(
            "INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset, _partition) VALUES",
            did_values,
        )


def get_orphaned_person_count(team_id: int) -> int:
    """Count orphaned persons in ClickHouse for a team."""
    result = sync_execute(
        """
        SELECT count() FROM person FINAL
        WHERE team_id = %(team_id)s
          AND is_deleted = 0
          AND id NOT IN (
            SELECT DISTINCT person_id FROM person_distinct_id2 FINAL
            WHERE team_id = %(team_id)s
          )
        """,
        {"team_id": team_id},
    )
    return result[0][0] if result else 0


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_prefix():
    """Generate a unique prefix for test data to avoid collisions."""
    return f"test-sync-{uuid.uuid4().hex[:8]}"
