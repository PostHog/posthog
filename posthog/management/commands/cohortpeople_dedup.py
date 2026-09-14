"""Remove surplus `posthog_cohortpeople` rows, so a unique (cohort_id, person_id) index can build.

The table had no uniqueness guarantee, and two writers could create a second row for a pair that
already had one: the bulk population insert, whose NOT EXISTS guard reads a pre-statement
snapshot and so lets two concurrent calls through, and the merge path, which moved a source
person's rows onto a target that could already hold a row for the same cohort.

The unique index posthog_cohortpeople_cohort_id_person_id_uniq rejects the pair, but it cannot
build while one is present, and on a database large enough to need CREATE UNIQUE INDEX
CONCURRENTLY it cannot build inside a migration either. This command is the step that comes
first there. The rows already written stay until it runs, whatever the writers now do.

A surplus row is user-visible. Static cohort size is a bare COUNT(*) over this table, so each
one adds a person to the size the cohort page shows. It also multiplies the work of every
per-member statement that has to reach the pair.

WHICH ROW SURVIVES

One row per (cohort_id, person_id) survives, the one with the highest version. Cohort
recalculation writes a new version and then sweeps the rows below the cohort's pinned version,
so keeping the highest version keeps the row that sweep would keep. The rows deleted here carry
no information the survivor does not: person_id and cohort_id are equal by construction, and
nothing outside this table references posthog_cohortpeople.id.

RUNNING IT

Run `--mode verify` first, and again after a repair. It reports the cohorts that still hold
surplus rows, and the index build fails on the first pair it reaches, so verify has to come back
clean before the build starts. Verify exits non-zero while a surplus row is left, so a script
that chains the steps stops before the build.

    python manage.py cohortpeople_dedup --mode verify
    python manage.py cohortpeople_dedup --mode repair
    python manage.py cohortpeople_dedup --mode verify

Work is bounded per cohort, not per table. The walk finds each cohort through the
(cohort_id, person_id) index rather than grouping the whole table, and the delete inside a cohort
runs in batches, so no statement holds a snapshot for longer than one batch takes. Use --sleep to
put the pace under the primary's write load.
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog
from psycopg import sql

from posthog.persons_db import persons_db_connection, persons_db_url

from products.cohorts.backend.models.cohort import Cohort

logger = structlog.get_logger(__name__)
# The posthoganalytics SDK claims the "posthog" logger name and clamps it to WARNING at
# client init, so every INFO record this command emits is dropped and a run leaves no log.
logging.getLogger(__name__).setLevel(logging.INFO)

# Walk the distinct cohort ids through the (cohort_id, person_id) index. Grouping the whole table
# would hold one snapshot for the length of a full scan.
NEXT_COHORT_SQL = """
SELECT cohort_id FROM posthog_cohortpeople
WHERE cohort_id > %(after)s
ORDER BY cohort_id
LIMIT 1
"""

# count(*) - count(DISTINCT person_id) is the number of rows that have to go, in one pass over
# the cohort's slice of the index.
SURPLUS_SQL = """
SELECT count(*) - count(DISTINCT person_id) FROM posthog_cohortpeople
WHERE cohort_id = %(cohort_id)s
"""

# person_from resumes the walk where the last batch stopped. Without it every batch re-enters
# the (cohort_id, person_id) index at the cohort's first person and re-ranks the rows already
# swept before it reaches a new duplicate, so each batch reads more of the cohort than the last.
SURPLUS_IDS_SQL = """
SELECT person_id, id FROM (
    SELECT person_id, id, row_number() OVER (
        PARTITION BY person_id ORDER BY version DESC NULLS LAST, id DESC
    ) AS rn
    FROM posthog_cohortpeople
    WHERE cohort_id = %(cohort_id)s AND person_id >= %(person_from)s
) ranked
WHERE rn > 1
ORDER BY person_id
LIMIT %(batch_size)s
"""

DELETE_SQL = "DELETE FROM posthog_cohortpeople WHERE id = ANY(%(ids)s)"

COUNT_SQL = "SELECT count(*) FROM posthog_cohortpeople WHERE cohort_id = %(cohort_id)s"


def _cohort_ids(conn: psycopg.Connection[Any]) -> list[int]:
    ids: list[int] = []
    after = -1
    while True:
        with conn.cursor() as cur:
            cur.execute(NEXT_COHORT_SQL, {"after": after})
            row = cur.fetchone()
        if row is None:
            return ids
        after = row[0]
        ids.append(after)


def _surplus(conn: psycopg.Connection[Any], cohort_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(SURPLUS_SQL, {"cohort_id": cohort_id})
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _repair_cohort(conn: psycopg.Connection[Any], cohort_id: int, batch_size: int, sleep: float) -> int:
    deleted = 0
    person_from = 0
    while True:
        with conn.cursor() as cur:
            cur.execute(
                SURPLUS_IDS_SQL,
                {"cohort_id": cohort_id, "person_from": person_from, "batch_size": batch_size},
            )
            rows = cur.fetchall()
        if not rows:
            return deleted
        # A short batch means the limit was not reached, so the cohort holds nothing after it.
        exhausted = len(rows) < batch_size
        last_person = rows[-1][0]
        if not exhausted:
            person_from = last_person
            # The limit can cut the last person's rows in two, so that person waits for the next
            # batch. A batch that holds one person cannot wait, because the next batch would read
            # the same rows again, so it deletes them and the next batch takes the remainder.
            if rows[0][0] != last_person:
                rows = [row for row in rows if row[0] != last_person]
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL, {"ids": [row[1] for row in rows]})
            deleted += cur.rowcount
        if exhausted:
            return deleted
        if sleep:
            time.sleep(sleep)


def _refresh_cohort_count(conn: psycopg.Connection[Any], cohort_id: int) -> None:
    """Write the corrected size back to the cohort, which is what the cohort page reads.

    The count the product shows is the same bare COUNT(*) this reads, so the repaired value is
    available on the connection already open here. Without this the cohort keeps showing the
    inflated size until its next recalculation.

    Only a static cohort takes its size from this table. A cohort flipped back to dynamic keeps
    its old rows here, and its size comes from ClickHouse instead, so the is_static filter stops
    an obsolete membership total from replacing it. The surplus rows are still deleted.
    """
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL, {"cohort_id": cohort_id})
        row = cur.fetchone()
    assert row is not None
    Cohort.objects.filter(pk=cohort_id, is_static=True).update(count=int(row[0]))


def _assert_explicit_target(writer: bool) -> None:
    """Refuse a silently defaulted database, and log the one chosen.

    posthog.persons_db falls back to a localhost URL built from PG* when neither persons URL is
    set, and on a deployed pod PG* usually point at the main cluster. A repair run would then
    delete rows from whatever posthog_cohortpeople resolves to there, and the deletes are not
    recoverable. Host and dbname are logged, and no credentials, because that is what tells the
    operator the shell is pointed at the persons database.
    """
    if not os.getenv("PERSONS_DB_WRITER_URL") and not os.getenv("PERSONS_DB_READER_URL"):
        var = "PERSONS_DB_WRITER_URL" if writer else "PERSONS_DB_READER_URL"
        raise CommandError(
            f"{var} is not set, so the persons-DB URL would fall back to a localhost default "
            "built from PG*. Refusing to run: on a deployed pod that default points somewhere "
            "else entirely. Set the variable explicitly."
        )
    parts = urlsplit(persons_db_url(writer=writer))
    logger.info(
        "cohortpeople_dedup.target",
        host=parts.hostname,
        port=parts.port,
        dbname=(parts.path or "/").lstrip("/"),
        role="writer" if writer else "reader",
    )


def _assert_session_is_stable(conn: psycopg.Connection[Any], timeout_ms: int) -> None:
    """Abort when the connection does not behave like one backend session.

    A pooler in transaction mode sends consecutive statements to different backends, so the
    statement timeout set once at startup applies to none of them. The sweep would then run
    unbounded against a primary, which is the opposite of what --statement-timeout-ms promises,
    and nothing would report it. persons_dedup refuses the same endpoint for the same reason.
    pg_settings reports the value in milliseconds, unlike SHOW, which normalizes the unit.
    """
    pids: set[int] = set()
    with conn.cursor() as cur:
        for _ in range(3):
            cur.execute("SELECT pg_backend_pid()")
            row = cur.fetchone()
            assert row is not None
            pids.add(row[0])
        cur.execute("SELECT setting::int FROM pg_settings WHERE name = 'statement_timeout'")
        row = cur.fetchone()
        assert row is not None
        applied = int(row[0])
    if len(pids) == 1 and applied == timeout_ms:
        return
    raise CommandError(
        f"connection is not session-stable (pooled/multiplexed): saw backend pids {sorted(pids)}, "
        f"and statement_timeout reads {applied}ms where {timeout_ms}ms was set. Session settings "
        "do not survive between statements there, so --statement-timeout-ms would not bound the "
        "sweep. Use a direct writer endpoint, not a transaction-pooled one."
    )


class Command(BaseCommand):
    help = "Remove surplus posthog_cohortpeople rows for (cohort_id, person_id) pairs held more than once"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--mode",
            choices=["verify", "repair"],
            default="verify",
            help="verify reports surplus rows, changes nothing, and exits non-zero if any remain; repair deletes them",
        )
        parser.add_argument(
            "--cohort-id",
            type=int,
            action="append",
            dest="cohort_ids",
            help="limit the run to this cohort, repeatable; the default walks every cohort",
        )
        parser.add_argument("--batch-size", type=int, default=5000, help="rows deleted per statement")
        parser.add_argument("--sleep", type=float, default=0.0, help="seconds to wait between delete batches")
        parser.add_argument(
            "--statement-timeout-ms",
            type=int,
            default=60_000,
            help="per-statement timeout on the connection",
        )
        parser.add_argument(
            "--skip-count-refresh",
            action="store_true",
            help="repair only: leave the stored cohort size alone instead of correcting it",
        )

    def handle(self, **options: Any) -> None:
        mode = options["mode"]
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1")

        repair = mode == "repair"
        _assert_explicit_target(repair)
        with persons_db_connection(writer=repair, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(options["statement_timeout_ms"])))
            # Only the delete path, matching persons_dedup: a pooled reader costs the gate its
            # bound, but a pooled writer costs the sweep its bound while it deletes.
            if repair:
                _assert_session_is_stable(conn, options["statement_timeout_ms"])

            cohort_ids = options["cohort_ids"] or _cohort_ids(conn)
            affected = 0
            surplus_total = 0

            for cohort_id in cohort_ids:
                # Repair counts what it deleted rather than calling _surplus first, which would
                # cost a second pass over every cohort in the table to learn the same number.
                surplus = (
                    _repair_cohort(conn, cohort_id, batch_size, options["sleep"])
                    if repair
                    else _surplus(conn, cohort_id)
                )
                if surplus == 0:
                    continue
                affected += 1
                surplus_total += surplus
                if repair and not options["skip_count_refresh"]:
                    _refresh_cohort_count(conn, cohort_id)
                logger.info(f"cohortpeople_dedup.{mode}", cohort_id=cohort_id, surplus=surplus)

        self.stdout.write(
            f"{mode}: {len(cohort_ids)} cohort(s) scanned, {affected} with surplus rows, "
            f"{surplus_total} surplus row(s) {'deleted' if repair else 'found'}"
        )

        # Verify is the gate the index build waits on, so its result has to reach a caller that
        # only reads the exit status. The count repair reports is work done, not a failure.
        if not repair and surplus_total:
            raise CommandError(
                f"{surplus_total} surplus row(s) remain across {affected} cohort(s). "
                "Run --mode repair before you build the unique index."
            )
