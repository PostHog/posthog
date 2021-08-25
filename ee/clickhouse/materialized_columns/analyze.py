import re
from collections import defaultdict
from typing import Dict, Generator, List, Optional, Set, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.util import instance_memoize
from ee.clickhouse.sql.person import GET_PERSON_PROPERTIES_COUNT
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.property import PropertyName, TableWithProperties
from posthog.models.property_definition import PropertyDefinition
from posthog.models.team import Team

Suggestion = Dict

INSPECT_QUERY_THRESHOLD_MS = 5000


class TeamManager:
    @instance_memoize
    def person_properties(self, team_id: str) -> Set[str]:
        rows = sync_execute(GET_PERSON_PROPERTIES_COUNT, {"team_id": team_id})
        return set(name for name, _ in rows)

    @instance_memoize
    def event_properties(self, team_id: str) -> Set[str]:
        return set(PropertyDefinition.objects.filter(team_id=team_id).values_list("name", flat=True))


class Query:
    def __init__(self, query_string: str, query_time_ms: float):
        self.query_string = query_string
        self.query_time_ms = query_time_ms

    @property
    def cost(self) -> int:
        return int((self.query_time_ms - INSPECT_QUERY_THRESHOLD_MS) / 1000) + 1

    @cached_property
    def is_valid(self):
        return self.team_id is not None and Team.objects.filter(pk=self.team_id).exists()

    @cached_property
    def team_id(self) -> Optional[str]:
        matches = re.findall(r"team_id = (\d+)", self.query_string)
        return matches[0] if matches else None

    @cached_property
    def _all_properties(self) -> List[PropertyName]:
        return re.findall(r"JSONExtract\w+\(\S+, '([^']+)'\)", self.query_string)

    def properties(self, team_manager: TeamManager) -> Generator[Tuple[TableWithProperties, PropertyName], None, None]:
        # Reverse-engineer whether a property is an "event" or "person" property by getting their event definitions.
        person_props = team_manager.person_properties(self.team_id)
        event_props = team_manager.event_properties(self.team_id)
        for property in self._all_properties:
            if property in person_props:
                yield "person", property
            if property in event_props:
                yield "events", property


def get_queries(since_hours_ago):
    raw_queries = sync_execute(
        f"""
        SELECT
            query,
            query_duration_ms
        FROM system.query_log
        WHERE
            query NOT LIKE '%%query_log%%'
            AND query LIKE '/* request:%%'
            AND query NOT LIKE '%%INSERT%%'
            AND type = 'QueryFinish'
            AND query_start_time > now() - toIntervalHour(%(since)s)
            AND query_duration_ms > {INSPECT_QUERY_THRESHOLD_MS}
        ORDER BY query_duration_ms desc
        """,
        {"since": since_hours_ago},
    )
    return [Query(query, query_duration_ms) for query, query_duration_ms in raw_queries]


def analyze(queries: List[Query]) -> List[Suggestion]:
    team_manager = TeamManager()
    costs: defaultdict = defaultdict(int)

    for query in queries:
        if not query.is_valid:
            continue

        for table, property in query.properties(team_manager):
            costs[(table, property)] += query.cost

    return list(sorted(costs.items(), key=lambda kv: -kv[1]))  # type: ignore


if __name__ == "__main__":
    print(analyze(get_queries(120)))
