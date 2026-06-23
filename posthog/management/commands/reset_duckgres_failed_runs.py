from django.core.management.base import BaseCommand, CommandError

import psycopg
import structlog

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    DUCKGRES_STATUS_TABLE,
    DUCKGRES_STATUS_VIEW,
)
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
)

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Un-stick a permanently failed Duckgres sink run: writes fresh 'waiting_retry' "
        "status rows (attempt reset to 0) for its failed batches so the consumer picks "
        "them up again. Only works while the batches are inside the queue retention "
        "window — after that, heal via a full resync of the schema."
    )

    def add_arguments(self, parser):
        parser.add_argument("--run-uuid", type=str, help="Reset all failed duckgres batches of this run")
        parser.add_argument("--team-id", type=int, help="Scope by team (with --schema-id)")
        parser.add_argument("--schema-id", type=str, help="Reset all failed duckgres runs of this schema")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be reset without writing")

    def handle(self, *args, **options):
        run_uuid = options.get("run_uuid")
        team_id = options.get("team_id")
        schema_id = options.get("schema_id")
        dry_run = options.get("dry_run", False)

        if not run_uuid and not (team_id and schema_id):
            raise CommandError("Provide --run-uuid, or both --team-id and --schema-id")

        filters = ["dgs.job_state = 'failed'", f"b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'"]
        params: dict = {}
        if run_uuid:
            filters.append("b.run_uuid = %(run_uuid)s")
            params["run_uuid"] = run_uuid
        if team_id:
            filters.append("b.team_id = %(team_id)s")
            params["team_id"] = team_id
        if schema_id:
            filters.append("b.schema_id = %(schema_id)s")
            params["schema_id"] = schema_id

        where = " AND ".join(filters)
        select_sql = f"""
            SELECT dgs.batch_id, b.run_uuid, b.batch_index, b.s3_path
            FROM {DUCKGRES_STATUS_VIEW} dgs
            JOIN {BATCH_TABLE} b ON b.id = dgs.batch_id
            WHERE {where}
            ORDER BY b.run_uuid, b.batch_index
        """

        with psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            rows = conn.execute(select_sql, params).fetchall()
            if not rows:
                self.stdout.write("No failed duckgres batches match — nothing to reset.")
                return

            self.stdout.write(f"{len(rows)} failed duckgres batch(es) across {len({r[1] for r in rows})} run(s):")
            for batch_id, r_uuid, batch_index, s3_path in rows:
                self.stdout.write(f"  run={r_uuid} batch_index={batch_index} batch_id={batch_id} s3={s3_path}")

            if dry_run:
                self.stdout.write("Dry run — no changes written.")
                return

            cursor = conn.execute(
                f"""
                INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, error_response)
                SELECT dgs.batch_id, 'waiting_retry', 0,
                       jsonb_build_object('error', 'manually reset via reset_duckgres_failed_runs')
                FROM {DUCKGRES_STATUS_VIEW} dgs
                JOIN {BATCH_TABLE} b ON b.id = dgs.batch_id
                WHERE {where}
                """,
                params,
            )
            self.stdout.write(self.style.SUCCESS(f"Reset {cursor.rowcount} batch(es) to waiting_retry (attempt 0)."))
            self.stdout.write(
                "Note: if any batch's S3 extract has already been pruned, its retry will fail again — "
                "heal those schemas with a full resync instead."
            )
