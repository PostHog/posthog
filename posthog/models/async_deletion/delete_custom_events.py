from clickhouse_driver.errors import SocketTimeoutError
from prometheus_client import Counter

from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.async_deletion.delete import AsyncDeletionProcess, logger
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER


logger.setLevel("DEBUG")

deletions_counter = Counter("custom_deletions_executed", "Total number of custom deletions sent to clickhouse")

MAX_QUERY_SIZE = 230_000  # 230KB which is less than 256KB limit in ClickHouse
MAX_SELECT_EXECUTION_TIME = 1 * 60 * 60  # 1 hour(s)


class AsyncCustomEventDeletion(AsyncDeletionProcess):
    DELETION_TYPES = [DeletionType.Custom]

    def process(self, deletions: list[AsyncDeletion]):
        deletions_counter.inc(len(deletions))

        if len(deletions) == 0:
            logger.debug("No AsyncDeletion to perform")
            return

        team_ids = list({row.team_id for row in deletions})

        logger.info(
            "Starting AsyncDeletion on `events` table in ClickHouse for custom predicates",
            {
                "count": len(deletions),
                "team_ids": team_ids,
            },
        )

        # Process each deletion separately since each has a unique predicate
        for deletion in deletions:
            try:
                query = f"""
                    DELETE FROM sharded_events ON CLUSTER '{CLICKHOUSE_CLUSTER}'
                    WHERE team_id = %(team_id)s AND ({deletion.key})
                """

                logger.debug(
                    f"Executing custom deletion query for team {deletion.team_id} with predicate: {deletion.key}"
                )

                sync_execute(
                    query,
                    {"team_id": deletion.team_id},
                    settings={},
                )
            except SocketTimeoutError:
                # This is unfortunately needed because currently all lightweight deletes are executed sync
                logger.warning(
                    f"ClickHouse query timed out during async custom deletion for team {deletion.team_id}. This is expected.",
                    exc_info=True,
                )
            except Exception as e:
                logger.error(
                    f"Error executing custom deletion for team {deletion.team_id}: {str(e)}",
                    exc_info=True,
                )

    def _verify_by_group(self, deletion_type: int, async_deletions: list[AsyncDeletion]) -> list[AsyncDeletion]:
        if deletion_type != DeletionType.Custom:
            return []

        verified_deletions = []

        for deletion in async_deletions:
            try:
                # Check if any events still exist matching the custom predicate
                result = sync_execute(
                    f"""
                    SELECT count() as count
                    FROM events
                    WHERE team_id = %(team_id)s AND ({deletion.key})
                    LIMIT 1
                    """,
                    {"team_id": deletion.team_id},
                    settings={"max_execution_time": MAX_SELECT_EXECUTION_TIME},
                )

                # If no events found, the deletion is verified
                if result and result[0][0] == 0:
                    verified_deletions.append(deletion)
                else:
                    logger.debug(
                        f"Custom deletion not yet complete for team {deletion.team_id}, "
                        f"found {result[0][0] if result else 'unknown'} remaining events"
                    )

            except Exception as e:
                logger.error(
                    f"Error verifying custom deletion for team {deletion.team_id}: {str(e)}",
                    exc_info=True,
                )

        return verified_deletions

    def _condition(self, async_deletion: AsyncDeletion, suffix: str) -> tuple[str, dict]:
        # This method is not used for custom deletions since we handle each deletion separately
        # in the process method, but we need to implement it to satisfy the interface
        return (
            f"(team_id = %(team_id{suffix})s AND ({async_deletion.key}))",
            {f"team_id{suffix}": async_deletion.team_id},
        )
