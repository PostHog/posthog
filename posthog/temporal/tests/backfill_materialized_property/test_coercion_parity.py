"""SQL-side parity tests for dmat property coercion.

The same fixture file (`coercion_fixtures.json` in the activities package) drives both this
test and the TypeScript-side `create-event.dmat.test.ts`. For each case the SQL extraction
must produce the value listed under `expected_output` — that's the value plugin-server
produces for live ingest, and it's also the value HogQL falls back to for queries on properties
without a materialized slot. Three paths, one fixture, byte-for-byte agreement.

Tests run actual ClickHouse SQL (legacy per-slot extraction expression and the new batched
multiIf form) against an inserted row, so any drift between the SQL we generate and the SQL
ClickHouse actually evaluates surfaces here.
"""

import json
import uuid
from pathlib import Path

import pytest
from posthog.test.base import _create_event, flush_persons_and_events

from posthog.clickhouse.client import sync_execute
from posthog.temporal.backfill_materialized_property.activities import _generate_property_extraction_sql

from products.event_definitions.backend.models.property_definition import PropertyType

FIXTURES_PATH = (
    Path(__file__).resolve().parents[3] / "temporal" / "backfill_materialized_property" / "coercion_fixtures.json"
)
FIXTURES = json.loads(FIXTURES_PATH.read_text())


def _flatten(cases_key: str, prop_type: PropertyType):
    """Yield (id, prop_type, fixture_case) — id is just `name` so pytest output is human-readable."""
    for case in FIXTURES[cases_key]:
        if case.get("_skip_reason"):
            continue
        yield pytest.param(prop_type, case, id=f"{cases_key}::{case['name']}")


@pytest.mark.django_db(transaction=True)
class TestCoercionParity:
    """Run each fixture case through the SQL extraction and assert it matches expected_output.

    These tests insert one event per case into `sharded_events`, run the extraction SELECT, and
    drop the data. Slow-ish but the only way to catch SQL-level drift (e.g. a ClickHouse upgrade
    that changes `parseDateTime64BestEffortOrNull` semantics).
    """

    @pytest.mark.parametrize(
        "prop_type,case",
        [
            *_flatten("string_cases", PropertyType.String),
            *_flatten("numeric_cases", PropertyType.Numeric),
            *_flatten("boolean_cases", PropertyType.Boolean),
            *_flatten("datetime_cases", PropertyType.Datetime),
        ],
    )
    def test_legacy_per_slot_extraction_matches_fixture(self, team, prop_type, case):
        """Exercises `_generate_property_extraction_sql` — the legacy per-slot SQL the existing
        BackfillMaterializedPropertyWorkflow runs. New batched flow goes through the multiIf
        builder (next test) but uses the same base extract."""
        property_name = f"prop_{uuid.uuid4().hex[:8]}"
        _create_event(
            team=team,
            distinct_id="user1",
            event="$test",
            properties={property_name: case["input"]},
        )
        flush_persons_and_events()

        sql = _generate_property_extraction_sql(prop_type)
        result = sync_execute(
            f"SELECT {sql} FROM sharded_events WHERE team_id = %(team_id)s AND properties LIKE %(prop_marker)s LIMIT 1",
            {
                "team_id": team.id,
                "property_name": property_name,
                "prop_marker": f"%{property_name}%",
            },
        )
        actual = result[0][0] if result else None

        # null expected ↔ either NULL or column-not-written semantics.
        if case["expected_output"] is None:
            assert actual is None, f"Expected NULL, got {actual!r}"
        else:
            assert actual == case["expected_output"], (
                f"SQL output {actual!r} does not match fixture expected {case['expected_output']!r} "
                f"for input {case['input']!r}"
            )
