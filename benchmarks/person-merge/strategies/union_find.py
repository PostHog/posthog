"""Union-find candidate: merges re-parent the source person instead of
moving its distinct id mappings.

Storage: `posthog_person.merged_into_id` (NULL = root). A merge of two
existing persons writes exactly two person rows — the target (merged
properties, version bump) and the source (pointer to target) — regardless
of how many distinct ids the source owns. Mapping rows are never touched.

Reads resolve pointer chains to the root. Chains only form when an already
merged-into person is itself merged away, so depth stays small in practice;
a background compaction (re-point chain members directly at the root, or
lazily re-home mapping rows) is the production companion piece, out of
scope here.

Emission modes (the price of the ClickHouse contract, measured):
- union_find:        one person-level override message, contract="new" —
                     requires the CH side to re-point by person, not by
                     distinct id.
- union_find_compat: reads the union's mappings and emits one
                     current-contract message per mapping. Versions are
                     derived as mapping.version + new root version; the
                     root's version strictly grows on every merge, so each
                     re-emission for a distinct id outranks the previous
                     one without ever writing the mapping row.
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

_MAX_RETRIES = 5

_FETCH_BY_ID = """
    SELECT id, uuid, created_at, team_id, properties, is_identified, version, merged_into_id
    FROM posthog_person
    WHERE team_id = %s AND id = %s AND is_deleted = false
