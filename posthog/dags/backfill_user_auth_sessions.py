"""Dagster job to backfill user_id/login_method onto pre-swap django_session rows.

The session store stamps user_id on every new/active session, so this only sweeps the idle
long-tail of sessions that pre-date the engine swap. It is idempotent (it touches only rows where
user_id is NULL) and batched, so it is safe to re-run and resumes where a prior run left off.
"""

import dagster
import pydantic

from posthog.dags.common import JobOwners
from posthog.session.backfill import backfill_session_user_ids


class BackfillUserAuthSessionsConfig(dagster.Config):
    batch_size: int = pydantic.Field(default=2000, description="Sessions decoded per batch.")
    sleep_seconds: float = pydantic.Field(default=0.1, description="Seconds to sleep between batches to cap DB load.")
    dry_run: bool = pydantic.Field(default=True, description="If true, scan and report counts without writing rows.")


@dagster.op
def backfill_user_auth_sessions_op(
    context: dagster.OpExecutionContext,
    config: BackfillUserAuthSessionsConfig,
) -> None:
    context.log.info(f"Backfilling session user_id (dry_run={config.dry_run}, batch_size={config.batch_size})")
    stats = backfill_session_user_ids(
        batch_size=config.batch_size,
        sleep_seconds=config.sleep_seconds,
        dry_run=config.dry_run,
    )
    context.log.info(f"Scanned {stats.scanned} sessions, updated {stats.updated} (dry_run={config.dry_run})")
    context.add_output_metadata(
        {
            "scanned": dagster.MetadataValue.int(stats.scanned),
            "updated": dagster.MetadataValue.int(stats.updated),
            "dry_run": dagster.MetadataValue.bool(config.dry_run),
        }
    )


@dagster.job(
    description="Backfill user_id/login_method onto pre-swap django_session rows (idempotent, batched).",
    tags={"owner": JobOwners.TEAM_SECURITY.value},
)
def backfill_user_auth_sessions_job():
    backfill_user_auth_sessions_op()
