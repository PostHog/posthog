from typing import Any, Dict, List, Set, Tuple

from posthog.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger


class AsyncCohortDeletion(AsyncDeletionProcess):
    def process(self, deletions: List[AsyncDeletion]):
        if len(deletions) == 0:
            logger.debug("No AsyncDeletion for cohorts to perform")
            return

        logger.info(
            "Starting AsyncDeletion on `cohortpeople` table in ClickHouse",
            {"count": len(deletions), "team_ids": list(set(row.team_id for row in deletions))},
        )

        conditions, args = self._conditions(deletions)

        sync_execute(
            f"""
            ALTER TABLE cohortpeople
            DELETE WHERE {" OR ".join(conditions)}
            """,
            args,
        )

    def _verify_by_group(self, deletion_type: int, async_deletions: List[AsyncDeletion]) -> List[AsyncDeletion]:
        if deletion_type == DeletionType.Cohort_stale or deletion_type == DeletionType.Cohort_full:
            cohort_ids_with_data = self._verify_by_column("team_id, cohort_id", async_deletions)
            return [row for row in async_deletions if (row.team_id, row.key.split("_")[0]) not in cohort_ids_with_data]
        else:
            return []

    def _verify_by_column(self, distinct_columns: str, async_deletions: List[AsyncDeletion]) -> Set[Tuple[Any, ...]]:
        conditions, args = self._conditions(async_deletions)
        clickhouse_result = sync_execute(
            f"""
            SELECT DISTINCT {distinct_columns}
            FROM cohortpeople
            WHERE {" OR ".join(conditions)}
            """,
            args,
        )
        return set(tuple(row) for row in clickhouse_result)

    def _column_name(self, async_deletion: AsyncDeletion):
        assert async_deletion.deletion_type in (
            DeletionType.Cohort_full,
            DeletionType.Cohort_stale,
        )
        return "cohort_id"

    def _condition(self, async_deletion: AsyncDeletion, suffix: str) -> Tuple[str, Dict]:
        if async_deletion.deletion_type == DeletionType.Cohort_full:
            key, _ = async_deletion.key.split("_")
            return f"team_id = %(team_id{suffix})s AND {self._column_name(async_deletion)} = %(key{suffix})s", {
                f"team_id{suffix}": async_deletion.team_id,
                f"key{suffix}": key,
            }
        else:
            key, version = async_deletion.key.split("_")
            return (
                f"team_id = %(team_id{suffix})s AND {self._column_name(async_deletion)} = %(key{suffix})s AND version < %(version{suffix})s",
                {f"team_id{suffix}": async_deletion.team_id, f"version{suffix}": version, f"key{suffix}": key},
            )
