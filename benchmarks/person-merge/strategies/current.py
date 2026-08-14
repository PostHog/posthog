"""Baseline: the production merge path, statement-for-statement.

SQL mirrors nodejs/src/common/persons/repositories/postgres-person-repository.ts
on the legacy (non-tombstone) path, which is what runs by default today:

- fetchPerson(forUpdate)            -> _fetch_for_update
- insertPerson (legacy CTE)         -> _create_person_with_both_ids
- addDistinctIdLegacy               -> _add_distinct_id
- updatePerson (merge fields)       -> _update_person_for_merge
- moveDistinctIds (SYNC, no limit)  -> _move_distinct_ids
- updateCohortsAndFeatureFlagsForMerge -> _move_cohorts_and_ff
- deletePerson                      -> _delete_person

The tombstone/lifecycle-mark rollout adds constant per-transaction overhead
(claim + liveness checks + release) but does not change how the cost scales
with the number of moved mappings, so the baseline omits it.

Retry behavior mirrors handleMergeTransaction: refetch persons and retry on
the concurrency errors production classifies as retryable.
"""

import json
import time
import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import errors as pgerrors
from psycopg.types.json import Json

from .base import Emission, MergeOutcome, ResolvedPerson

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"

_PERSON_COLUMNS = "id, uuid, created_at, team_id, properties, is_identified, version"

_FETCH_FOR_UPDATE = f"""
    SELECT {", ".join("posthog_person." + c for c in _PERSON_COLUMNS.split(", "))}
    FROM posthog_person
    JOIN posthog_persondistinctid ON (
        posthog_persondistinctid.person_id = posthog_person.id
        AND posthog_persondistinctid.team_id = posthog_person.team_id
    )
    WHERE
        posthog_person.team_id = %s
        AND posthog_persondistinctid.team_id = %s
        AND posthog_persondistinctid.distinct_id = %s
        AND posthog_persondistinctid.is_deleted = false
        AND posthog_person.is_deleted = false
    FOR UPDATE
"""

_MAX_RETRIES = 5


@dataclass(frozen=True, kw_only=True)
class _Person:
    id: int
    uuid: str
    created_at: Any
    team_id: int
    properties: dict[str, Any]
    is_identified: bool
    version: int


def _row_to_person(row: tuple) -> _Person:
    return _Person(
        id=row[0],
        uuid=str(row[1]),
        created_at=row[2],
        team_id=row[3],
        properties=row[4],
        is_identified=row[5],
        version=int(row[6] or 0),
    )


