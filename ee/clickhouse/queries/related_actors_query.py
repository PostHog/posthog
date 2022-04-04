from datetime import timedelta
from functools import cached_property
from typing import List, Optional, Union

from django.utils.timezone import now

from ee.clickhouse.queries.actor_base_query import (
    SerializedActor,
    SerializedGroup,
    SerializedPerson,
    get_groups,
    get_people,
)
from posthog.client import sync_execute
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import GroupTypeIndex
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query


class RelatedActorsQuery:
    DISTINCT_ID_TABLE_ALIAS = "pdi"

    """
    This query calculates other groups and persons that are related to a person or a group.

    Two actors are considered related if they have had shared events in the past 90 days.
    """

    def __init__(self, team_id: int, group_type_index: Optional[Union[GroupTypeIndex, str]], id: str):
        self.team_id = team_id
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)
        self.id = id

    def run(self) -> List[SerializedActor]:
        results: List[SerializedActor] = []
        results.extend(self._query_related_people())
        for group_type_mapping in GroupTypeMapping.objects.filter(team_id=self.team_id):
            results.extend(self._query_related_groups(group_type_mapping.group_type_index))
        return results

    @property
    def is_aggregating_by_groups(self) -> bool:
        return self.group_type_index is not None

    def _query_related_people(self) -> List[SerializedPerson]:
        if not self.is_aggregating_by_groups:
            return []

        # :KLUDGE: We need to fetch distinct_id + person properties to be able to link to user properly.
        person_ids = self._take_first(
            sync_execute(
                f"""
            SELECT DISTINCT {self.DISTINCT_ID_TABLE_ALIAS}.person_id
            FROM events e
            {self._distinct_ids_join}
            WHERE team_id = %(team_id)s
              AND timestamp > %(after)s
              AND timestamp < %(before)s
              AND {self._filter_clause}
            """,
                self._params,
            )
        )

        _, serialized_people = get_people(self.team_id, person_ids)
        return serialized_people

    def _query_related_groups(self, group_type_index: GroupTypeIndex) -> List[SerializedGroup]:
        if group_type_index == self.group_type_index:
            return []

        group_ids = self._take_first(
            sync_execute(
                f"""
            SELECT DISTINCT $group_{group_type_index} AS group_key
            FROM events e
            {'' if self.is_aggregating_by_groups else self._distinct_ids_join}
            JOIN (
                SELECT group_key
                FROM groups
                WHERE team_id = %(team_id)s AND group_type_index = %(group_type_index)s
                GROUP BY group_key
            ) groups ON $group_{group_type_index} = groups.group_key
            WHERE team_id = %(team_id)s
              AND timestamp > %(after)s
              AND timestamp < %(before)s
              AND group_key != ''
              AND {self._filter_clause}
            ORDER BY group_key
            """,
                {**self._params, "group_type_index": group_type_index},
            )
        )

        _, serialize_groups = get_groups(self.team_id, group_type_index, group_ids)
        return serialize_groups

    def _take_first(self, rows: List) -> List:
        return [row[0] for row in rows]

    @property
    def _filter_clause(self):
        if self.is_aggregating_by_groups:
            return f"$group_{self.group_type_index} = %(id)s"
        else:
            return f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id = %(id)s"

    @property
    def _distinct_ids_join(self):
        return f"JOIN ({get_team_distinct_ids_query(self.team_id)}) {self.DISTINCT_ID_TABLE_ALIAS} on e.distinct_id = {self.DISTINCT_ID_TABLE_ALIAS}.distinct_id"

    @cached_property
    def _params(self):
        return {
            "team_id": self.team_id,
            "id": self.id,
            "after": (now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "before": now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        }
