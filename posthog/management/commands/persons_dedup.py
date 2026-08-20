"""Resolve duplicate (team_id, uuid) rows in posthog_person, one team at a time.

Production has no unique index on (team_id, uuid) even though
rust/persons_migrations/20251113000001 declares one, and person UUIDs are derived
deterministically from (team_id, primary distinct_id). Any actor that removes a
posthog_persondistinctid row while leaving its person behind therefore lets the next
event mint a second person row with an identical (team_id, uuid).

This command resolves those groups so the unique index can be built. It never creates,
drops or alters an index -- that is separate work, gated on `--mode verify` reporting
zero remaining groups.

SAFETY MODEL

Everything rests on one property, verified against the flag and cohort read paths:

    A person row owning no live posthog_persondistinctid row cannot be resolved FROM A
    DISTINCT ID, so nothing keyed to that person_id takes part in flag evaluation, cohort
    matching, or event attribution. Those reads all start from a distinct id
    (rust/common/types/src/person.rs:22 joins posthog_persondistinctid with
    is_deleted = false; flag_matching_utils.rs:845 and :288 build on it).

Say it that precisely, because the shorter version -- "the row is unreachable" -- is not
true. Plenty of paths reach a person by uuid or by bigint id without touching a distinct
id at all: the persons detail API accepts either, and personhog exposes GetPersonByUuid,
GetPersonsByUuids, GetPerson and GetPersons. What makes the delete safe is narrower: a
victim is always rn > 1 within a duplicate (team_id, uuid) group, so a row carrying the
same uuid always survives it. Every uuid-keyed lookup still finds a person; it just finds
the one the product can actually resolve.

Two consequences of that worth stating rather than discovering:

  - get_person_by_uuid takes the first row of an unordered result, so for a duplicated
    uuid it returns an arbitrary member today. Removing the victims makes it deterministic.
  - Static cohort population resolves uuid -> person id and does not deduplicate, so it
    writes membership rows against victims continuously, not historically. Expect the
    post-commit cohort sweep to find rows on an active team. That is the normal case here.

Two gates enforce it from opposite directions, because proving the victims are safe is
not the same as proving the survivor is right:

    GATE_REACHABLE_SQL           no row we delete may be reachable
    GATE_SURVIVOR_REACHABLE_SQL  if any row in the group is reachable, one we keep must be

DO NOT REORDER THE LOCK AND THE GATE. Ingestion's stranded-row claim path selects exactly
the rows this command deletes -- the unreachable holder of a (team_id, uuid) -- and
repoints it to a live distinct id. It takes FOR UPDATE on that row, and so does
LOCK_VICTIMS_SQL, which is the only reason the two serialize instead of racing. The gate
must stay after the lock. This stopped being hypothetical when
PERSON_CREATE_CLAIM_TEAM_ALLOWLIST was enabled: the teams on it are the teams with
duplicates, so a run against them will meet a claim in flight, and the batch-level prune
is what absorbs it.

So a row owning zero live distinct IDs can be deleted without changing any membership
or flag DECISION, and the feature-flag overrides that cascade away with it were already
unreachable. Moving them onto the surviving person would do the opposite: it would
resurrect dead data and could change which flag variant a live user receives.

One carve-out, because "no product behaviour" would overstate it. Static cohort size
comes from a bare COUNT(*) over posthog_cohortpeople scoped by cohort_id, with no join
to persons, so an unreachable row's memberships are counted today even though no read
path can act on them. Removing that row corrects the displayed count downward. That is
a fix rather than a regression -- the count gates the realtime-evaluation threshold, so
an inflated one can demote a cohort that should qualify -- but it is user-visible, and
it is the one number a dedup run can move.

The three dependent tables behave differently on DELETE in production, which is why
the reachability assertion runs before every delete and again inside the transaction:

    posthog_persondistinctid              FK NO ACTION -> Postgres blocks the delete
    posthog_featureflaghashkeyoverride    FK CASCADE   -> silently removes overrides
    posthog_cohortpeople                  no FK        -> silently orphans rows
    posthog_person_reconciliation_backup  no FK        -> silently orphans rows

Only the first fails loudly, so the command cannot rely on the database to catch a
mistake in the other three. The two without a foreign key are deleted explicitly, before
the person row, so a failure there aborts before anything is lost.

A note on what is NOT a reason to keep a row. Being referenced is not the same as being
live. A row owning no distinct ID is dead whatever else points at it, and refusing to
delete it does not protect anything -- it leaves the dead row in place along with cohort
memberships that still count toward the cohort size shown in the product. These repairs
are expensive to run, so every row skipped for a reason that does not survive scrutiny is
a re-run later. n_did = 0 is the safety condition; nothing else is.

BLAST RADIUS OF A DELETED bigint id

Audited across the repo rather than assumed. Two facts do most of the work.

Nothing reassigns the id. posthog_person.id comes from a sequence and there is no setval
anywhere, so a deleted id dangles forever and is never handed to a different person. Every
"wrong person" scenario needs id reuse, so the real failure mode is a dangling reference or
a silent no-op, not mistaken identity.

ClickHouse never stores it. Every person column in every ClickHouse table is UUID-typed --
person, person_distinct_id2, person_static_cohort, cohortpeople, events, the override
dictionary, all of it -- and every Kafka producer sends person.uuid, discarding the bigint.
So a dedup needs no ClickHouse tombstone, but only because the survivor keeps the uuid and
therefore keeps ClickHouse's row backed. GATE_NO_SURVIVOR_SQL is what holds that up: delete
the last row for a uuid and ClickHouse would be left visible-but-unbacked. Do not weaken it.

Outside the persons DB the bigint survives in a handful of places, none of which this
command can repair, and all of which fail safe:

    posthog_activitylog.item_id     a Person row's audit trail becomes unreachable; only
                                    the "deleted" entry carries the uuid to find it by
    Temporal delete-persons input   a queued run holding a victim id resolves nothing for
                                    it and under-deletes silently
    split_person Celery payload     raises, retries once, dies
    Dagster run config / event log  stale resume watermarks and failure metadata

Drain those queues before a large run rather than reasoning about them mid-flight.

Deleted rows and their dependent rows are written to a local JSONL file, fsync'd, after
the victims are locked and before the delete runs. Locking first matters: an insert into
posthog_featureflaghashkeyoverride takes FOR KEY SHARE on the parent person row, so
reading dependents before the lock would let a row appear afterwards, cascade away, and
never reach the backup. Writing before the delete means a rolled back transaction leaves
a harmless superset, and a deleted row can never be missing. Copy that file off the pod;
it is the only undo.

TOMBSTONES

A row with is_deleted = true is a tombstone, not a dead row: the write path revives it in
place so the revived key outranks its own ClickHouse tombstone, which needs the version
this row is holding. Deleting one would drop that version floor, so tombstoned rows are
never staged, and they lose the survivor ranking to any live member of their group. That
leaves a group of only tombstoned rows unresolved, which verify reports rather than hides.
No production team can be in that state yet -- every is_deleted writer is gated on a team
allowlist that is only enabled where the unique (team_id, uuid) index already exists.
"""

