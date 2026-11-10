"""Per-team damage gauge: how many old ClickHouse persons and mappings Postgres still holds."""

from __future__ import annotations

from datetime import datetime

from posthog.models.person.util import _batched_get_persons_by_distinct_ids
from posthog.personhog_client.client import personhog_call

from . import datatypes, lookups

_TEAM_CHECK_SETTINGS = {"max_execution_time": 900, "max_memory_usage": 32_000_000_000}

# The hash pre-filter keeps about this many times the sample, so the sample stays full size and uniform.
_TEAM_CHECK_OVERSAMPLE = 10

_TEAM_PERSON_ROWS_SQL = "SELECT count() FROM person WHERE team_id = %(team_id)s"

_TEAM_MAPPING_ROWS_SQL = "SELECT count() FROM person_distinct_id2 WHERE team_id = %(team_id)s"

_TEAM_PERSONS_SQL = """
SELECT toString(id)
FROM person
WHERE team_id = %(team_id)s AND cityHash64(id) %% %(modulus)s = 0
GROUP BY id
HAVING argMax(is_deleted, version) = 0 AND max(_timestamp) < fromUnixTimestamp(%(before)s)
ORDER BY cityHash64(id)
LIMIT %(limit)s
"""

_TEAM_MAPPINGS_SQL = """
SELECT distinct_id
FROM person_distinct_id2
WHERE team_id = %(team_id)s AND cityHash64(distinct_id) %% %(modulus)s = 0
GROUP BY distinct_id
HAVING argMax(is_deleted, version) = 0 AND max(_timestamp) < fromUnixTimestamp(%(before)s)
ORDER BY cityHash64(distinct_id)
LIMIT %(limit)s
"""


def _team_check_modulus(rows: int, sample_size: int) -> int:
    return max(1, rows // max(1, sample_size * _TEAM_CHECK_OVERSAMPLE))


def _team_check_args(rows_sql: str, *, team_id: int, sample_size: int, before: datetime) -> dict[str, int]:
    [[rows]] = lookups._ch(rows_sql, {"team_id": team_id}, _TEAM_CHECK_SETTINGS)
    return {
        "team_id": team_id,
        "before": int(before.timestamp()),
        "limit": sample_size,
        "modulus": _team_check_modulus(int(rows), sample_size),
    }


def check_team(*, team_id: int, sample_size: int, before: datetime) -> datatypes.TeamCheck:
    """Count how many of a team's old live ClickHouse persons and mappings Postgres still holds live."""
    person_args = _team_check_args(_TEAM_PERSON_ROWS_SQL, team_id=team_id, sample_size=sample_size, before=before)
    mapping_args = _team_check_args(_TEAM_MAPPING_ROWS_SQL, team_id=team_id, sample_size=sample_size, before=before)
    person_uuids = [row[0] for row in lookups._ch(_TEAM_PERSONS_SQL, person_args, _TEAM_CHECK_SETTINGS)]
    distinct_ids = [row[0] for row in lookups._ch(_TEAM_MAPPINGS_SQL, mapping_args, _TEAM_CHECK_SETTINGS)]
    live_persons = (
        lookups._live_person_versions(team_id, person_uuids, "person_divergence_team_check") if person_uuids else {}
    )
    live_mappings = (
        personhog_call(
            "person_divergence_team_check",
            lambda: _batched_get_persons_by_distinct_ids(
                team_id,
                distinct_ids,
                "person_divergence_team_check",
                deduplicate_by_person=False,
                read_options=lookups._VERSION_ONLY_READ_OPTIONS,
            ),
        )
        if distinct_ids
        else []
    )
    return datatypes.TeamCheck(
        team_id=team_id,
        persons_sampled=len(person_uuids),
        persons_live_in_postgres=len(live_persons),
        distinct_ids_sampled=len(distinct_ids),
        distinct_ids_live_in_postgres=len({r.distinct_id for r in live_mappings}),
    )
