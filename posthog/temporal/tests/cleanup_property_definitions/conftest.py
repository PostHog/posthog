"""Shared fixtures and utilities for cleanup_property_definitions tests."""

import uuid
from datetime import datetime

import pytest

from posthog.clickhouse.client.execute import sync_execute


def insert_property_definition_to_ch(
    team_id: int,
    name: str,
    property_type: int = 2,
    last_seen_at: datetime | None = None,
) -> None:
    """Insert a property definition directly into ClickHouse property_definitions table.

    Args:
        team_id: The team ID
        name: The property name
        property_type: 1=event, 2=person, 3=group, 4=session (default: 2 for person)
        last_seen_at: When the property was last seen (default: now)
    """
    if last_seen_at is None:
        last_seen_at = datetime.now()

    sync_execute(
        """
        INSERT INTO property_definitions (team_id, name, type, last_seen_at)
        VALUES (%(team_id)s, %(name)s, %(type)s, %(last_seen_at)s)
        """,
        {
            "team_id": team_id,
            "name": name,
            "type": property_type,
            "last_seen_at": last_seen_at,
        },
    )


def get_ch_property_definitions(team_id: int, property_type: int = 2) -> list[dict]:
    """Get property definitions from ClickHouse for a team.

    Args:
        team_id: The team ID
        property_type: 1=event, 2=person, 3=group, 4=session (default: 2 for person)

    Returns:
        List of property definition dicts with keys: name, type, last_seen_at
    """
    result = sync_execute(
        """
        SELECT name, type, last_seen_at
        FROM property_definitions FINAL
        WHERE team_id = %(team_id)s AND type = %(type)s
        ORDER BY name
        """,
        {"team_id": team_id, "type": property_type},
    )
    return [{"name": row[0], "type": row[1], "last_seen_at": row[2]} for row in result]


def cleanup_ch_property_definitions(team_id: int, names: list[str]) -> None:
    """Delete property definitions from ClickHouse using lightweight delete.

    Args:
        team_id: The team ID
        names: List of property names to delete
    """
    if not names:
        return

    sync_execute(
        """
        DELETE FROM property_definitions
        WHERE team_id = %(team_id)s AND name IN %(names)s
        """,
        {"team_id": team_id, "names": names},
    )


@pytest.fixture
def test_prefix():
    """Generate a unique prefix for test data to avoid collisions."""
    return f"test-cleanup-{uuid.uuid4().hex[:8]}"