class CurrentStrategy:
    name = "current"
    supports_current_contract = True

    def schema_files(self) -> list[str]:
        return [str(_SCHEMA_DIR / "current.sql")]

    def identify(
        self,
        conn: psycopg.Connection,
        team_id: int,
        target_distinct_id: str,
        anon_distinct_id: str,
    ) -> MergeOutcome:
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self._identify_once(conn, team_id, target_distinct_id, anon_distinct_id, attempt)
            except (
                pgerrors.DeadlockDetected,  # 40P01 -> caller retry in prod
                pgerrors.ForeignKeyViolation,  # target deleted / source gained ids
                pgerrors.UniqueViolation,  # concurrent create of same mapping
                _RetryableMergeError,
            ) as e:
                conn.rollback()
                last_error = e
                time.sleep(0.001 * (2**attempt))
        raise RuntimeError(f"merge failed after {_MAX_RETRIES} retries") from last_error

    def _identify_once(
        self,
        conn: psycopg.Connection,
        team_id: int,
        target_distinct_id: str,
        anon_distinct_id: str,
        attempt: int,
    ) -> MergeOutcome:
        with conn.cursor() as cur:
            # Production fetches other-person first, then merge-into person,
            # each FOR UPDATE in its own statement (fetchForUpdate x2).
            cur.execute(_FETCH_FOR_UPDATE, (team_id, team_id, anon_distinct_id))
            other_row = cur.fetchone()
            cur.execute(_FETCH_FOR_UPDATE, (team_id, team_id, target_distinct_id))
            target_row = cur.fetchone()

            other = _row_to_person(other_row) if other_row else None
            target = _row_to_person(target_row) if target_row else None

            if other is None and target is None:
                outcome = self._create_person_with_both_ids(cur, team_id, target_distinct_id, anon_distinct_id)
            elif other is not None and target is not None:
                if other.id == target.id:
                    conn.commit()
                    return MergeOutcome(
                        scenario="noop", person_id=target.id, person_uuid=target.uuid, emissions=[], retries=attempt
                    )
                outcome = self._merge_people(cur, target, other)
            else:
                existing = other if other is not None else target
                assert existing is not None
                to_add = target_distinct_id if other is not None else anon_distinct_id
                outcome = self._add_distinct_id_to_existing(cur, existing, to_add)

        conn.commit()
        return MergeOutcome(
            scenario=outcome.scenario,
            person_id=outcome.person_id,
            person_uuid=outcome.person_uuid,
            emissions=outcome.emissions,
            retries=attempt,
        )

    # -- neither exists ------------------------------------------------------

    def _create_person_with_both_ids(
        self, cur: psycopg.Cursor, team_id: int, target_distinct_id: str, anon_distinct_id: str
    ) -> MergeOutcome:
        person_uuid = str(uuidlib.uuid4())
        # Legacy insertPerson CTE: person + both mappings in one statement.
        # target distinct id derives the person -> version 0, anon id -> version 1
        # (see the distinctIdVersion comment in person-merge-service.ts).
        cur.execute(
            """
            WITH inserted_person AS (
                INSERT INTO posthog_person (
                    created_at, properties, properties_last_updated_at, properties_last_operation,
                    team_id, is_user_id, is_identified, uuid, version, last_seen_at
                )
                VALUES (now(), %s, '{}'::jsonb, '{}'::jsonb, %s, NULL, true, %s, 0, date_trunc('hour', now()))
                RETURNING id, uuid, version
            ),
            inserted_distinct_ids AS (
                INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                SELECT d.distinct_id, ip.id, %s, d.version
                FROM inserted_person ip
                CROSS JOIN unnest(%s::text[], %s::bigint[]) AS d(distinct_id, version)
                RETURNING id, distinct_id, version
            )
            SELECT ip.id, ip.uuid, ip.version,
                   (SELECT jsonb_agg(jsonb_build_object('distinct_id', d.distinct_id, 'version', d.version))
                    FROM inserted_distinct_ids d)
            FROM inserted_person ip
            """,
            (
                Json({}),
                team_id,
                person_uuid,
                team_id,
                [target_distinct_id, anon_distinct_id],
                [0, 1],
            ),
        )
        person_id, p_uuid, version, did_rows = cur.fetchone()
        emissions = [
            Emission(topic="person", contract="current", payload={"uuid": str(p_uuid), "version": version})
        ] + [
            Emission(
                topic="person_distinct_id",
                contract="current",
                payload={"distinct_id": d["distinct_id"], "person_id": str(p_uuid), "version": d["version"]},
            )
            for d in did_rows
        ]
        return MergeOutcome(scenario="neither", person_id=person_id, person_uuid=str(p_uuid), emissions=emissions)

    # -- one exists ----------------------------------------------------------

    def _add_distinct_id_to_existing(self, cur: psycopg.Cursor, person: _Person, distinct_id: str) -> MergeOutcome:
        # addDistinctIdLegacy; merge-added mappings get version 1.
        cur.execute(
            """
            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
            VALUES (%s, %s, %s, %s) RETURNING version
            """,
            (distinct_id, person.id, person.team_id, 1),
        )
        version = cur.fetchone()[0]
        # Production also flips is_identified via the person-update step that
        # follows the merge; modeled here as part of the scenario.
        cur.execute(
            "UPDATE posthog_person SET is_identified = true, version = COALESCE(version, 0)::numeric + 1"
            " WHERE id = %s AND team_id = %s AND is_deleted = false RETURNING version",
            (person.id, person.team_id),
        )
        person_version = cur.fetchone()[0]
        emissions = [
            Emission(topic="person", contract="current", payload={"uuid": person.uuid, "version": person_version}),
            Emission(
                topic="person_distinct_id",
                contract="current",
                payload={"distinct_id": distinct_id, "person_id": person.uuid, "version": version},
            ),
        ]
        return MergeOutcome(scenario="one", person_id=person.id, person_uuid=person.uuid, emissions=emissions)

    # -- both exist ----------------------------------------------------------

    def _merge_people(self, cur: psycopg.Cursor, target: _Person, source: _Person) -> MergeOutcome:
        merged_properties = {**source.properties, **target.properties}
        emissions: list[Emission] = []

        # updatePersonForMerge
        cur.execute(
            """
            UPDATE posthog_person
            SET version = %s, created_at = %s, properties = %s, is_identified = true
            WHERE id = %s AND team_id = %s AND is_deleted = false
            RETURNING version
            """,
            (
                max(target.version, source.version) + 1,
                min(target.created_at, source.created_at),
                Json(merged_properties),
                target.id,
                target.team_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise _RetryableMergeError("target person vanished before update")
        emissions.append(Emission(topic="person", contract="current", payload={"uuid": target.uuid, "version": row[0]}))

        # moveDistinctIds, SYNC mode without limit
        cur.execute(
            """
            UPDATE posthog_persondistinctid
            SET person_id = %s, version = COALESCE(version, 0)::numeric + 1
            WHERE person_id = %s AND team_id = %s AND is_deleted = false
            RETURNING distinct_id, version
            """,
            (target.id, source.id, target.team_id),
        )
        moved = cur.fetchall()
        if not moved:
            raise _RetryableMergeError("source person no longer exists")
        emissions.extend(
            Emission(
                topic="person_distinct_id",
                contract="current",
                payload={"distinct_id": distinct_id, "person_id": target.uuid, "version": int(version)},
            )
            for distinct_id, version in moved
        )

        # updateCohortsAndFeatureFlagsForMerge — single round-trip CTE
        cur.execute(
            """
            WITH cohort_update AS (
                UPDATE posthog_cohortpeople
                SET person_id = %s
                WHERE person_id = %s
                RETURNING person_id
            ),
            deletions AS (
                DELETE FROM posthog_featureflaghashkeyoverride
                WHERE team_id = %s AND person_id = %s
                RETURNING team_id, person_id, feature_flag_key, hash_key
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, %s, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING
            """,
            (target.id, source.id, target.team_id, source.id, target.id),
        )

        # deletePerson — the FK violation here is the concurrency signal prod relies on
        cur.execute(
            "DELETE FROM posthog_person WHERE team_id = %s AND id = %s RETURNING version",
            (source.team_id, source.id),
        )
        del_row = cur.fetchone()
        if del_row is not None:
            emissions.append(
                Emission(
                    topic="person",
                    contract="current",
                    payload={"uuid": source.uuid, "version": int(del_row[0] or 0) + 100, "is_deleted": 1},
                )
            )

        return MergeOutcome(scenario="both", person_id=target.id, person_uuid=target.uuid, emissions=emissions)

    # -- read path -----------------------------------------------------------

    def resolve(self, conn: psycopg.Connection, team_id: int, distinct_id: str) -> ResolvedPerson | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT posthog_person.id, posthog_person.uuid, posthog_person.properties,
                       posthog_person.is_identified, posthog_person.version
                FROM posthog_person
                JOIN posthog_persondistinctid ON (
                    posthog_persondistinctid.person_id = posthog_person.id
                    AND posthog_persondistinctid.team_id = posthog_person.team_id
                )
                WHERE posthog_person.team_id = %s
                  AND posthog_persondistinctid.team_id = %s
                  AND posthog_persondistinctid.distinct_id = %s
                  AND posthog_persondistinctid.is_deleted = false
                  AND posthog_person.is_deleted = false
                """,
                (team_id, team_id, distinct_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ResolvedPerson(
            person_id=row[0],
            person_uuid=str(row[1]),
            properties=row[2] if isinstance(row[2], dict) else json.loads(row[2]),
            is_identified=row[3],
            version=int(row[4] or 0),
        )


class _RetryableMergeError(Exception):
    """Concurrency outcomes production maps to refetch-and-retry."""
