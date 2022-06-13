from typing import Any, List

import structlog

from posthog.client import sync_execute
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.person import Person, PersonDistinctId
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
    "plugin_log_entries",
]


def delete_bulky_postgres_data(team_ids: List[int]):
    "Efficiently delete large tables for teams from postgres. Using normal CASCADE delete here can time out"
    _raw_delete(PersonDistinctId.objects.filter(team_id__in=team_ids))
    _raw_delete(Person.objects.filter(team_id__in=team_ids))


def _raw_delete(queryset: Any):
    "Issues a single DELETE statement for the queryset"
    queryset._raw_delete(queryset.db)


def delete_teams_clickhouse_data(team_ids: List[int]):
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
