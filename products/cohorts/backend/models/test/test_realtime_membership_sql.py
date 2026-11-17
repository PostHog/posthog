import json
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest

from posthog.clickhouse.client import sync_execute

from products.cohorts.backend.models.realtime_membership_sql import (
    KAFKA_REALTIME_COHORT_MEMBERSHIP_COLUMNS,
    REALTIME_COHORT_MEMBERSHIP_MV_SELECT_SQL,
    REALTIME_COHORT_MEMBERSHIP_TABLE,
    REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
    WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE,
    WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL,
)

ZERO = UUID(int=0)
RUN = UUID("01928c3e-0000-7000-8000-000000000001")
ENTERED = UUID(int=1)
RECONCILED = UUID(int=2)
LEFT = UUID(int=3)
THRESHOLD = "2026-09-21 03:00:00.214331"


def change(person_id: UUID | str, **fields: object) -> dict[str, object]:
    return {
        "team_id": 7,
        "cohort_id": 42,
        "person_id": str(person_id),
        "status": "entered",
        "last_updated": "2026-09-21 03:00:00.400000",
        **fields,
    }


def floor_copy(partition: int, **fields: object) -> dict[str, object]:
    # _partition stands in for the Kafka table's virtual column.
    return {
        "type": "sweep_floor",
        "team_id": 7,
        "cohort_id": 42,
        "run_id": str(RUN),
        "threshold": THRESHOLD,
        "partitions": 64,
        "_partition": partition,
        **fields,
    }


@pytest.fixture
def membership_tables(clickhouse_database) -> Iterator[None]:
    sync_execute(REALTIME_COHORT_MEMBERSHIP_TABLE_SQL())
    sync_execute(WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL())
    sync_execute(TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL)
    try:
        yield
    finally:
        sync_execute(TRUNCATE_REALTIME_COHORT_MEMBERSHIP_TABLE_SQL)


@pytest.mark.usefixtures("membership_tables")
def test_view_stores_changes_and_floor_copies_and_drops_the_rest() -> None:
    messages = [
        change(ENTERED, last_updated="2026-09-21 03:00:00.100000"),
        change(RECONCILED, last_updated="2026-09-21 03:00:00.200000", origin="reconcile", run_id=str(RUN)),
        change(LEFT, last_updated="2026-09-21 03:00:00.300000", status="left"),
        floor_copy(3),
        floor_copy(5),
        change(UUID(int=4), type="membership_hint"),
        change("not-a-uuid"),
        {"team_id": 7, "cohort_id": 42, "person_id": str(UUID(int=5)), "status": "entered"},
        change(UUID(int=6), last_updated="2026-09-21 03:00:00.400"),
        change(UUID(int=7), status="member"),
        floor_copy(7, run_id="not-a-uuid"),
    ]
    source = "format(JSONEachRow, %(columns)s, %(messages)s)"

    sync_execute(
        f"INSERT INTO {WRITABLE_REALTIME_COHORT_MEMBERSHIP_TABLE} {REALTIME_COHORT_MEMBERSHIP_MV_SELECT_SQL(source)}",
        {
            "columns": f"{KAFKA_REALTIME_COHORT_MEMBERSHIP_COLUMNS}, _partition UInt64",
            "messages": "\n".join(map(json.dumps, messages)),
        },
        settings={"distributed_foreground_insert": 1},
    )

    stamp = datetime(2026, 9, 21, 3, 0, 0, tzinfo=UTC)
    floor_version = datetime(2026, 9, 21, 3, 0, 0, 214331, tzinfo=UTC)
    assert sync_execute(
        f"SELECT * FROM {REALTIME_COHORT_MEMBERSHIP_TABLE} ORDER BY kind, toString(person_id), floor_partition"
    ) == [
        (7, 42, "member", ENTERED, ZERO, 0, 1, stamp.replace(microsecond=100000), 0),
        (7, 42, "member", RECONCILED, ZERO, 0, 1, stamp.replace(microsecond=200000), 0),
        (7, 42, "member", LEFT, ZERO, 0, 0, stamp.replace(microsecond=300000), 0),
        (7, 42, "floor", ZERO, RUN, 3, 0, floor_version, 64),
        (7, 42, "floor", ZERO, RUN, 5, 0, floor_version, 64),
    ]