"""


@dataclass(frozen=True, kw_only=True)
class _Person:
    id: int
    uuid: str
    created_at: Any
    team_id: int
    properties: dict[str, Any]
    is_identified: bool
    version: int
    merged_into_id: int | None


def _row_to_person(row: tuple) -> _Person:
    return _Person(
        id=row[0],
        uuid=str(row[1]),
        created_at=row[2],
        team_id=row[3],
        properties=row[4],
        is_identified=row[5],
        version=int(row[6] or 0),
        merged_into_id=row[7],
    )


class UnionFindStrategy:
    name = "union_find"
    supports_current_contract = False
    # When set, merges also re-point the source's direct children at the new
    # root, keeping every pointer chain at depth <= 1.
    compress = False

    def schema_files(self) -> list[str]:
        return [str(_SCHEMA_DIR / "current.sql"), str(_SCHEMA_DIR / "union_find.sql")]

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
                pgerrors.DeadlockDetected,
                pgerrors.ForeignKeyViolation,
                pgerrors.UniqueViolation,
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
            other = self._fetch_root_for_update(cur, team_id, anon_distinct_id)
            target = self._fetch_root_for_update(cur, team_id, target_distinct_id)

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

    # -- locking chain walk --------------------------------------------------

    _FIND_ROOT_ID = """
        WITH RECURSIVE walk AS (
            SELECT p.id, p.merged_into_id
            FROM posthog_person p
            JOIN posthog_persondistinctid d ON d.person_id = p.id AND d.team_id = p.team_id
            WHERE p.team_id = %s AND d.team_id = %s AND d.distinct_id = %s
              AND d.is_deleted = false AND p.is_deleted = false
            UNION ALL
            SELECT p2.id, p2.merged_into_id
            FROM posthog_person p2
            JOIN walk w ON p2.id = w.merged_into_id
            WHERE p2.team_id = %s AND p2.is_deleted = false
        )
        SELECT id FROM walk WHERE merged_into_id IS NULL
    """

    def _fetch_root_for_update(self, cur: psycopg.Cursor, team_id: int, distinct_id: str) -> _Person | None:
        """Resolve distinct id -> root person, locking the root.

        The chain walk happens server-side (one recursive query, no lock), then
        only the root is locked. If the root gained a pointer while we waited
        on the lock, follow it — that re-chase is rare and short.
        """
        cur.execute(self._FIND_ROOT_ID, (team_id, team_id, distinct_id, team_id))
        row = cur.fetchone()
        if row is None:
            return None
        root_id = row[0]
        for _ in range(16):
            cur.execute(_FETCH_BY_ID + " FOR UPDATE", (team_id, root_id))
            prow = cur.fetchone()
            if prow is None:
                raise _RetryableMergeError("pointer chain hit a missing person")
            person = _row_to_person(prow)
            if person.merged_into_id is None:
                return person
            root_id = person.merged_into_id
        raise _RetryableMergeError("root kept moving while locking")

    # -- neither / one: identical shape to the baseline ----------------------

    def _create_person_with_both_ids(
        self, cur: psycopg.Cursor, team_id: int, target_distinct_id: str, anon_distinct_id: str
    ) -> MergeOutcome:
        person_uuid = str(uuidlib.uuid4())
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
            (Json({}), team_id, person_uuid, team_id, [target_distinct_id, anon_distinct_id], [0, 1]),
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

    def _add_distinct_id_to_existing(self, cur: psycopg.Cursor, person: _Person, distinct_id: str) -> MergeOutcome:
        cur.execute(
            """
            INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
            VALUES (%s, %s, %s, %s) RETURNING version
            """,
            (distinct_id, person.id, person.team_id, 1),
        )
        version = cur.fetchone()[0]
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

    # -- both exist: the O(1)-write merge ------------------------------------

    def _merge_people(self, cur: psycopg.Cursor, target: _Person, source: _Person) -> MergeOutcome:
        merged_properties = {**source.properties, **target.properties}
        new_version = max(target.version, source.version) + 1
        emissions: list[Emission] = []

        cur.execute(
            """
            UPDATE posthog_person
            SET version = %s, created_at = %s, properties = %s, is_identified = true
            WHERE id = %s AND team_id = %s AND is_deleted = false
            RETURNING version
            """,
            (
                new_version,
                min(target.created_at, source.created_at),
                Json(merged_properties),
                target.id,
                target.team_id,
            ),
        )
        if cur.fetchone() is None:
            raise _RetryableMergeError("target person vanished before update")
        emissions.append(
            Emission(topic="person", contract="current", payload={"uuid": target.uuid, "version": new_version})
        )

        cur.execute(
            """
            UPDATE posthog_person
            SET merged_into_id = %s, version = COALESCE(version, 0)::numeric + 1
            WHERE id = %s AND team_id = %s AND is_deleted = false AND merged_into_id IS NULL
            RETURNING version
            """,
            (target.id, source.id, source.team_id),
        )
        src_row = cur.fetchone()
        if src_row is None:
            raise _RetryableMergeError("source person merged or deleted concurrently")

        if self.compress:
            # Path compression: re-point the source's direct children at the new
            # root. With every merge doing this, pointers never exceed depth 1 —
            # cost is O(persons previously merged into the source), not O(ids).
            cur.execute(
                """
                UPDATE posthog_person
                SET merged_into_id = %s
                WHERE team_id = %s AND merged_into_id = %s
                """,
                (target.id, source.team_id, source.id),
            )

        # Union members: the source and everything already merged into it.
        cur.execute(
            """
            WITH RECURSIVE members AS (
                SELECT id FROM posthog_person WHERE team_id = %s AND id = %s
                UNION ALL
                SELECT p.id FROM posthog_person p
                JOIN members m ON p.merged_into_id = m.id
                WHERE p.team_id = %s
            )
            SELECT id FROM members
            """,
            (source.team_id, source.id, source.team_id),
        )
        member_ids = [r[0] for r in cur.fetchall()]

        # Cohort/FF rows still re-home (proportional to cohort membership, not
        # distinct id count).
        cur.execute(
            """
            WITH cohort_update AS (
                UPDATE posthog_cohortpeople
                SET person_id = %s
                WHERE person_id = ANY(%s::bigint[])
                RETURNING person_id
            ),
            deletions AS (
                DELETE FROM posthog_featureflaghashkeyoverride
                WHERE team_id = %s AND person_id = ANY(%s::bigint[])
                RETURNING team_id, person_id, feature_flag_key, hash_key
            )
            INSERT INTO posthog_featureflaghashkeyoverride (team_id, person_id, feature_flag_key, hash_key)
                SELECT team_id, %s, feature_flag_key, hash_key
                FROM deletions
                ON CONFLICT DO NOTHING
            """,
            (target.id, member_ids, target.team_id, member_ids, target.id),
        )

        emissions.extend(self._merge_emissions(cur, target, source, member_ids, new_version))
        return MergeOutcome(scenario="both", person_id=target.id, person_uuid=target.uuid, emissions=emissions)

    def _merge_emissions(
        self,
        cur: psycopg.Cursor,
        target: _Person,
        source: _Person,
        member_ids: list[int],
        new_version: int,
    ) -> list[Emission]:
        """New contract: one person-level override; CH re-points every event and
        mapping owned by the source person in one hop."""
        return [
            Emission(
                topic="person_override",
                contract="new",
                payload={"old_person_id": source.uuid, "override_person_id": target.uuid, "version": new_version},
            ),
            Emission(
                topic="person",
                contract="current",
                payload={"uuid": source.uuid, "version": source.version + 100, "is_deleted": 1},
            ),
        ]

    # -- read path -----------------------------------------------------------

    def resolve(self, conn: psycopg.Connection, team_id: int, distinct_id: str) -> ResolvedPerson | None:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE chain AS (
                    SELECT posthog_person.id, posthog_person.uuid, posthog_person.properties,
                           posthog_person.is_identified, posthog_person.version,
                           posthog_person.merged_into_id, posthog_person.team_id
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
                    UNION ALL
                    SELECT p.id, p.uuid, p.properties, p.is_identified, p.version,
                           p.merged_into_id, p.team_id
                    FROM posthog_person p
                    JOIN chain c ON p.id = c.merged_into_id AND p.team_id = c.team_id
                    WHERE p.is_deleted = false
                )
                SELECT id, uuid, properties, is_identified, version
                FROM chain
                WHERE merged_into_id IS NULL
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

    # -- storage consistency (oracle hook) ------------------------------------

    def verify_storage(self, conn: psycopg.Connection, team_id: int) -> None:
        with conn.cursor() as cur:
            # No pointer targets a merged-away or missing person in a way that
            # breaks resolution: every chain terminates at a live root.
            cur.execute(
                """
                WITH RECURSIVE walk AS (
                    SELECT id AS start_id, merged_into_id AS next_id, 0 AS depth
                    FROM posthog_person
                    WHERE team_id = %s AND merged_into_id IS NOT NULL
                    UNION ALL
                    SELECT w.start_id, p.merged_into_id, w.depth + 1
                    FROM walk w
                    JOIN posthog_person p ON p.id = w.next_id
                    WHERE w.next_id IS NOT NULL AND w.depth < 100
                )
                SELECT count(*) FROM walk WHERE depth >= 100
                """,
                (team_id,),
            )
            deep = cur.fetchone()[0]
            if deep:
                raise AssertionError(f"{deep} pointer chains exceed depth 100 (cycle or runaway)")


class UnionFindCompatStrategy(UnionFindStrategy):
    """Union-find storage, but emits today's per-mapping override messages.

    Pays the contract floor — read N mappings, emit N messages — without any
    mapping writes. Version = mapping.version + new root version: the root's
    version strictly grows each merge, so re-emissions always outrank prior
    ones per distinct id.
    """

    name = "union_find_compat"
    supports_current_contract = True

    def _merge_emissions(
        self,
        cur: psycopg.Cursor,
        target: _Person,
        source: _Person,
        member_ids: list[int],
        new_version: int,
    ) -> list[Emission]:
        cur.execute(
            """
            SELECT distinct_id, COALESCE(version, 0) + %s
            FROM posthog_persondistinctid
            WHERE team_id = %s AND person_id = ANY(%s::bigint[]) AND is_deleted = false
            """,
            (new_version, source.team_id, member_ids),
        )
        rows = cur.fetchall()
        return [
            Emission(
                topic="person_distinct_id",
                contract="current",
                payload={"distinct_id": distinct_id, "person_id": target.uuid, "version": int(version)},
            )
            for distinct_id, version in rows
        ] + [
            Emission(
                topic="person",
                contract="current",
                payload={"uuid": source.uuid, "version": source.version + 100, "is_deleted": 1},
            ),
        ]


class UnionFindCompressedStrategy(UnionFindStrategy):
    """Union-find with eager path compression: chains never exceed depth 1,
    so reads pay at most one extra hop and the merge's root walk is bounded."""

    name = "union_find_compressed"
    compress = True


class _RetryableMergeError(Exception):
    """Concurrency outcomes mapped to refetch-and-retry."""
