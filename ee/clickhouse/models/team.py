from typing import List

import structlog

from ee.clickhouse.sql.events import EVENTS_DATA_TABLE
from posthog.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER

logger = structlog.get_logger(__name__)

# Note: Session recording, dead letter queue, logs deletion will be handled by TTL
TABLES_TO_DELETE_FROM = lambda: [
    EVENTS_DATA_TABLE(),
    "person",
    "person_distinct_id",
    "person_distinct_id2",
    "groups",
    "cohortpeople",
    "person_static_cohort",
]


def delete_teams_data(team_ids: List[int]):
    logger.info(
        f"Deleting teams data from clickhouse using background mutations.",
        team_ids=team_ids,
        tables=TABLES_TO_DELETE_FROM(),
    )
    for table in TABLES_TO_DELETE_FROM():
        sync_execute(
            f"ALTER TABLE {table} ON CLUSTER '{CLICKHOUSE_CLUSTER}' DELETE WHERE team_id IN %(team_ids)s",
            {"team_ids": team_ids},
        )