from __future__ import annotations

import os
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog

from posthog.persons_db import persons_db_connection, persons_db_url

logger = structlog.get_logger(__name__)

VICTIMS_TABLE = "pg_temp.persons_dedup_victims"

PERSON_COLUMNS = (
    "id",
    "created_at",
    "properties",
    "team_id",
    "is_user_id",
    "is_identified",
    "uuid",
    "properties_last_updated_at",
    "properties_last_operation",
    "version",
    "last_seen_at",
    "is_deleted",
)

# Reference counts per member row of a duplicate group.
# posthog_person_reconciliation_backup (the Dagster property-reconciliation pre-image
# table) is counted defensively: a row it references stops being deletable. The
# personhog lifecycle/shadow tables are deliberately NOT consulted -- personhog does not
# run in production, its tables are empty there, and their ACLs are owner-only, so a
# subquery against them fails with permission denied for the operator role.
_MEMBERS_CTE = """
WITH dups AS (
    SELECT team_id, uuid FROM posthog_person
    WHERE team_id = %(team)s
    GROUP BY team_id, uuid HAVING count(*) > 1
),
members AS (
    SELECT p.team_id, p.uuid, p.id, p.version, p.is_identified, p.created_at, p.is_deleted,
           -- Two counts, because two different questions. n_did is what the foreign key
           -- sees, so it decides whether a row can be deleted at all: the FK is NO ACTION
           -- and counts tombstoned mappings too, so staging a row with any mapping would
           -- fail the delete. n_did_live is what the product sees -- the flag path requires
           -- pdi.is_deleted = false -- so it decides which row is worth keeping.
           (SELECT count(*) FROM posthog_persondistinctid pdi
             WHERE pdi.team_id = p.team_id AND pdi.person_id = p.id) AS n_did,
           (SELECT count(*) FROM posthog_persondistinctid pdi
             WHERE pdi.team_id = p.team_id AND pdi.person_id = p.id
               AND NOT pdi.is_deleted) AS n_did_live,
           (SELECT count(*) FROM posthog_cohortpeople cp
             WHERE cp.person_id = p.id) AS n_cohort,
           (SELECT count(*) FROM posthog_featureflaghashkeyoverride ff
             WHERE ff.team_id = p.team_id AND ff.person_id = p.id) AS n_ff,
           (SELECT count(*) FROM posthog_person_reconciliation_backup rb
             WHERE rb.team_id = p.team_id AND rb.person_id = p.id) AS n_recon
    FROM posthog_person p
    JOIN dups d ON d.team_id = p.team_id AND d.uuid = p.uuid
    WHERE p.team_id = %(team)s
),
-- refs decides deletability for delete-unreferenced, not who survives: the ranking below
-- puts reachability ahead of it, so n_cohort and n_ff only ever break a tie between rows
-- that are all unreachable. They look load-bearing for survivor choice and are not.
scored AS (
    SELECT *, (n_did + n_cohort + n_ff + n_recon) AS refs FROM members
),
ranked AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY team_id, uuid
               ORDER BY is_deleted ASC, (n_did_live > 0) DESC, (n_did > 0) DESC, refs DESC,
                        is_identified DESC, version DESC NULLS LAST, created_at ASC, id ASC
           ) AS rn
    FROM scored
),
-- One row per duplicate group, in the terms the staging queries below use, so
-- classify and verify report exactly what repair will and will not resolve.
per_group AS (
    SELECT uuid,
           count(*) AS members,
           count(*) FILTER (WHERE n_did > 0) AS live_owners,
           count(*) FILTER (WHERE n_did_live > 0) AS reachable_owners,
           count(*) FILTER (WHERE is_deleted) AS tombstoned,
           count(*) FILTER (WHERE n_recon > 0) AS recon_held,
           sum(n_ff)::bigint AS flag_overrides,
           sum(n_cohort)::bigint AS cohort_rows,
           count(*) FILTER (WHERE rn > 1 AND n_did = 0 AND NOT is_deleted) AS stageable
    FROM ranked GROUP BY uuid
)
"""

CLASSIFY_SQL = (
    _MEMBERS_CTE
    + """
SELECT
    (SELECT count(*) FROM (SELECT uuid FROM ranked GROUP BY uuid) x),
    (SELECT count(*) FROM (SELECT uuid FROM ranked GROUP BY uuid
                            HAVING count(*) FILTER (WHERE refs > 0) = 0) x),
    (SELECT count(*) FROM (SELECT uuid FROM ranked GROUP BY uuid
                            HAVING count(*) FILTER (WHERE refs > 0) = 1) x),
    (SELECT count(*) FROM (SELECT uuid FROM ranked GROUP BY uuid
                            HAVING count(*) FILTER (WHERE refs > 0) > 1) x),
    (SELECT count(*) FROM (SELECT uuid FROM ranked GROUP BY uuid
                            HAVING count(*) FILTER (WHERE n_did > 0) > 1) x),
    (SELECT count(*) FROM per_group WHERE live_owners > 1 OR members - stageable > 1),
    (SELECT count(*) FROM ranked WHERE is_deleted),
    COALESCE(sum(n_did), 0), COALESCE(sum(n_cohort), 0), COALESCE(sum(n_ff), 0),
    COALESCE(sum(n_recon), 0)
FROM ranked
"""
)

