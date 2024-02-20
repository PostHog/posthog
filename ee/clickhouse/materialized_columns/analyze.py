import re
from datetime import timedelta
from typing import Dict, Generator, List, Optional, Set, Tuple

import structlog

from ee.clickhouse.materialized_columns.columns import (
    DEFAULT_TABLE_COLUMN,
    backfill_materialized_columns,
    get_materialized_columns,
    materialize,
)
from ee.settings import (
    MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS,
    MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS,
    MATERIALIZE_COLUMNS_MAX_AT_ONCE,
    MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
)
from posthog.cache_utils import instance_memoize
from posthog.client import sync_execute
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.person.sql import (
    GET_EVENT_PROPERTIES_COUNT,
    GET_PERSON_PROPERTIES_COUNT,
)
from posthog.models.property import PropertyName, TableColumn, TableWithProperties
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team import Team

Suggestion = Tuple[TableWithProperties, TableColumn, PropertyName]

logger = structlog.get_logger(__name__)


class TeamManager:
    @instance_memoize
    def person_properties(self, team_id: str) -> Set[str]:
        return self._get_properties(GET_PERSON_PROPERTIES_COUNT, team_id)

    @instance_memoize
    def event_properties(self, team_id: str) -> Set[str]:
        return set(
            PropertyDefinition.objects.filter(team_id=team_id, type=PropertyDefinition.Type.EVENT).values_list(
                "name", flat=True
            )
        )

    @instance_memoize
    def person_on_events_properties(self, team_id: str) -> Set[str]:
        return self._get_properties(GET_EVENT_PROPERTIES_COUNT.format(column_name="person_properties"), team_id)

    @instance_memoize
    def group_on_events_properties(self, group_type_index: int, team_id: str) -> Set[str]:
        return self._get_properties(
            GET_EVENT_PROPERTIES_COUNT.format(column_name=f"group{group_type_index}_properties"),
            team_id,
        )

    def _get_properties(self, query, team_id) -> Set[str]:
        rows = sync_execute(query, {"team_id": team_id})
        return set(name for name, _ in rows)


class Query:
    def __init__(
        self,
        query_string: str,
        query_time_ms: float,
        min_query_time=MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
    ):
        self.query_string = query_string
        self.query_time_ms = query_time_ms
        self.min_query_time = min_query_time

    @property
    def cost(self) -> int:
        return int((self.query_time_ms - self.min_query_time) / 1000) + 1

    @cached_property
    def is_valid(self):
        return self.team_id is not None and Team.objects.filter(pk=self.team_id).exists()

    @cached_property
    def team_id(self) -> Optional[str]:
        matches = re.findall(r"team_id = (\d+)", self.query_string)
        return matches[0] if matches else None

    @cached_property
    def _all_properties(self) -> List[Tuple[str, PropertyName]]:
        return re.findall(r"JSONExtract\w+\((\S+), '([^']+)'\)", self.query_string)

    def properties(
        self, team_manager: TeamManager
    ) -> Generator[Tuple[TableWithProperties, TableColumn, PropertyName], None, None]:
        # Reverse-engineer whether a property is an "event" or "person" property by getting their event definitions.
        # :KLUDGE: Note that the same property will be found on both tables if both are used.
        # We try to hone in on the right column by looking at the column from which the property is extracted.
        person_props = team_manager.person_properties(self.team_id)
        event_props = team_manager.event_properties(self.team_id)
        person_on_events_props = team_manager.person_on_events_properties(self.team_id)
        group0_props = team_manager.group_on_events_properties(0, self.team_id)
        group1_props = team_manager.group_on_events_properties(1, self.team_id)
        group2_props = team_manager.group_on_events_properties(2, self.team_id)
        group3_props = team_manager.group_on_events_properties(3, self.team_id)
        group4_props = team_manager.group_on_events_properties(4, self.team_id)

        for table_column, property in self._all_properties:
            if property in event_props:
                yield "events", DEFAULT_TABLE_COLUMN, property
            if property in person_props:
                yield "person", DEFAULT_TABLE_COLUMN, property

            if property in person_on_events_props and "person_properties" in table_column:
                yield "events", "person_properties", property
            if property in group0_props and "group0_properties" in table_column:
                yield "events", "group0_properties", property
            if property in group1_props and "group1_properties" in table_column:
                yield "events", "group1_properties", property
            if property in group2_props and "group2_properties" in table_column:
                yield "events", "group2_properties", property
            if property in group3_props and "group3_properties" in table_column:
                yield "events", "group3_properties", property
            if property in group4_props and "group4_properties" in table_column:
                yield "events", "group4_properties", property


