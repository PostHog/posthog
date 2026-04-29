"""Real-ClickHouse integration tests for the dmat slot-assignments dictionary.

These tests pin the dict mechanics that the dmat backfill mutation depends on:
- `dictHas` returns true for known `(team_id, column_index)` keys, false otherwise.
- `dictGetString` returns the inserted property name for known keys.
- Reload picks up new rows after TRUNCATE+INSERT.

The end-to-end coercion parity is covered by
`posthog/temporal/tests/backfill_materialized_property/test_coercion_parity.py::TestDictBackedDispatchCoercion`.
This file is the focused unit-style equivalent: no event rows, no extraction, just the
dict round-trip the mutation builder relies on.
"""

import uuid

import pytest

from posthog.clickhouse.client import sync_execute
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME,
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    DMAT_SLOT_ASSIGNMENTS_TABLE_SQL,
    INSERT_DMAT_SLOT_ASSIGNMENTS_SQL,
    RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL,
)


@pytest.fixture(autouse=True)
def ensure_dmat_dictionary_exists():
    # Migration 0244 creates these in production; recreate idempotently here so the
    # tests are self-contained when running against a fresh test DB.
    sync_execute(DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster=False))
    sync_execute(DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster=False))
    yield


def _populate(rows: list[tuple[int, int, str]]) -> None:
    sync_execute(TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL())
    if rows:
        sync_execute(INSERT_DMAT_SLOT_ASSIGNMENTS_SQL(), rows)
    sync_execute(RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL())


def test_dict_has_returns_true_for_known_keys() -> None:
    team_id = 1_000_001
    column_index = 5
    property_name = f"prop_{uuid.uuid4().hex[:8]}"
    _populate([(team_id, column_index, property_name)])

    result = sync_execute(
        f"SELECT dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert result == [(1,)]


def test_dict_has_returns_false_for_unknown_keys() -> None:
    _populate([])  # empty dict

    result = sync_execute(
        f"SELECT dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": 999_999, "idx": 0},
    )
    assert result == [(0,)]


def test_dict_get_string_round_trips_property_name() -> None:
    team_id = 2_000_002
    column_index = 12
    property_name = f"my prop with spaces {uuid.uuid4().hex[:6]}"
    _populate([(team_id, column_index, property_name)])

    result = sync_execute(
        f"SELECT dictGetString('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', 'property_name', "
        "(toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert result == [(property_name,)]


def test_truncate_then_reload_clears_dict() -> None:
    team_id = 3_000_003
    column_index = 7
    _populate([(team_id, column_index, "browser")])

    # Round trip on the populated state.
    has_before = sync_execute(
        f"SELECT dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert has_before == [(1,)]

    # Truncate and reload — the populate activity uses this exact pattern every cycle.
    _populate([])

    has_after = sync_execute(
        f"SELECT dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert has_after == [(0,)], "dict must drop the entry after TRUNCATE+RELOAD"


def test_distinct_team_ids_lookup_via_in_subselect() -> None:
    """The mutation's WHERE uses `team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)`.
    Confirms the subselect actually returns the right team set so the mutation prunes
    parts correctly.
    """
    team_a = 4_000_001
    team_b = 4_000_002
    team_c = 4_000_003
    _populate(
        [
            (team_a, 0, "p1"),
            (team_a, 1, "p2"),  # team_a appears twice — DISTINCT must collapse it.
            (team_b, 3, "p3"),
            (team_c, 5, "p4"),
        ]
    )

    result = sync_execute("SELECT DISTINCT team_id FROM dmat_slot_assignments ORDER BY team_id")
    assert result == [(team_a,), (team_b,), (team_c,)]
