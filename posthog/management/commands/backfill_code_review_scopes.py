import time
from collections.abc import Iterator

from django.core.management.base import BaseCommand
from django.db import connections

from posthog.dataclasses import frozen
from posthog.scopes.catalog import RENAMED_OAUTH_SCOPE_OBJECTS

RENAMED_SCOPES: dict[str, str] = {
    f"{old}:{action}": f"{new}:{action}"
    for old, new in RENAMED_OAUTH_SCOPE_OBJECTS.items()
    for action in ("read", "write")
}


def _missing_array_scopes(column: str) -> str:
    """The new scopes `column` (a varchar array) lacks next to an old scope it holds, as an array."""
    return f"""ARRAY(
        SELECT m.new FROM unnest(%(olds)s::varchar[], %(news)s::varchar[]) WITH ORDINALITY AS m(old, new, ord)
        WHERE {column} @> ARRAY[m.old] AND NOT {column} @> ARRAY[m.new]
        ORDER BY m.ord
    )::varchar[]"""


def _missing_text_scopes(column: str) -> str:
    """The new scopes `column` (space-separated text) lacks next to an old scope it holds, as ' a b'."""
    tokens = f"string_to_array({column}, ' ')"
    return f"""COALESCE((
        SELECT string_agg(' ' || m.new, '' ORDER BY m.ord)
        FROM unnest(%(olds)s::text[], %(news)s::text[]) WITH ORDINALITY AS m(old, new, ord)
        WHERE {tokens} @> ARRAY[m.old] AND NOT {tokens} @> ARRAY[m.new]
    ), '')"""


@frozen
class ArrayColumnUpdate:
    set_clause: str
    needs_update: str


def _array_column_update(column: str) -> ArrayColumnUpdate:
    missing = _missing_array_scopes(column)
    needs = f"cardinality({missing}) > 0"
    return ArrayColumnUpdate(
        set_clause=f"{column} = CASE WHEN {needs} THEN {column} || {missing} ELSE {column} END",
        needs_update=needs,
    )


class Command(BaseCommand):
    help = (
        "Add the code_review scope names next to the old review_hog and stamphog names on OAuth "
        "applications and usable OAuth access tokens. Safe to stop and re-run at any point."
    )

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1000, help="Rows per UPDATE")
        parser.add_argument("--sleep-interval", type=float, default=0.1, help="Seconds to sleep between batches")
        parser.add_argument(
            "--table",
            choices=["applications", "access_tokens", "all"],
            default="all",
            help="Which table to backfill",
        )
        parser.add_argument("--database", default="default", help="Database alias to run against")
        parser.add_argument("--dry-run", action="store_true", help="Count the rows to change, change nothing")

    def handle(self, *args, **options):
        self.connection = connections[options["database"]]
        self.batch_size = options["batch_size"]
        self.sleep_interval = options["sleep_interval"]
        self.dry_run = options["dry_run"]
        self.params = {"olds": list(RENAMED_SCOPES), "news": list(RENAMED_SCOPES.values())}

        if options["table"] in ("applications", "all"):
            self.backfill_applications()
        if options["table"] in ("access_tokens", "all"):
            self.backfill_access_tokens()

    def backfill_applications(self) -> None:
        # No filter in the SELECT, so the planner cannot pick a scope index and sort every match per
        # batch. The UPDATE re-checks each row, so a concurrently changed row is skipped.
        scopes = _array_column_update("scopes")
        optional = _array_column_update("optional_scopes")
        needs = f"({scopes.needs_update} OR {optional.needs_update})"
        update_sql = f"""
            UPDATE posthog_oauthapplication SET {scopes.set_clause}, {optional.set_clause}
            WHERE id = ANY(%(ids)s) AND {needs}
        """
        count_sql = f"SELECT count(*) FROM posthog_oauthapplication WHERE id = ANY(%(ids)s) AND {needs}"

        totals = {"scanned": 0, "updated": 0}
        started = time.monotonic()
        for ids in self._id_batches("posthog_oauthapplication", "id", "TRUE"):
            with self.connection.cursor() as cursor:
                self._run_batch(cursor, update_sql, count_sql, ids, totals)
            self._progress("applications", totals, started)
        self._progress("applications", totals, started, done=True)

    def backfill_access_tokens(self) -> None:
        # Only tokens that can still be used: unexpired ones, and the ones an unrevoked refresh token
        # points at (a refresh reads the old token's scope). Expired tokens are never read again.
        sources = [
            ("posthog_oauthaccesstoken", "id", "application_id IS NOT NULL AND expires > now()"),
            ("posthog_oauthrefreshtoken", "access_token_id", "revoked IS NULL AND access_token_id IS NOT NULL"),
        ]

        missing = _missing_text_scopes("scope")
        needs = f"{missing} <> ''"
        update_sql = f"""
            UPDATE posthog_oauthaccesstoken SET scope = scope || {missing}
            WHERE id = ANY(%(ids)s) AND application_id IS NOT NULL AND {needs}
        """
        count_sql = f"SELECT count(*) FROM posthog_oauthaccesstoken WHERE id = ANY(%(ids)s) AND application_id IS NOT NULL AND {needs}"

        totals = {"scanned": 0, "updated": 0}
        started = time.monotonic()
        for table, id_column, where in sources:
            for ids in self._id_batches(table, id_column, where):
                with self.connection.cursor() as cursor:
                    self._run_batch(cursor, update_sql, count_sql, ids, totals)
                self._progress("access_tokens", totals, started)
        self._progress("access_tokens", totals, started, done=True)

    def _id_batches(self, table: str, id_column: str, where: str) -> Iterator[list]:
        """Batches of `id_column` values from rows matching `where`, walked in order of that column."""
        # A short query per batch, not one long cursor: an open transaction on the writer would hold
        # back vacuum for the whole run.
        last_id = None
        while True:
            params: dict = {"limit": self.batch_size}
            cursor_filter = ""
            if last_id is not None:
                cursor_filter = f"AND {id_column} > %(last_id)s"
                params["last_id"] = last_id
            with self.connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT {id_column} FROM {table} WHERE {where} {cursor_filter} ORDER BY {id_column} LIMIT %(limit)s",
                    params,
                )
                ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                return
            yield ids
            if len(ids) < self.batch_size:
                return
            last_id = ids[-1]

    def _run_batch(self, cursor, update_sql: str, count_sql: str, ids: list, totals: dict[str, int]) -> None:
        params = {**self.params, "ids": ids}
        if self.dry_run:
            cursor.execute(count_sql, params)
            totals["updated"] += cursor.fetchone()[0]
        else:
            cursor.execute(update_sql, params)
            totals["updated"] += cursor.rowcount
        totals["scanned"] += len(ids)
        if self.sleep_interval:
            time.sleep(self.sleep_interval)

    def _progress(self, label: str, totals: dict[str, int], started: float, done: bool = False) -> None:
        batches = totals["scanned"] // self.batch_size
        if not done and batches % 50:
            return
        verb = "would update" if self.dry_run else "updated"
        elapsed = time.monotonic() - started
        self.stdout.write(
            f"{label}: {'done, ' if done else ''}scanned {totals['scanned']}, {verb} {totals['updated']} "
            f"in {elapsed:.0f}s"
        )
