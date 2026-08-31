from typing import Any

from more_itertools import chunked
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger

COHORT_DELETION_MARK_FAILURE_COUNTER = Counter(
    "posthog_cohort_deletion_mark_failure_total",
    "Times cohort deletion mark failed",
)

COHORT_DELETION_RUN_FAILURE_COUNTER = Counter(
    "posthog_cohort_deletion_run_failure_total",
    "Times cohort deletion run failed",
)


# A backlog of pending deletions would otherwise become one mutation whose predicate ORs every
# cohort together. Chunking keeps each mutation's predicate and blast radius bounded, and a chunk
# that fails leaves the later chunks for the next run.
COHORT_DELETION_CHUNK_SIZE = 500


class AsyncCohortDeletion(AsyncDeletionProcess):
    DELETION_TYPES = [DeletionType.Cohort_full, DeletionType.Cohort_stale]

    def process(self, deletions: list[AsyncDeletion]):
        if len(deletions) == 0:
            logger.warn("No AsyncDeletion for cohorts to perform")
            return

        logger.warn(
            "Starting AsyncDeletion on `cohortpeople` table in ClickHouse",
            {
                "count": len(deletions),
                "team_ids": list({row.team_id for row in deletions}),
            },
        )

        for chunk in chunked(deletions, COHORT_DELETION_CHUNK_SIZE):
            conditions, args = self._conditions(chunk)

            # nosemgrep: clickhouse-fstring-param-audit - conditions from internal _conditions method
            sync_execute(
                f"""
                DELETE FROM cohortpeople
                WHERE {" OR ".join(conditions)}
                """,
                args,
                settings={},
            )

    def _verify_by_group(self, deletion_type: int, async_deletions: list[AsyncDeletion]) -> list[AsyncDeletion]:
        if deletion_type == DeletionType.Cohort_stale or deletion_type == DeletionType.Cohort_full:
            cohort_ids_with_data = self._verify_by_column("team_id, cohort_id", async_deletions)
            return [
                row for row in async_deletions if (row.team_id, int(row.key.split("_")[0])) not in cohort_ids_with_data
            ]
        else:
            return []

    def _verify_by_column(self, distinct_columns: str, async_deletions: list[AsyncDeletion]) -> set[tuple[Any, ...]]:
        found: set[tuple[Any, ...]] = set()
        for chunk in chunked(async_deletions, COHORT_DELETION_CHUNK_SIZE):
            conditions, args = self._conditions(chunk)
            # nosemgrep: clickhouse-fstring-param-audit - distinct_columns hardcoded, conditions internal
            clickhouse_result = sync_execute(
                f"""
                SELECT DISTINCT {distinct_columns}
                FROM cohortpeople
                WHERE {" OR ".join(conditions)}
                """,
                args,
                settings={},
            )
            found.update(tuple(row) for row in clickhouse_result)
        return found

    def _column_name(self, async_deletion: AsyncDeletion):
        assert async_deletion.deletion_type in (
            DeletionType.Cohort_full,
            DeletionType.Cohort_stale,
        )
        return "cohort_id"

    def _condition(self, async_deletion: AsyncDeletion, suffix: str) -> tuple[str, dict]:
        team_id_param = f"team_id{suffix}"
        key_param = f"key{suffix}"
        version_param = f"version{suffix}"
        if async_deletion.deletion_type == DeletionType.Cohort_full:
            key, _ = async_deletion.key.split("_")
            return (
                f"( team_id = %({team_id_param})s AND {self._column_name(async_deletion)} = %({key_param})s )",
                {
                    team_id_param: async_deletion.team_id,
                    key_param: key,
                },
            )
        else:
            key, version = async_deletion.key.split("_")
            return (
                f"( team_id = %({team_id_param})s AND {self._column_name(async_deletion)} = %({key_param})s AND version < %({version_param})s )",
                {
                    team_id_param: async_deletion.team_id,
                    version_param: version,
                    key_param: key,
                },
            )


def sweep_cohort_deletions() -> list[str]:
    """Run both cohort deletion passes and return the names of any that failed.

    Each pass is guarded on its own: failing to tick off cohorts whose rows are already gone
    must not stop the pass that actually removes rows.
    """
    runner = AsyncCohortDeletion()
    failed = []

    try:
        runner.mark_deletions_done()
    except Exception as e:
        logger.error("Failed to mark cohort deletions done", error=e, exc_info=True)
        COHORT_DELETION_MARK_FAILURE_COUNTER.inc()
        failed.append("mark")

    try:
        runner.run()
    except Exception as e:
        logger.error("Failed to run cohort deletions", error=e, exc_info=True)
        COHORT_DELETION_RUN_FAILURE_COUNTER.inc()
        failed.append("run")

    return failed