# Delete-only: a non-survivor that nothing at all references.
STAGE_UNREFERENCED_SQL = (
    _MEMBERS_CTE
    + f"""
INSERT INTO {VICTIMS_TABLE} (team_id, id, uuid)
SELECT team_id, id, uuid FROM ranked WHERE rn > 1 AND refs = 0 AND NOT is_deleted
"""
)

# Repair: a non-survivor owning NO distinct IDs. Unreachable by definition, so its
# feature-flag overrides, cohort rows and reconciliation backup are dead data that go with
# it. n_did = 0 is the whole safety condition and it is doing more work than it looks:
# because it counts tombstoned mappings as well as live ones, no row a foreign key would
# refuse to delete can be staged, and no row the product can still resolve can be either.
#
# Two conditions used to sit here and have been removed, because each refused a delete we
# can prove is safe, and every skipped row is a re-run later:
#
#   n_recon = 0
#       A reconciliation backup row does not make a person live. Its restore path reads the
#       person by id and returns early when the row is gone
#       (person_property_reconciliation_restore.py:326), and the caller counts that as a
#       skip. So the delete is safe; the backup row goes with the person rather than being
#       left to warn on every future restore and retain a deleted person's properties.
#
#   uuid IN (groups with at most one distinct-ID owner)
#       This never protected a live row -- n_did = 0 already does that, with or without it.
#       Its only effect was to skip dead rows that happened to share a group with two live
#       ones, leaving known-orphaned rows behind and their cohort memberships still counted.
#       The group stays blocked for the merge either way; classify still reports it, because
#       that accounting keys on the count of live owners, not on this clause.
STAGE_UNREACHABLE_SQL = (
    _MEMBERS_CTE
    + f"""
INSERT INTO {VICTIMS_TABLE} (team_id, id, uuid)
SELECT team_id, id, uuid FROM ranked
WHERE rn > 1
  AND n_did = 0
  AND NOT is_deleted
"""
)

# Groups repair cannot resolve, counted the way the staging query above decides: a group
# with two live distinct-ID owners needs a real person merge, and a group that keeps more
# than one member after every stageable victim is removed is held by something else
# (reconciliation backup, or a tombstone this command deliberately will not touch).
# verify uses this to tell "dedup is incomplete" from "this is the remainder we accept".
COUNT_BLOCKED_SQL = (
    _MEMBERS_CTE
    + """
SELECT count(*), count(*) FILTER (WHERE live_owners > 1 OR members - stageable > 1)
FROM per_group
"""
)

# Everything needed to resolve a group this command refuses, without re-deriving it: which
# rows are in the group, which of them the product can still reach, what hangs off them, and
# why it was refused. The merge work needs the reachable pair and the override count; the
# reconciliation and tombstone cases need to be told apart from it.
BLOCKED_DETAIL_SQL = (
    _MEMBERS_CTE
    + """
SELECT g.uuid,
       -- Mirrors the WHERE below, branch for branch, so the reason names the condition that
       -- actually refused the group. Two rows owning distinct IDs is the merge case, split by
       -- whether the product can still reach both; a tombstone is the other. A reconciliation
       -- backup row no longer refuses anything, so it is a reported column, not a reason --
       -- ranking it here attributed tombstone-blocked groups to the backup. 'other' should be
       -- unreachable: the survivor ranking puts any row owning a distinct ID first, so a group
       -- with one live owner and no tombstone always resolves down to a single member.
       CASE WHEN g.reachable_owners > 1 THEN 'multiple_reachable_rows'
            WHEN g.live_owners > 1      THEN 'multiple_distinct_id_owners'
            WHEN g.tombstoned > 0       THEN 'tombstoned_member'
            ELSE 'other' END AS reason,
       g.members, g.reachable_owners, g.live_owners, g.tombstoned, g.recon_held,
       g.flag_overrides, g.cohort_rows,
       (SELECT array_agg(r.id ORDER BY r.rn) FROM ranked r WHERE r.uuid = g.uuid) AS member_ids,
       (SELECT array_agg(r.id ORDER BY r.rn) FROM ranked r
         WHERE r.uuid = g.uuid AND r.n_did_live > 0) AS reachable_ids
FROM per_group g
WHERE g.live_owners > 1 OR g.members - g.stageable > 1
ORDER BY g.uuid
"""
)

TAKE_BATCH_SQL = f"""
INSERT INTO {VICTIMS_TABLE}_batch (team_id, id, uuid)
SELECT team_id, id, uuid FROM {VICTIMS_TABLE} ORDER BY uuid, id LIMIT %(batch)s
"""

RETIRE_BATCH_SQL = f"""
DELETE FROM {VICTIMS_TABLE} v USING {VICTIMS_TABLE}_batch b
WHERE v.team_id = b.team_id AND v.id = b.id
"""

# Drop from the staged set the batch members a concurrent writer made undeletable. Aborting
# the whole run instead would discard a staging scan that costs minutes on the large teams,
# and on a team still receiving writes it can stop the run finishing at all. Only the staged
# set is touched -- no person row is modified. Three ways a victim stops being one:
#   1. it no longer exists, because something else removed it;
#   2. it gained a reference since staging, so it is now reachable;
#   3. its group lost the survivor, so the staged victims are all that remains of the key.
#      Deleting them would remove it entirely, and it is no longer a duplicate anyway.
# Case 3 must be here as well as in the gate: without it, a concurrent delete of an unstaged
# survivor fails GATE_NO_SURVIVOR_SQL, matches none of the other predicates, and aborts the
# team over a batch that is merely no longer worth deleting.
PRUNE_BATCH_SQL = f"""
DELETE FROM {VICTIMS_TABLE} v
USING {VICTIMS_TABLE}_batch b
WHERE v.team_id = b.team_id AND v.id = b.id
  AND (
      NOT EXISTS (SELECT 1 FROM posthog_person p
                   WHERE p.team_id = v.team_id AND p.id = v.id)
   OR EXISTS (SELECT 1 FROM posthog_persondistinctid pdi
               WHERE pdi.team_id = v.team_id AND pdi.person_id = v.id)
   OR (SELECT count(*) FROM posthog_person p
        WHERE p.team_id = v.team_id AND p.uuid = v.uuid)
      <= (SELECT count(*) FROM {VICTIMS_TABLE}_batch b2
           WHERE b2.team_id = v.team_id AND b2.uuid = v.uuid)
  )
"""

