"""SQL-side parity tests for the dmat string extraction.

The same fixture file (`coercion_fixtures.json` in the activities package) drives both this
test and the TypeScript-side `create-event.dmat.test.ts`. For each case the SQL extraction
must produce the value listed under `expected_output` — that's the value plugin-server
produces for live ingest, and it's also the value HogQL falls back to for queries on
properties without a materialized slot. Three paths, one fixture, byte-for-byte agreement.

Per the dmat RFC every dmat column is `Nullable(String)`, so this fixture only covers the
string extraction. Type-cast parity (toFloat / toBool / toDateTime applied at HogQL read
time) is covered separately in `test_property_types_dmat.py::TestDmatExtractionConsistency`.

Tests run actual ClickHouse SQL against an inserted row, so any drift between the SQL we
generate and the SQL ClickHouse actually evaluates surfaces here.

Two test classes:

- ``TestCoercionParity`` exercises the bare ``_generate_property_extraction_sql`` shape
  with the property name passed as a query parameter — the same path used by HogQL's
  JSON fallback and by the legacy multiIf-based mutation. Pins the inner-extract
  contract.

- ``TestDictBackedDispatchCoercion`` exercises the full
  ``if(dictHas(...), JSONExtractRaw(properties, dictGetString(...)), col)`` dispatch
  used by the dict-backed mutation introduced for the dictionary-keyed backfill.
  Property name is sourced from the dict at runtime instead of a query parameter, so
  the SQL strings are NOT byte-identical to the bare-extract path — but the runtime
  output must match for every fixture case.
"""

import json
import uuid
from pathlib import Path

import pytest
from posthog.test.base import _create_event, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME,
    INSERT_DMAT_SLOT_ASSIGNMENTS_SQL,
    RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL,
)
from posthog.temporal.backfill_materialized_property.activities import _generate_property_extraction_sql

FIXTURES_PATH = (
    Path(__file__).resolve().parents[3] / "temporal" / "backfill_materialized_property" / "coercion_fixtures.json"
)
FIXTURES = json.loads(FIXTURES_PATH.read_text())


def _string_cases():
    for case in FIXTURES["string_cases"]:
        if case.get("_skip_reason"):
            continue
        yield pytest.param(case, id=f"string_cases::{case['name']}")


@pytest.mark.django_db
class TestCoercionParity:
    @pytest.mark.parametrize("case", list(_string_cases()))
    def test_extraction_sql_matches_fixture(self, team, case):
        # Inserts one event per case into `sharded_events`, runs the extraction SELECT,
        # and asserts byte equality with the shared fixture. Slow-ish but the only way to
        # catch SQL-level drift (e.g. a ClickHouse upgrade that changes how `JSONExtractRaw`
        # quotes its output).
        property_name = f"prop_{uuid.uuid4().hex[:8]}"
        _create_event(
            team=team,
            distinct_id="user1",
            event="$test",
            properties={property_name: case["input"]},
        )
        flush_persons_and_events()

        sql = _generate_property_extraction_sql()
        result = sync_execute(
            f"SELECT {sql} FROM sharded_events WHERE team_id = %(team_id)s AND properties LIKE %(prop_marker)s LIMIT 1",
            {
                "team_id": team.id,
                "property_name": property_name,
                "prop_marker": f"%{property_name}%",
            },
        )
        actual = result[0][0] if result else None

        if case["expected_output"] is None:
            assert actual is None, f"Expected NULL, got {actual!r}"
        else:
            assert actual == case["expected_output"], (
                f"SQL output {actual!r} does not match fixture expected {case['expected_output']!r} "
                f"for input {case['input']!r}"
            )


def _populate_dict(team_id: int, column_index: int, property_name: str) -> None:
    """Replace the dict's contents with a single (team_id, column_index, property_name)
    row, then reload so the next dictGet/dictHas sees the new state. Using TRUNCATE+INSERT
    matches what the populate_slot_assignments activity does in production."""
    sync_execute(TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL())
    sync_execute(
        INSERT_DMAT_SLOT_ASSIGNMENTS_SQL(),
        [(team_id, column_index, property_name)],
    )
    sync_execute(RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL())


def _dict_backed_dispatch_sql(column_index: int, fallback_value: str = "NULL") -> str:
    """The full dispatch shape used by the dict-backed mutation. Mirrors
    `_build_dict_backed_update_command` in activities.py; kept inline here so the test
    fails loudly if either side drifts."""
    property_name_expr = (
        f"dictGetString('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', 'property_name', (team_id, {column_index}))"
    )
    extract_sql = (
        f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, {property_name_expr}), ''), 'null'), '^\"|\"$', '')"
    )
    return (
        f"if(dictHas('{DMAT_SLOT_ASSIGNMENTS_DICTIONARY_NAME}', (team_id, {column_index})), "
        f"{extract_sql}, "
        f"{fallback_value})"
    )


@pytest.mark.django_db
class TestDictBackedDispatchCoercion:
    """The dict-based mutation reads property names out of `dmat_slot_assignments_dict`
    via `dictGetString` instead of a query parameter. Same wrapper, different way of
    sourcing the property name — runtime output must match the bare-extract path for
    every fixture case so plugin-server / HogQL JSON fallback / dict-based backfill
    agree byte-for-byte.
    """

    @pytest.mark.parametrize("case", list(_string_cases()))
    def test_dispatch_extraction_matches_fixture(self, team, case):
        property_name = f"prop_{uuid.uuid4().hex[:8]}"
        column_index = 0
        _create_event(
            team=team,
            distinct_id="user1",
            event="$test",
            properties={property_name: case["input"]},
        )
        flush_persons_and_events()
        _populate_dict(team.id, column_index, property_name)

        dispatch_sql = _dict_backed_dispatch_sql(column_index)
        result = sync_execute(
            f"SELECT {dispatch_sql} FROM sharded_events "
            "WHERE team_id = %(team_id)s AND properties LIKE %(prop_marker)s LIMIT 1",
            {"team_id": team.id, "prop_marker": f"%{property_name}%"},
        )
        actual = result[0][0] if result else None

        if case["expected_output"] is None:
            assert actual is None, f"Expected NULL, got {actual!r}"
        else:
            assert actual == case["expected_output"], (
                f"Dispatch SQL output {actual!r} does not match fixture expected "
                f"{case['expected_output']!r} for input {case['input']!r}"
            )

    def test_empty_dict_falls_through_to_column_value(self, team):
        """When the dict has no entry for (team_id, column_index), the dispatch must
        return the fallback (the column itself in the production builder, NULL here so
        we can assert via SELECT). Confirms the no-op path that protects unrelated
        teams' rows from being clobbered when the mutation runs."""
        sync_execute(TRUNCATE_DMAT_SLOT_ASSIGNMENTS_SQL())
        sync_execute(RELOAD_DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL())

        property_name = f"prop_{uuid.uuid4().hex[:8]}"
        _create_event(
            team=team,
            distinct_id="user1",
            event="$test",
            properties={property_name: "should-not-be-extracted"},
        )
        flush_persons_and_events()

        dispatch_sql = _dict_backed_dispatch_sql(column_index=0, fallback_value="NULL")
        result = sync_execute(
            f"SELECT {dispatch_sql} FROM sharded_events "
            "WHERE team_id = %(team_id)s AND properties LIKE %(prop_marker)s LIMIT 1",
            {"team_id": team.id, "prop_marker": f"%{property_name}%"},
        )
        actual = result[0][0] if result else None
        assert actual is None, f"Expected NULL fallback when dict is empty, got {actual!r}"
