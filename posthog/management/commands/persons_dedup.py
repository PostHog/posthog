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

    A person row owning no posthog_persondistinctid row is unreachable. The product
    resolves a person only via distinct_id -> posthog_persondistinctid -> person_id
    (rust/feature-flags/src/flags/flag_matching_utils.rs:839 for hash key overrides,
    :284 for static cohorts), so nothing keyed to that person_id can be read either.

So a row owning zero distinct IDs can be deleted without changing any product
behaviour, and the feature-flag overrides that cascade away with it were already
unreachable. Moving them onto the surviving person would do the opposite: it would
resurrect dead data and could change which flag variant a live user receives.

The three dependent tables behave differently on DELETE in production, which is why
the reachability assertion runs before every delete and again inside the transaction:

    posthog_persondistinctid            FK NO ACTION -> Postgres blocks the delete
    posthog_featureflaghashkeyoverride  FK CASCADE   -> silently removes overrides
    posthog_cohortpeople                no FK        -> silently orphans rows

Only the first fails loudly, so the command cannot rely on the database to catch a
mistake in the other two.

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

from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog

from posthog.persons_db import persons_db_connection

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
           (SELECT count(*) FROM posthog_persondistinctid pdi
             WHERE pdi.team_id = p.team_id AND pdi.person_id = p.id) AS n_did,
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
scored AS (
    SELECT *, (n_did + n_cohort + n_ff + n_recon) AS refs FROM members
),
ranked AS (
    SELECT *,
           row_number() OVER (
               PARTITION BY team_id, uuid
               ORDER BY is_deleted ASC, (n_did > 0) DESC, refs DESC, is_identified DESC,
                        version DESC NULLS LAST, created_at ASC, id ASC
           ) AS rn
    FROM scored
),
-- One row per duplicate group, in the terms the staging queries below use, so
-- classify and verify report exactly what repair will and will not resolve.
per_group AS (
    SELECT uuid,
           count(*) AS members,
           count(*) FILTER (WHERE n_did > 0) AS live_owners,
           count(*) FILTER (
               WHERE rn > 1 AND n_did = 0 AND n_recon = 0 AND NOT is_deleted
           ) AS stageable
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
# feature-flag overrides and cohort rows are dead data and may cascade/be removed.
# Groups where two rows own distinct IDs are excluded -- those need a real merge and
# this command refuses to guess.
STAGE_UNREACHABLE_SQL = (
    _MEMBERS_CTE
    + f"""
INSERT INTO {VICTIMS_TABLE} (team_id, id, uuid)
SELECT team_id, id, uuid FROM ranked
WHERE rn > 1
  AND n_did = 0
  AND n_recon = 0
  AND NOT is_deleted
  AND uuid IN (SELECT uuid FROM ranked GROUP BY uuid
                HAVING count(*) FILTER (WHERE n_did > 0) <= 1)
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

TAKE_BATCH_SQL = f"""
INSERT INTO {VICTIMS_TABLE}_batch (team_id, id, uuid)
SELECT team_id, id, uuid FROM {VICTIMS_TABLE} ORDER BY uuid, id LIMIT %(batch)s
"""

RETIRE_BATCH_SQL = f"""
DELETE FROM {VICTIMS_TABLE} v USING {VICTIMS_TABLE}_batch b
WHERE v.team_id = b.team_id AND v.id = b.id
"""

# Drop from the staged set the batch members a concurrent writer made undeletable: one that
# gained a reference since staging, or one that no longer exists because something else
# removed it. Aborting the whole run instead would discard a staging scan that costs minutes
# on the large teams, and on a team still receiving writes it can prevent the run finishing
# at all. Only the staged set is touched -- no person row is modified.
PRUNE_BATCH_SQL = f"""
DELETE FROM {VICTIMS_TABLE} v
USING {VICTIMS_TABLE}_batch b
WHERE v.team_id = b.team_id AND v.id = b.id
  AND (
      NOT EXISTS (SELECT 1 FROM posthog_person p
                   WHERE p.team_id = v.team_id AND p.id = v.id)
   OR EXISTS (SELECT 1 FROM posthog_persondistinctid pdi
               WHERE pdi.team_id = v.team_id AND pdi.person_id = v.id)
   OR EXISTS (SELECT 1 FROM posthog_person_reconciliation_backup rb
               WHERE rb.team_id = v.team_id AND rb.person_id = v.id)
  )
"""

# The load-bearing assertion. A victim owning a distinct ID is reachable, so deleting it
# would change product behaviour and silently destroy its overrides via the cascade.
GATE_REACHABLE_SQL = f"""
SELECT count(*) FROM {VICTIMS_TABLE}_batch v
WHERE EXISTS (SELECT 1 FROM posthog_persondistinctid pdi
               WHERE pdi.team_id = v.team_id AND pdi.person_id = v.id)
   OR EXISTS (SELECT 1 FROM posthog_person_reconciliation_backup rb
               WHERE rb.team_id = v.team_id AND rb.person_id = v.id)
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
"""

# Cohort rows have no FK, so the cascade will not remove them. Delete explicitly, before
# the person row, so a failure here aborts before anything is lost.
DELETE_COHORT_SQL = f"""
DELETE FROM posthog_cohortpeople cp
USING {VICTIMS_TABLE}_batch b WHERE cp.person_id = b.id
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

VERIFY_DUPS_SQL = """
SELECT count(*) FROM (
    SELECT uuid FROM posthog_person WHERE team_id = %(team)s
    GROUP BY team_id, uuid HAVING count(*) > 1
) x
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
)


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
                    self._classify(conn, team)
                else:
                    self._verify(conn, team)
                return

            if _scalar(conn, "SELECT CASE WHEN pg_is_in_recovery() THEN 1 ELSE 0 END"):
                raise CommandError("connected to a replica; this mode needs the writer")

            _check_session_stability(conn)

            stage_sql = STAGE_UNREFERENCED_SQL if mode == "delete-unreferenced" else STAGE_UNREACHABLE_SQL
            self._run(conn, team, stage_sql, options, apply_changes=apply_changes, mode=mode)

    def _classify(self, conn: psycopg.Connection, team: int) -> None:
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

    def _verify(self, conn: psycopg.Connection, team: int) -> None:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET LOCAL statement_timeout = 0")
            cur.execute(VERIFY_DUPS_SQL, {"team": team})
            dups_row = cur.fetchone()
            cur.execute(VERIFY_ORPHANS_SQL, {"team": team})
            orphans_row = cur.fetchone()
            cur.execute(COUNT_BLOCKED_SQL, {"team": team})
            blocked_row = cur.fetchone()
            cur.execute("COMMIT")
        dups = int(dups_row[0]) if dups_row else 0
        orphans = int(orphans_row[0]) if orphans_row else 0
        blocked = int(blocked_row[1]) if blocked_row else 0
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
            if reachable or no_survivor:
                raise CommandError(
                    f"gate failed for team {team}: {reachable} victim(s) are reachable, "
                    f"{no_survivor} group(s) would be emptied. Nothing deleted."
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
                now_reachable = int(gate_row[0]) if gate_row else 0
                now_emptied = int(survivor_row[0]) if survivor_row else 0
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