# The load-bearing assertion. A victim owning a distinct ID is reachable, so deleting it
# would change product behaviour and silently destroy its overrides via the cascade.
GATE_REACHABLE_SQL = f"""
SELECT count(*) FROM {VICTIMS_TABLE}_batch v
WHERE EXISTS (SELECT 1 FROM posthog_persondistinctid pdi
               WHERE pdi.team_id = v.team_id AND pdi.person_id = v.id)
"""

# The mirror of the reachable gate. That one proves no victim is reachable; this proves the
# row we keep is the right one. Staging should already guarantee it -- a victim needs n_did = 0
# -- so this is an assertion, and a non-zero result means the model is wrong rather than that a
# writer raced us. Scoped to the batch's keys, so it costs a handful of index probes rather
# than another pass over the team.
GATE_SURVIVOR_REACHABLE_SQL = f"""
SELECT count(*) FROM (SELECT DISTINCT team_id, uuid FROM {VICTIMS_TABLE}_batch) g
WHERE EXISTS (
        SELECT 1 FROM posthog_person p
        WHERE p.team_id = g.team_id AND p.uuid = g.uuid
          AND EXISTS (SELECT 1 FROM posthog_persondistinctid d
                       WHERE d.team_id = p.team_id AND d.person_id = p.id AND NOT d.is_deleted)
      )
  AND NOT EXISTS (
        SELECT 1 FROM posthog_person p
        WHERE p.team_id = g.team_id AND p.uuid = g.uuid
          AND NOT EXISTS (SELECT 1 FROM {VICTIMS_TABLE}_batch b
                           WHERE b.team_id = p.team_id AND b.id = p.id)
          AND EXISTS (SELECT 1 FROM posthog_persondistinctid d
                       WHERE d.team_id = p.team_id AND d.person_id = p.id AND NOT d.is_deleted)
      )
"""

GATE_NO_SURVIVOR_SQL = f"""
SELECT count(*) FROM (
    SELECT v.team_id, v.uuid, count(*) AS victims,
           (SELECT count(*) FROM posthog_person p
             WHERE p.team_id = v.team_id AND p.uuid = v.uuid) AS members
    FROM {VICTIMS_TABLE}_batch v GROUP BY v.team_id, v.uuid
) g WHERE victims >= members
"""

LOCK_VICTIMS_SQL = f"""
SELECT p.id FROM posthog_person p
JOIN {VICTIMS_TABLE}_batch v ON v.team_id = p.team_id AND v.id = p.id
WHERE p.team_id = %(team)s
FOR UPDATE
"""

FETCH_PERSONS_SQL = f"""
SELECT {", ".join("p." + c for c in PERSON_COLUMNS)}
FROM posthog_person p
JOIN {VICTIMS_TABLE}_batch v ON v.team_id = p.team_id AND v.id = p.id
WHERE p.team_id = %(team)s ORDER BY p.uuid, p.id
"""

# Dependent rows the delete will remove. Captured so the backup covers everything lost,
# not just the person row.
FETCH_DEPENDENTS_SQL = f"""
SELECT 'featureflaghashkeyoverride' AS tbl, ff.id, ff.person_id,
       ff.feature_flag_key AS k, ff.hash_key AS v
FROM posthog_featureflaghashkeyoverride ff
JOIN {VICTIMS_TABLE}_batch b ON b.team_id = ff.team_id AND b.id = ff.person_id
UNION ALL
SELECT 'cohortpeople', cp.id, cp.person_id, cp.cohort_id::text, NULL
FROM posthog_cohortpeople cp
JOIN {VICTIMS_TABLE}_batch b ON b.id = cp.person_id
UNION ALL
SELECT 'reconciliation_backup', NULL, rb.person_id, rb.job_id::text, rb.properties::text
FROM posthog_person_reconciliation_backup rb
JOIN {VICTIMS_TABLE}_batch b ON b.team_id = rb.team_id AND b.id = rb.person_id
"""

# Cohort rows have no FK, so the cascade will not remove them. Delete explicitly, before
# the person row, so a failure here aborts before anything is lost.
DELETE_COHORT_SQL = f"""
DELETE FROM posthog_cohortpeople cp
USING {VICTIMS_TABLE}_batch b WHERE cp.person_id = b.id
"""

# Same shape, same reason: no FK, so nothing removes these for us. Left behind they would
# warn on every future restore run and keep a deleted person's properties indefinitely.
# The restore path already treats a missing person as a skip, so removing both together is
# the outcome it would reach anyway.
DELETE_RECON_BACKUP_SQL = f"""
DELETE FROM posthog_person_reconciliation_backup rb
USING {VICTIMS_TABLE}_batch b
WHERE rb.team_id = b.team_id AND rb.person_id = b.id
"""

# posthog_cohortpeople has no FK to posthog_person, so nothing at the database level
# stops a row appearing for a victim while the delete transaction is open.
CHECK_COHORT_ORPHANS_SQL = f"""
SELECT count(*) FROM posthog_cohortpeople cp
JOIN {VICTIMS_TABLE}_batch b ON cp.person_id = b.id
"""

