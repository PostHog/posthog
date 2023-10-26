from typing import Any, Dict, List, Set, Tuple

from posthog.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger


class AsyncCohortDeletion(AsyncDeletionProcess):
    DELETION_TYPES = [DeletionType.Cohort_full, DeletionType.Cohort_stale]

    def process(self, deletions: List[AsyncDeletion]):
        if len(deletions) == 0:
            logger.warn("No AsyncDeletion for cohorts to perform")
            return

        logger.warn(
            "Starting AsyncDeletion on `cohortpeople` table in ClickHouse",
            {
                "count": len(deletions),
                "team_ids": list(set(row.team_id for row in deletions)),
            },
        )

        conditions, args = self._conditions(deletions)

        sync_execute(
            f"""
            DELETE FROM cohortpeople
            WHERE {" OR ".join(conditions)}
            """,
            args,
        )

    def _verify_by_group(self, deletion_type: int, async_deletions: List[AsyncDeletion]) -> List[AsyncDeletion]:
        if deletion_type == DeletionType.Cohort_stale or deletion_type == DeletionType.Cohort_full:
            cohort_ids_with_data = self._verify_by_column("team_id, cohort_id", async_deletions)
            return [
                row for row in async_deletions if (row.team_id, int(row.key.split("_")[0])) not in cohort_ids_with_data
            ]
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
