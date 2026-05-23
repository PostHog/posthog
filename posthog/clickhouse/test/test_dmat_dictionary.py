"""Real-ClickHouse integration tests for the dmat slot-assignments dictionary.

These tests pin the dict mechanics that the dmat backfill mutation depends on:
- `dictHas` returns true for known `(team_id, column_index)` keys, false otherwise.
- `dictGetString` returns the inserted property name for known keys.
- Publishing a new generation supersedes the previous one (the dict reads `max(generation)`).

The end-to-end coercion parity is covered by
`posthog/temporal/tests/backfill_materialized_property/test_coercion_parity.py::TestDictBackedDispatchCoercion`.
This file is the focused unit-style equivalent: no event rows, no extraction, just the
dict round-trip the mutation builder relies on.
"""

import time
import uuid

from posthog.clickhouse.client import sync_execute
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME,
    INSERT_DMAT_SLOT_ASSIGNMENTS_SQL,
    RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
)


def _populate(rows: list[tuple[int, int, str]]) -> None:
    """Publish `rows` as a new generation, mirroring the populate activity. A nanosecond
    generation is strictly increasing across calls (and prior test runs), so the dictionary —
    which reads `generation = max(generation)` — always reflects the latest publish. An empty
    publish still advances the generation via the team_id=0 marker, so it clears real entries."""
    generation = time.time_ns()
    payload = [(t, c, p, generation) for (t, c, p) in rows] or [(0, 0, "", generation)]
    sync_execute(INSERT_DMAT_SLOT_ASSIGNMENTS_SQL(), payload)
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
    column_index = 8
    property_name = f"my prop with spaces {uuid.uuid4().hex[:6]}"
    _populate([(team_id, column_index, property_name)])

    result = sync_execute(
        f"SELECT dictGetString('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', 'property_name', "
        "(toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert result == [(property_name,)]


def test_new_generation_supersedes_previous() -> None:
    team_id = 3_000_003
    column_index = 7
    _populate([(team_id, column_index, "browser")])

    # Round trip on the populated state.
    has_before = sync_execute(
        f"SELECT dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert has_before == [(1,)]

    # Publish an empty generation — the activity does this when the last slot is removed.
    _populate([])

    has_after = sync_execute(
        f"SELECT dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (toUInt64(%(team)s), toUInt8(%(idx)s)))",
        {"team": team_id, "idx": column_index},
    )
    assert has_after == [(0,)], "dict must drop the entry once a newer generation omits it"


def test_distinct_team_ids_lookup_via_in_subselect() -> None:
    """The mutation's WHERE prunes on
    `team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments
                 WHERE generation = max(generation) AND team_id != 0)`.
    Confirms that subselect returns exactly the latest generation's team set (collapsing
    duplicates, excluding the marker and superseded generations) so the mutation prunes parts
    correctly.
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

    result = sync_execute(
        "SELECT DISTINCT team_id FROM dmat_slot_assignments "
        "WHERE generation = (SELECT max(generation) FROM dmat_slot_assignments) AND team_id != 0 "
        "ORDER BY team_id"
    )
    assert result == [(team_a,), (team_b,), (team_c,)]