# Post-commit sweep. posthog_cohortpeople has no FK, so a cohort insert takes no lock
# on the person row and can commit between the in-transaction check's snapshot and our
# commit. This runs after commit with a fresh snapshot, so it sees any row that raced
# us; scoped to the batch's victims, whose persons are now provably gone.
SWEEP_COHORT_ORPHANS_SQL = f"""
DELETE FROM posthog_cohortpeople cp
USING {VICTIMS_TABLE}_batch b
WHERE cp.person_id = b.id
RETURNING cp.id, cp.cohort_id, cp.person_id
"""

DELETE_PERSONS_SQL = f"""
DELETE FROM posthog_person p
USING {VICTIMS_TABLE}_batch b
WHERE p.team_id = b.team_id AND p.id = b.id AND p.team_id = %(team)s
"""

VERIFY_ORPHANS_SQL = """
SELECT count(*) FROM posthog_persondistinctid pdi
WHERE pdi.team_id = %(team)s
  AND NOT EXISTS (SELECT 1 FROM posthog_person p
                   WHERE p.team_id = pdi.team_id AND p.id = pdi.person_id)
"""


# Every (table, privilege) pair the command exercises. Probed up front so a missing
# grant aborts cleanly before any work, instead of surfacing as a raw permission
# error mid-CTE (lifecycle_op_person in production is owner-only, which is exactly
# how such a gap presents).
REQUIRED_PRIVILEGES = (
    ("posthog_person", "SELECT"),
    ("posthog_person", "DELETE"),
    ("posthog_persondistinctid", "SELECT"),
    ("posthog_featureflaghashkeyoverride", "SELECT"),
    ("posthog_cohortpeople", "SELECT"),
    ("posthog_cohortpeople", "DELETE"),
    ("posthog_person_reconciliation_backup", "SELECT"),
    ("posthog_person_reconciliation_backup", "DELETE"),
)
# posthog_featureflaghashkeyoverride needs only SELECT: its rows go via the FK's
# ON DELETE CASCADE, and Postgres runs referential actions with the privileges of the
# referencing table's owner rather than the caller's, so no DELETE grant is required.


def _check_privileges(conn: psycopg.Connection) -> list[str]:
    missing = []
    with conn.cursor() as cur:
        for table, privilege in REQUIRED_PRIVILEGES:
            cur.execute("SELECT has_table_privilege(%s, %s)", (table, privilege))
            row = cur.fetchone()
            if not (row and row[0]):
                missing.append(f"{privilege} on {table}")
    return missing


