import pytest

from posthog.models.event.sql import (
    BULK_INSERT_EVENT_SQL,
    EVENTS_JSON_DATA_TABLE,
    EVENTS_JSON_TABLE_SQL,
    INSERT_EVENT_SQL,
    TRUNCATE_EVENTS_JSON_TABLE_SQL,
)
from posthog.test.events_schema_recorder import names_events_json_table


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (INSERT_EVENT_SQL(table_name=EVENTS_JSON_DATA_TABLE), False),
        (BULK_INSERT_EVENT_SQL(table_name=EVENTS_JSON_DATA_TABLE, values="(1), (2)"), False),
        (TRUNCATE_EVENTS_JSON_TABLE_SQL(), False),
        (EVENTS_JSON_TABLE_SQL(), False),
        ("SELECT * FROM kafka_events_json_native_json", False),
        ("SELECT count() FROM events WHERE team_id = 1", False),
        ("SELECT count() FROM events_json AS events WHERE team_id = 1", True),
        ("ALTER TABLE sharded_events_json DELETE WHERE team_id = 1", True),
        ("INSERT INTO writable_events_json SELECT * FROM events_json", True),
        ("CREATE TABLE events_copy ENGINE = Memory AS SELECT * FROM events_json", True),
        ("CREATE TABLE events_copy ENGINE = Memory AS SELECT * FROM events", False),
    ],
)
def test_names_events_json_table(sql: str, expected: bool) -> None:
    assert names_events_json_table(sql) is expected
