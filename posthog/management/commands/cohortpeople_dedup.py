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
clean before the build starts.

    python manage.py cohortpeople_dedup --mode verify
    python manage.py cohortpeople_dedup --mode repair
    python manage.py cohortpeople_dedup --mode verify

Work is bounded per cohort, not per table. The walk finds each cohort through the
(cohort_id, person_id) index rather than grouping the whole table, and the delete inside a cohort
runs in batches, so no statement holds a snapshot for longer than one batch takes. Use --sleep to
put the pace under the primary's write load.
"""

from __future__ import annotations

import time
import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog
from psycopg import sql

from posthog.persons_db import persons_db_connection

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

SURPLUS_IDS_SQL = """
SELECT id FROM (
    SELECT id, row_number() OVER (
        PARTITION BY person_id ORDER BY version DESC NULLS LAST, id DESC
    ) AS rn
    FROM posthog_cohortpeople
    WHERE cohort_id = %(cohort_id)s
) ranked
WHERE rn > 1
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
    while True:
        with conn.cursor() as cur:
            cur.execute(SURPLUS_IDS_SQL, {"cohort_id": cohort_id, "batch_size": batch_size})
            ids = [row[0] for row in cur.fetchall()]
        if not ids:
            return deleted
        with conn.cursor() as cur:
            cur.execute(DELETE_SQL, {"ids": ids})
            deleted += cur.rowcount
        if sleep:
            time.sleep(sleep)


def _refresh_cohort_count(conn: psycopg.Connection[Any], cohort_id: int) -> None:
    """Write the corrected size back to the cohort, which is what the cohort page reads.

    The count the product shows is the same bare COUNT(*) this reads, so the repaired value is
    available on the connection already open here. Without this the cohort keeps showing the
    inflated size until its next recalculation.
    """
    with conn.cursor() as cur:
        cur.execute(COUNT_SQL, {"cohort_id": cohort_id})
        row = cur.fetchone()
    assert row is not None
    Cohort.objects.filter(pk=cohort_id).update(count=int(row[0]))


class Command(BaseCommand):
    help = "Remove surplus posthog_cohortpeople rows for (cohort_id, person_id) pairs held more than once"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--mode",
            choices=["verify", "repair"],
            default="verify",
            help="verify reports surplus rows and changes nothing; repair deletes them",
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
        with persons_db_connection(writer=repair, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(options["statement_timeout_ms"])))

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