def _analyze(since_hours_ago: int, min_query_time: int) -> List[Suggestion]:
    "Finds columns that should be materialized"

    raw_queries = sync_execute(
        """
WITH
    {min_query_time} as slow_query_minimum,
    (
        159, -- TIMEOUT EXCEEDED
        160, -- TOO SLOW (estimated query execution time)
    ) as exception_codes,
    20 * 1000 * 1000 * 1000 as min_bytes_read,
    5000000 as min_read_rows
SELECT
    arrayJoin(
        extractAll(query, 'JSONExtract[a-zA-Z0-9]*?\\((?:[a-zA-Z0-9\\`_-]+\\.)?(.*?), .*?\\)')
    ) as column,
    arrayJoin(extractAll(query, 'JSONExtract[a-zA-Z0-9]*?\\(.*?, \\'(.*?)\\'\\)')) as prop_to_materialize
    --,groupUniqArrayIf(JSONExtractInt(log_comment, 'team_id'), type > 2),
    --count(),
    --countIf(type > 2) as failures,
    --countIf(query_duration_ms > 3000) as slow_query,
    --formatReadableSize(avg(read_bytes)),
    --formatReadableSize(max(read_bytes))
FROM
    clusterAllReplicas(posthog, system, query_log)
WHERE
    query_start_time > now() - toIntervalHour({since})
    and query LIKE '%JSONExtract%'
    and query not LIKE '%JSONExtractKeysAndValuesRaw(group_properties)%'
    and type > 1
    and is_initial_query
    and JSONExtractString(log_comment, 'access_method') != 'personal_api_key' -- API requests failing is less painful than queries in the interface
    and JSONExtractString(log_comment, 'kind') != 'celery'
    and JSONExtractInt(log_comment, 'team_id') != 0
    and query not like '%person_distinct_id2%' -- Old style person properties that are joined, no need to optimize those queries
    and column IN ('properties', 'person_properties', 'group0_properties', 'group1_properties', 'group2_properties', 'group3_properties', 'group4_properties')
    and read_bytes > min_bytes_read
    and (exception_code IN exception_codes OR query_duration_ms > slow_query_minimum)
    and read_rows > min_read_rows
GROUP BY
    1, 2
HAVING
    countIf(exception_code IN exception_codes) > 0 OR countIf(query_duration_ms > slow_query_minimum) > 9
ORDER BY
    countIf(exception_code IN exception_codes) DESC,
    countIf(query_duration_ms > slow_query_minimum) DESC
LIMIT 100 -- Make sure we don't add 100s of columns in one run
        """.format(since=since_hours_ago, min_query_time=min_query_time),
    )

    return [("events", table_column, property_name) for (table_column, property_name) in raw_queries]


def materialize_properties_task(
    columns_to_materialize: Optional[List[Suggestion]] = None,
    time_to_analyze_hours: int = MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS,
    maximum: int = MATERIALIZE_COLUMNS_MAX_AT_ONCE,
    min_query_time: int = MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
    backfill_period_days: int = MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS,
    dry_run: bool = False,
) -> None:
    """
    Creates materialized columns for event and person properties based off of slow queries
    """

    if columns_to_materialize is None:
        columns_to_materialize = _analyze(time_to_analyze_hours, min_query_time)
    result = []
    for suggestion in columns_to_materialize:
        table, table_column, property_name = suggestion
        if (property_name, table_column) not in get_materialized_columns(table):
            result.append(suggestion)

    if len(result) > 0:
        logger.info(f"Calculated columns that could be materialized. count={len(result)}")
    else:
        logger.info("Found no columns to materialize.")

    properties: Dict[TableWithProperties, List[Tuple[PropertyName, TableColumn]]] = {
        "events": [],
        "person": [],
    }
    for table, table_column, property_name in result[:maximum]:
        logger.info(f"Materializing column. table={table}, property_name={property_name}")

        if not dry_run:
            materialize(table, property_name, table_column=table_column)
        properties[table].append((property_name, table_column))

    if backfill_period_days > 0 and not dry_run:
        logger.info(f"Starting backfill for new materialized columns. period_days={backfill_period_days}")
        backfill_materialized_columns("events", properties["events"], timedelta(days=backfill_period_days))
        backfill_materialized_columns("person", properties["person"], timedelta(days=backfill_period_days))
