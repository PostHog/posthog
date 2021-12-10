import json
from datetime import timedelta
from functools import cached_property
from typing import Dict, List, Literal, Optional, TypedDict, Union

from django.utils.timezone import now

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import GroupTypeIndex


class RelatedActorsResponse(TypedDict):
    type: Literal["person", "group"]
    group_type_index: Optional[GroupTypeIndex]
    id: str
    person: Optional[Dict]


class RelatedActorsQuery:
    """
    This query calculates other groups and persons that are related to a person or a group.

    Two actors are considered related if they have had shared events in the past 90 days.
    """

    def __init__(self, team_id: int, group_type_index: Optional[Union[GroupTypeIndex, str]], id: str):
        self.team_id = team_id
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)
        self.id = id

    def run(self) -> List[RelatedActorsResponse]:
        results = self._query_related_people()
        for group_type_mapping in GroupTypeMapping.objects.filter(team_id=self.team_id):
            results.extend(self._query_related_groups(group_type_mapping.group_type_index))
        return results

    @property
    def is_aggregating_by_groups(self) -> bool:
        return self.group_type_index is not None

    def _query_related_people(self) -> List[RelatedActorsResponse]:
        if not self.is_aggregating_by_groups:
            return []

        # :KLUDGE: We need to fetch distinct_id + person properties to be able to link to user properly.
        rows = sync_execute(
            f"""
            SELECT person_id, any(e.distinct_id), any(person_props)
            FROM events e
            {self._distinct_ids_join}
            JOIN (
                SELECT id, any(properties) as person_props
                FROM person
                WHERE team_id = %(team_id)s
                GROUP BY id
                HAVING max(is_deleted) = 0
            ) person ON pdi.person_id = person.id
            WHERE team_id = %(team_id)s
              AND timestamp > %(after)s
              AND timestamp < %(before)s
              AND {self._filter_clause}
            GROUP BY person_id
            """,
            self._params,
        )

        return [
            RelatedActorsResponse(
                type="person",
                group_type_index=None,
                id=person_id,
                person={"distinct_ids": [distinct_id], "properties": json.loads(person_props)},
            )
            for (person_id, distinct_id, person_props) in rows
        ]

    def _query_related_groups(self, group_type_index: GroupTypeIndex) -> List[RelatedActorsResponse]:
        if group_type_index == self.group_type_index:
            return []

        rows = sync_execute(
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
        return [
            RelatedActorsResponse(type="group", group_type_index=group_type_index, id=group_key, person=None)
            for (group_key,) in rows
        ]

    @property
    def _filter_clause(self):
        if self.is_aggregating_by_groups:
            return f"$group_{self.group_type_index} = %(id)s"
        else:
            return "person_id = %(id)s"

    @property
    def _distinct_ids_join(self):
        return f"JOIN ({get_team_distinct_ids_query(self.team_id)}) pdi on e.distinct_id = pdi.distinct_id"

    @cached_property
    def _params(self):
        return {
            "team_id": self.team_id,
            "id": self.id,
            "after": (now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "before": now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        }
