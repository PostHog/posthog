"""Seeding for the three merge scenarios.

Seeding writes through plain SQL against the baseline schema's tables when the
strategy uses them; strategies with a different storage format provide a
`seed_person` hook instead. Each rep gets fresh distinct ids inside one shared
team so index depth grows realistically across reps.
"""

import uuid as uuidlib
from dataclasses import dataclass

import psycopg

TEAM_ID = 1

# Background rows so btree depth and FK lookups behave like a real tenant,
# not an empty table.
PRELOAD_PERSONS = 50_000
PRELOAD_DIDS_PER_PERSON = 3


@dataclass(frozen=True, kw_only=True)
class SeededCase:
    case: str  # "neither" | "one" | "both"
    target_distinct_id: str
    anon_distinct_id: str
    # distinct ids that must resolve to the surviving person afterwards
    expected_distinct_ids: list[str]
    source_did_count: int
    cohort_rows: int
    ff_rows: int


def preload(
    conn: psycopg.Connection, persons: int = PRELOAD_PERSONS, dids_per_person: int = PRELOAD_DIDS_PER_PERSON
) -> None:
    """Bulk background population, set-based for speed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH people AS (
                INSERT INTO posthog_person (created_at, properties, team_id, is_identified, uuid, version)
                SELECT now() - (g || ' seconds')::interval, '{}'::jsonb, %s, false, gen_random_uuid(), 0
                FROM generate_series(1, %s) g
                RETURNING id
            )
            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
            SELECT 'preload-' || p.id || '-' || d, p.id, %s, 0
            FROM people p, generate_series(1, %s) d
            """,
            (TEAM_ID, persons, TEAM_ID, dids_per_person),
        )
    conn.commit()


def seed_chain_persons(
    conn: psycopg.Connection,
    person_count: int,
    dids_per_person: int,
    tag: str,
) -> list[list[str]]:
    """Persons for the chain workload: `person_count` persons, each owning
    `dids_per_person` distinct ids. Returns each person's distinct ids;
    index 0 is the chain's first source (deepest after repeated merges).
    """
    did_lists = [[f"chain-{tag}-p{p}-{d}" for d in range(dids_per_person)] for p in range(person_count)]
    with conn.cursor() as cur:
        # Set-based: one statement seeds every person and mapping. Person ids
        # are sequential, so row_number() over id reproduces the p0..pN order
        # the client-side did names encode.
        cur.execute(
            """
            WITH people AS (
                INSERT INTO posthog_person (created_at, properties, team_id, is_identified, uuid, version)
                SELECT now(), '{}'::jsonb, %s, false, gen_random_uuid(), 0
                FROM generate_series(0, %s - 1)
                RETURNING id
            ),
            numbered AS (
                SELECT id, row_number() OVER (ORDER BY id) - 1 AS pnum FROM people
            )
            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
            SELECT 'chain-' || %s || '-p' || n.pnum || '-' || d, n.id, %s, 0
            FROM numbered n, generate_series(0, %s - 1) d
            """,
            (TEAM_ID, person_count, tag, TEAM_ID, dids_per_person),
        )
    conn.commit()
    return did_lists


def seed_case(
    conn: psycopg.Connection,
    case: str,
    source_did_count: int,
    tag: str,
    cohort_rows: int = 2,
    ff_rows: int = 2,
) -> SeededCase:
    """Create the persons/mappings a single identify call will operate on.

    both:    source person with `source_did_count` distinct ids (+ cohort/FF
             rows), target person with one distinct id.
    one:     target person exists with one distinct id; anon id is unknown.
    neither: both distinct ids unknown.
    """
    target_did = f"user-{tag}"
    anon_did = f"anon-{tag}-0"

    if case == "neither":
        return SeededCase(
            case=case,
            target_distinct_id=target_did,
            anon_distinct_id=anon_did,
            expected_distinct_ids=[target_did, anon_did],
            source_did_count=0,
            cohort_rows=0,
            ff_rows=0,
        )

    with conn.cursor() as cur:
        if case in ("one", "both"):
            cur.execute(
                """
                WITH p AS (
                    INSERT INTO posthog_person (created_at, properties, team_id, is_identified, uuid, version)
                    VALUES (now(), %s, %s, false, %s, 0)
                    RETURNING id
                )
                INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                SELECT %s, p.id, %s, 0 FROM p
                RETURNING person_id
                """,
                ('{"plan": "free", "seeded": "target"}', TEAM_ID, str(uuidlib.uuid4()), target_did, TEAM_ID),
            )

        expected = [target_did, anon_did]
        if case == "both":
            anon_dids = [f"anon-{tag}-{i}" for i in range(source_did_count)]
            expected = [target_did, *anon_dids]
            cur.execute(
                """
                WITH p AS (
                    INSERT INTO posthog_person (created_at, properties, team_id, is_identified, uuid, version)
                    VALUES (now() - interval '30 days', %s, %s, false, %s, 0)
                    RETURNING id
                ),
                dids AS (
                    INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                    SELECT d, p.id, %s, 0 FROM p, unnest(%s::text[]) d
                ),
                cohorts AS (
                    INSERT INTO posthog_cohortpeople (version, cohort_id, person_id)
                    SELECT 0, c, p.id FROM p, generate_series(1, %s) c
                )
                INSERT INTO posthog_featureflaghashkeyoverride (feature_flag_key, hash_key, person_id, team_id)
                SELECT 'flag-' || f, 'hash-' || %s, p.id, %s FROM p, generate_series(1, %s) f
                """,
                (
                    '{"utm_source": "seeded-source", "device": "mobile"}',
                    TEAM_ID,
                    str(uuidlib.uuid4()),
                    TEAM_ID,
                    anon_dids,
                    cohort_rows,
                    tag,
                    TEAM_ID,
                    ff_rows,
                ),
            )
    conn.commit()

    return SeededCase(
        case=case,
        target_distinct_id=target_did,
        anon_distinct_id=anon_did,
        expected_distinct_ids=expected,
        source_did_count=source_did_count if case == "both" else 0,
        cohort_rows=cohort_rows if case == "both" else 0,
        ff_rows=ff_rows if case == "both" else 0,
    )