def _scalar(conn: psycopg.Connection, sql: str, params: dict | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _check_session_stability(conn: psycopg.Connection) -> None:
    """Abort if the connection does not behave like one stable backend session.

    The US census run proved this failure mode is real: queries were canceled at the
    server's 30-minute statement_timeout even though the session had SET it to 0,
    which is the signature of a pooler (pgbouncer transaction mode, proxy multiplexing)
    routing consecutive statements to different backends. On such a connection this
    command is unusable -- its temp tables and session settings silently vanish between
    statements. Detect it up front instead of failing intermittently mid-run.
    """
    pids = set()
    for _ in range(3):
        pids.add(_scalar(conn, "SELECT pg_backend_pid()"))
    with conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE persons_dedup_canary (n int)")
        cur.execute("INSERT INTO persons_dedup_canary VALUES (1)")
    canary = _scalar(conn, "SELECT count(*) FROM persons_dedup_canary")
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS persons_dedup_canary")
    if len(pids) != 1 or canary != 1:
        raise CommandError(
            "connection is not session-stable (pooled/multiplexed): "
            f"saw backend pids {sorted(pids)}, temp-table canary={canary}. "
            "Temp tables and session settings will not survive between statements. "
            "Use a direct writer endpoint, not a transaction-pooled one."
        )


class Command(BaseCommand):
    help = "Resolve duplicate (team_id, uuid) rows in posthog_person. Dry run unless --apply."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--mode", required=True, choices=["classify", "delete-unreferenced", "repair", "verify"])
        parser.add_argument("--team", type=int, required=True)
        parser.add_argument("--apply", action="store_true", help="actually delete; omit for a dry run")
        parser.add_argument(
            "--writer",
            action="store_true",
            help="read from the primary instead of the reader replica (classify/verify only)",
        )
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--outdir", default="persons_dedup_backups")
        parser.add_argument(
            "--sleep-ms",
            type=int,
            default=200,
            help="pause between batches so writers blocked on our row locks drain (0 disables)",
        )

    def _assert_explicit_target(self, use_writer: bool) -> None:
        """Refuse to run against a silently defaulted database, and log the one chosen.

        posthog.persons_db falls back to a localhost URL built from PG* when the persons
        URL is unset. That default is right for a developer and wrong for this command: in
        a deployed pod PG* usually point at the main cluster, so an unset variable turns a
        destructive run against the persons database into a destructive run against
        whatever `posthog_persons` resolves to there -- or a confusing connection error.
        The variable is injected by the charts in every deployment, so requiring it costs
        nothing operationally and removes the failure mode entirely. Tests set it in
        conftest; a developer without it gets told which variable to set.
        """
        var = "PERSONS_DB_WRITER_URL" if use_writer else "PERSONS_DB_READER_URL"
        if not os.getenv("PERSONS_DB_WRITER_URL") and not os.getenv("PERSONS_DB_READER_URL"):
            raise CommandError(
                f"{var} is not set, so the persons-DB URL would fall back to a localhost "
                "default built from PG*. Refusing to run: on a deployed pod that default "
                "points somewhere else entirely. Set the variable explicitly."
            )
        # Say out loud which database is about to be modified. The operator is driving this
        # by hand against production, and host plus dbname is what tells them the toolbox
        # is pointed at persons rather than the main cluster.
        parts = urlsplit(persons_db_url(writer=use_writer))
        logger.info(
            "persons_dedup.target",
            host=parts.hostname,
            port=parts.port,
            dbname=(parts.path or "/").lstrip("/"),
            role="writer" if use_writer else "reader",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team: int = options["team"]
        mode: str = options["mode"]
        apply_changes: bool = options["apply"]

        if mode in ("classify", "verify") and apply_changes:
            raise CommandError(f"--apply is meaningless for --mode {mode}")

        if mode not in ("classify", "verify") and options["writer"]:
            raise CommandError(f"--writer is meaningless for --mode {mode}; it always uses the writer")

        # LIMIT 0 stages nothing and the loop exits reporting success, which reads as
        # "nothing to do" on a team that still has duplicates. A negative value reaches
        # Postgres as a raw syntax error.
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")

        # classify and verify are pure reads whose scans can run for minutes on large
        # teams, so they default to the reader replica to keep that load off the
        # primary. Replica staleness is bounded to replay lag (logged below) and is not
        # load-bearing: a duplicate minted after the read escapes a primary read too,
        # and the unique index build is the authoritative duplicate check either way.
        use_writer = mode not in ("classify", "verify") or options["writer"]
        self._assert_explicit_target(use_writer)

        with persons_db_connection(writer=use_writer, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = 0")

            missing = _check_privileges(conn)
            if missing:
                raise CommandError(
                    "operator role lacks required grants: " + ", ".join(missing) + ". "
                    "Ask for the grants before running; nothing was changed."
                )

            if mode in ("classify", "verify"):
                # A verify run seconds after a repair can see the pre-repair state on a
                # lagging replica; surfacing the lag lets the operator tell a stale read
                # from a real failure (or rerun with --writer).
                if not use_writer and _scalar(conn, "SELECT CASE WHEN pg_is_in_recovery() THEN 1 ELSE 0 END"):
                    lag_seconds = _scalar(
                        conn,
                        "SELECT COALESCE(EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp()), 0)::bigint",
                    )
                    logger.info("persons_dedup.reading_from_replica", team_id=team, replay_lag_seconds=lag_seconds)
                if mode == "classify":
                    self._classify(conn, team, Path(options["outdir"]))
                else:
                    self._verify(conn, team)
                return

            if _scalar(conn, "SELECT CASE WHEN pg_is_in_recovery() THEN 1 ELSE 0 END"):
                raise CommandError("connected to a replica; this mode needs the writer")

            _check_session_stability(conn)

            stage_sql = STAGE_UNREFERENCED_SQL if mode == "delete-unreferenced" else STAGE_UNREACHABLE_SQL
            self._run(conn, team, stage_sql, options, apply_changes=apply_changes, mode=mode)

    BLOCKED_COLUMNS = (
        "uuid",
        "reason",
        "members",
        "reachable_owners",
        "live_owners",
        "tombstoned",
        "recon_held",
        "flag_overrides",
        "cohort_rows",
        "member_ids",
        "reachable_ids",
    )

    def _dump_blocked(self, conn: psycopg.Connection, team: int, outdir: Path) -> dict[str, int]:
        """Write one record per group this command refuses, and return the reason tally.

        The counts alone cannot be acted on: resolving a group needs to know which rows it
        holds, which of them are still reachable, and what hangs off them. Written next to
        the delete backups so a run leaves everything the follow-up work needs.
        """
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute(BLOCKED_DETAIL_SQL, {"team": team})
            rows = cur.fetchall()
            cur.execute("COMMIT")
        if not rows:
            return {}

        outdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = outdir / f"blocked_team_{team}_{stamp}.jsonl"
        tally: dict[str, int] = {}
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            for row in rows:
                record = dict(zip(self.BLOCKED_COLUMNS, row))
                tally[str(record["reason"])] = tally.get(str(record["reason"]), 0) + 1
                fh.write(json.dumps({"team_id": team, **record}, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        logger.info("persons_dedup.blocked_detail_written", team_id=team, groups=len(rows), path=str(path))
        return tally

    def _classify(self, conn: psycopg.Connection, team: int, outdir: Path) -> None:
        # SET LOCAL is transaction-scoped, so this scan keeps its unlimited timeout even
        # on a connection where the session-level SET was silently dropped by a pooler
        # (observed on the US census: reader queries canceled at the server's 30-minute
        # default despite SET statement_timeout = 0).
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute(CLASSIFY_SQL, {"team": team})
            row = cur.fetchone()
            cur.execute("COMMIT")
        assert row is not None
        groups, orphaned, one_ref, needs_merge, multi_did, blocked, tombstoned, dids, cohort, ff, recon = (
            int(v) for v in row
        )
        logger.info(
            "persons_dedup.classify",
            team_id=team,
            dup_groups=groups,
            all_orphaned=orphaned,
            one_referenced=one_ref,
            needs_merge=needs_merge,
            groups_with_distinct_ids_on_multiple_rows=multi_did,
            # What repair will leave behind, and therefore what a passing verify accepts.
            blocked_groups=blocked,
            resolvable_groups=groups - blocked,
            tombstoned_members=tombstoned,
            distinct_ids=dids,
            cohort_rows=cohort,
            flag_overrides=ff,
            reconciliation_rows=recon,
        )
        if multi_did:
            logger.warning("persons_dedup.needs_real_merge", team_id=team, groups=multi_did)
        if recon:
            logger.warning("persons_dedup.reconciliation_backup_references", team_id=team, recon=recon)
        if tombstoned:
            logger.warning("persons_dedup.tombstoned_members_skipped", team_id=team, members=tombstoned)
        if blocked:
            # A count is not actionable. Write the per-group detail and report the split by
            # reason, so the groups this command refuses can be resolved without re-deriving
            # which rows they hold or why each was refused.
            tally = self._dump_blocked(conn, team, outdir)
            logger.warning("persons_dedup.blocked_by_reason", team_id=team, groups=blocked, **tally)

    def _verify(self, conn: psycopg.Connection, team: int) -> None:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET LOCAL statement_timeout = 0")
            # Both counts come from one statement on purpose. Read committed takes a fresh
            # snapshot per statement, so counting the groups and the blocked subset separately
            # lets a write land between them -- and since resolvable is the difference, that
            # reports a resolvable group the team does not have, or a negative count. One
            # statement over one snapshot cannot disagree with itself, and it saves a second
            # group-by pass over the whole team.
            cur.execute(COUNT_BLOCKED_SQL, {"team": team})
            blocked_row = cur.fetchone()
            cur.execute(VERIFY_ORPHANS_SQL, {"team": team})
            orphans_row = cur.fetchone()
            cur.execute("COMMIT")
        dups = int(blocked_row[0]) if blocked_row else 0
        blocked = int(blocked_row[1]) if blocked_row else 0
        orphans = int(orphans_row[0]) if orphans_row else 0
        resolvable = dups - blocked
        logger.info(
            "persons_dedup.verify",
            team_id=team,
            duplicate_groups=dups,
            blocked_groups=blocked,
            resolvable_groups=resolvable,
            orphaned_distinct_ids=orphans,
        )
        # Exiting non-zero on any remaining group made this unusable as a gate on the teams
        # that matter: the merge-required remainder is expected and is a separate workstream,
        # so a run that leaves only those has done everything this command can do. Only
        # groups repair could still resolve, or orphaned mappings, are a failure.
        if resolvable or orphans:
            raise CommandError(
                f"team {team}: {resolvable} resolvable duplicate group(s), "
                f"{orphans} orphaned distinct id(s); {blocked} group(s) need a real merge"
            )
        if blocked:
            logger.warning("persons_dedup.blocked_remainder", team_id=team, groups=blocked)

    def _run(
        self,
        conn: psycopg.Connection,
        team: int,
        stage_sql: str,
        options: dict,
        *,
        apply_changes: bool,
        mode: str,
    ) -> None:
        if not apply_changes:
            logger.info("persons_dedup.dry_run", team_id=team, mode=mode)

        with conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE IF NOT EXISTS persons_dedup_victims "
                "(team_id integer NOT NULL, id bigint NOT NULL, uuid uuid NOT NULL, PRIMARY KEY (team_id, id))"
            )
            cur.execute(
                "CREATE TEMP TABLE IF NOT EXISTS persons_dedup_victims_batch "
                "(team_id integer NOT NULL, id bigint NOT NULL, uuid uuid NOT NULL, PRIMARY KEY (team_id, id))"
            )
            cur.execute(f"TRUNCATE {VICTIMS_TABLE}")
            cur.execute(f"TRUNCATE {VICTIMS_TABLE}_batch")
            # The staging scan reads every duplicate group for the team and can run for
            # minutes on the large ones; SET LOCAL keeps its timeout immunity
            # transaction-scoped rather than trusting the session-level SET.
            cur.execute("BEGIN")
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute(stage_sql, {"team": team})
            staged = cur.rowcount
            cur.execute("COMMIT")
            # Temp tables get no autovacuum or autoanalyze. Without this index every
            # TAKE_BATCH full-scans and sorts the victims table, and the retired rows
            # only go dead, so the scan never gets cheaper as the run progresses. Built
            # after the staging insert so it is one bulk build, not per-row maintenance.
            cur.execute(f"CREATE INDEX IF NOT EXISTS persons_dedup_victims_uuid_id_idx ON {VICTIMS_TABLE} (uuid, id)")
            cur.execute(f"ANALYZE {VICTIMS_TABLE}")

        logger.info("persons_dedup.staged", team_id=team, mode=mode, victims=staged)
        if staged == 0:
            return

        outdir = Path(options["outdir"])
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = outdir / f"deleted_team_{team}_{mode}_{stamp}.jsonl"

        deleted = 0
        checked = 0
        batches = 0
        pruned_total = 0
        # A live-leak team can make a staged victim reachable mid-run, which is expected and
        # is handled per batch below. A large share going that way is not expected and means
        # the staging query and the gate disagree, so stop rather than grind through the set.
        prune_budget = max(20, staged // 100)
        while True:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE {VICTIMS_TABLE}_batch")
                cur.execute(TAKE_BATCH_SQL, {"batch": options["batch_size"]})
                in_batch = cur.rowcount
                # With no stats on the batch table the planner can pick a hash join and
                # seq-scan posthog_cohortpeople inside the lock-holding transaction,
                # instead of probing its person_id index once per victim.
                cur.execute(f"ANALYZE {VICTIMS_TABLE}_batch")
            if in_batch == 0:
                break
            batches += 1

            reachable = _scalar(conn, GATE_REACHABLE_SQL)
            no_survivor = _scalar(conn, GATE_NO_SURVIVOR_SQL)
            wrong_survivor = _scalar(conn, GATE_SURVIVOR_REACHABLE_SQL)
            if reachable or no_survivor or wrong_survivor:
                raise CommandError(
                    f"gate failed for team {team}: {reachable} victim(s) are reachable, "
                    f"{no_survivor} group(s) would be emptied, {wrong_survivor} group(s) would "
                    f"lose their only reachable row. Nothing deleted."
                )

            if not apply_changes:
                # Retire the batch and continue rather than returning: a dry run that stops
                # after one batch gates --batch-size victims out of the whole staged set and
                # still reports success, which on the large teams is a fraction of a percent.
                checked += in_batch
                with conn.cursor() as cur:
                    cur.execute(RETIRE_BATCH_SQL)
                continue

            with conn.cursor() as cur:
                cur.execute("BEGIN")
                cur.execute("SET LOCAL lock_timeout = '2s'")
                # The session runs with statement_timeout = 0 for the big staging scan;
                # inside the write transaction we hold FOR UPDATE row locks that live
                # ingestion can block on (updatePersonsBatch matches persons by
                # (team_id, uuid), which duplicates share), so every statement here
                # must be bounded.
                cur.execute("SET LOCAL statement_timeout = '5min'")
                cur.execute(LOCK_VICTIMS_SQL, {"team": team})
                locked = cur.rowcount
                # Re-check inside the transaction: these teams still receive writes, and a
                # concurrent insert could have made a victim reachable since the pre-flight.
                # Both gates are re-checked, not just reachability, so the failure message
                # below describes what was actually verified.
                cur.execute(GATE_REACHABLE_SQL)
                gate_row = cur.fetchone()
                cur.execute(GATE_NO_SURVIVOR_SQL)
                survivor_row = cur.fetchone()
                cur.execute(GATE_SURVIVOR_REACHABLE_SQL)
                wrong_survivor_row = cur.fetchone()
                now_reachable = int(gate_row[0]) if gate_row else 0
                now_emptied = int(survivor_row[0]) if survivor_row else 0
                now_wrong_survivor = int(wrong_survivor_row[0]) if wrong_survivor_row else 0
                # Not prunable, and never a race: staging cannot produce this, so reaching it
                # means the survivor rule and the reachability rule disagree. Stop the team.
                if now_wrong_survivor:
                    cur.execute("ROLLBACK")
                    raise CommandError(
                        f"team {team}: {now_wrong_survivor} group(s) would lose their only "
                        f"reachable row. This is not a concurrent-writer race; the survivor "
                        f"rule is wrong for this data. {deleted} row(s) already deleted."
                    )
                if locked != in_batch or now_reachable or now_emptied:
                    cur.execute("ROLLBACK")
                    logger.warning(
                        "persons_dedup.batch_raced",
                        team_id=team,
                        batch=batches,
                        locked=locked,
                        staged=in_batch,
                        reachable=now_reachable,
                        would_empty=now_emptied,
                    )
                    pruned = self._prune_batch(conn)
                    pruned_total += pruned
                    # Nothing pruned means the gate failed for a reason this does not
                    # explain, and the next iteration would take the same batch forever.
                    if pruned == 0:
                        raise CommandError(
                            f"in-transaction gate failed for team {team} "
                            f"(locked {locked}/{in_batch}, reachable {now_reachable}, "
                            f"would empty {now_emptied}) and no victim was prunable; rolled back"
                        )
                    if pruned_total > prune_budget:
                        raise CommandError(
                            f"team {team}: {pruned_total} victim(s) became unresolvable mid-run, "
                            f"over the {prune_budget} budget; staging and the gate disagree. "
                            f"{deleted} row(s) already deleted, rerun to resume"
                        )
                    continue

                # Back up after the lock, not before it. An insert into
                # posthog_featureflaghashkeyoverride takes FOR KEY SHARE on the parent
                # person row, so the FOR UPDATE above blocks one; reading dependents
                # earlier would let a row appear afterwards, get cascaded, and never
                # reach the backup. Still written and fsync'd before the delete, so a
                # rollback leaves a superset rather than a gap.
                backed_up = self._backup(conn, team, backup_path)
                if backed_up != in_batch:
                    cur.execute("ROLLBACK")
                    raise CommandError(f"backed up {backed_up} row(s) but staged {in_batch}; rolled back")

                cur.execute(DELETE_COHORT_SQL)
                cur.execute(DELETE_RECON_BACKUP_SQL)
                cur.execute(DELETE_PERSONS_SQL, {"team": team})
                removed = cur.rowcount
                if removed != in_batch:
                    cur.execute("ROLLBACK")
                    raise CommandError(f"deleted {removed} but staged {in_batch}; rolled back")

                # posthog_cohortpeople has no foreign key, so the row lock above cannot
                # block an insert into it. A cohort recalculation could have added a row
                # after DELETE_COHORT_SQL ran, which would survive as an orphan.
                cur.execute(CHECK_COHORT_ORPHANS_SQL)
                orphan_row = cur.fetchone()
                if orphan_row and orphan_row[0]:
                    cur.execute("ROLLBACK")
                    raise CommandError(
                        f"{orphan_row[0]} cohort row(s) appeared for a victim mid-transaction; rolled back"
                    )
                cur.execute("COMMIT")

            with conn.cursor() as cur:
                cur.execute(SWEEP_COHORT_ORPHANS_SQL)
                raced = cur.fetchall()
            if raced:
                # These rows were inserted after the backup was written, so record them
                # in the log; they reference persons that no longer exist either way.
                logger.warning(
                    "persons_dedup.cohort_rows_raced_the_delete",
                    team_id=team,
                    rows=[{"id": r[0], "cohort_id": r[1], "person_id": r[2]} for r in raced],
                )
            with conn.cursor() as cur:
                cur.execute(RETIRE_BATCH_SQL)
            deleted += removed
            if options["sleep_ms"] > 0:
                time.sleep(options["sleep_ms"] / 1000.0)
            logger.info("persons_dedup.batch_done", team_id=team, batch=batches, deleted=removed, total=deleted)

        if not apply_changes:
            logger.info(
                "persons_dedup.dry_run_ok", team_id=team, mode=mode, batches=batches, checked=checked, staged=staged
            )
            return

        logger.info(
            "persons_dedup.done",
            team_id=team,
            mode=mode,
            batches=batches,
            deleted=deleted,
            pruned=pruned_total,
            backup=str(backup_path),
        )

    def _prune_batch(self, conn: psycopg.Connection) -> int:
        with conn.cursor() as cur:
            cur.execute(PRUNE_BATCH_SQL)
            return cur.rowcount

    def _backup(self, conn: psycopg.Connection, team: int, path: Path) -> int:
        """Write victims and their dependent rows to JSONL, fsync'd, before any delete.

        Ordering is the guarantee: a rolled back delete leaves a superset in the file,
        but a deleted row can never be missing from it.
        """
        with conn.cursor() as cur:
            cur.execute(FETCH_PERSONS_SQL, {"team": team})
            persons = cur.fetchall()
            cur.execute(FETCH_DEPENDENTS_SQL)
            dependents = cur.fetchall()

        # The backup holds person properties. Create owner-only and refuse symlinks, so
        # a shared pod filesystem or a swapped path cannot expose or redirect it.
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            for row in persons:
                fh.write(json.dumps({"_kind": "person", **dict(zip(PERSON_COLUMNS, row))}, default=str) + "\n")
            for tbl, row_id, person_id, k, v in dependents:
                fh.write(
                    json.dumps({"_kind": tbl, "id": row_id, "person_id": person_id, "key": k, "value": v}, default=str)
                    + "\n"
                )
            fh.flush()
            os.fsync(fh.fileno())
        return len(persons)
