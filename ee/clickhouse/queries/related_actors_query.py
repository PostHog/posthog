from datetime import timedelta
from functools import cached_property
from typing import Optional, Union

from django.utils.timezone import now

import posthoganalytics

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import tag_queries
from posthog.models import Team
from posthog.models.filters.utils import validate_group_type_index
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.property import GroupTypeIndex
from posthog.queries.actor_base_query import (
    SerializedActor,
    SerializedGroup,
    SerializedPerson,
    get_groups,
    get_serialized_people,
)
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query


class RelatedActorsQuery:
    DISTINCT_ID_TABLE_ALIAS = "pdi"

    """
    This query calculates other groups and persons that are related to a person or a group.

    Two actors are considered related if they have had shared events in the past 90 days.
    """

    def __init__(
        self,
        team: Team,
        group_type_index: Optional[Union[GroupTypeIndex, str]],
        id: str,
    ):
        self.team = team
        self.group_type_index = validate_group_type_index("group_type_index", group_type_index)
        self.id = id

    @property
    def is_aggregating_by_groups(self) -> bool:
        return self.group_type_index is not None

    def run(self, variant: str = "control") -> list[SerializedActor]:
        results: list[SerializedActor] = []
        results.extend(self._query_related_people())

        group_type_indexes = list(
            GroupTypeMapping.objects.filter(project_id=self.team.project_id)
            .exclude(group_type_index=self.group_type_index)
            .values_list("group_type_index", flat=True)
        )

        if variant == "test":
            tag_queries(name="optimized-related-groups-test")
            results.extend(self._query_related_groups_optimized(group_type_indexes=group_type_indexes))
        else:
            tag_queries(name="optimized-related-groups-control")
            for index in group_type_indexes:
                results.extend(self._query_related_groups_control(index))
        return results

    def _is_test_variant(self) -> bool:
        flag_result = posthoganalytics.get_feature_flag(
            "optimized-related-people-query",
            str(self.team.uuid),
            groups={"organization": str(self.team.organization.id), "project": str(self.team.uuid)},
        )
        return flag_result == "test"  # type: ignore[comparison-overlap]

    def _query_related_people(self) -> list[SerializedPerson]:
        if not self.is_aggregating_by_groups:
            return []

        if self._is_test_variant():
            tag_queries(name="optimized-related-people-test")
            person_ids = self._query_related_people_optimized()
        else:
            tag_queries(name="optimized-related-people-control")
            person_ids = self._query_related_people_control()

        return get_serialized_people(self.team, person_ids)

    def _query_related_people_control(self) -> list:
        # :KLUDGE: We need to fetch distinct_id + person properties to be able to link to user properly.
        return self._take_first(
            # nosemgrep: clickhouse-injection-taint - internal SQL fragments, values parameterized
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

    def _query_related_people_optimized(self) -> list:
        return self._take_first(
            # nosemgrep: clickhouse-injection-taint - internal SQL fragments, values parameterized
            sync_execute(
                f"""
            SELECT DISTINCT argMax(person_id, version) AS person_id
            FROM person_distinct_id2
            WHERE team_id = %(team_id)s
              AND distinct_id IN (
                  SELECT distinct_id
                  FROM events
                  WHERE team_id = %(team_id)s
                    AND timestamp > %(after)s
                    AND timestamp < %(before)s
                    AND {self._filter_clause}
            )
            GROUP BY distinct_id
            HAVING argMax(is_deleted, version) = 0
            """,
                self._params,
            )
        )

    def _query_related_groups_control(self, group_type_index: GroupTypeIndex) -> list:
        group_ids = self._take_first(
            # nosemgrep: clickhouse-injection-taint, clickhouse-fstring-param-audit - internal SQL fragments, values parameterized
            sync_execute(
                f"""
            SELECT DISTINCT $group_{group_type_index} AS group_key
            FROM events e
            {"" if self.is_aggregating_by_groups else self._distinct_ids_join}
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
        _, serialized_groups = get_groups(self.team.pk, group_type_index, group_ids)
        return serialized_groups

    def _query_related_groups_optimized(self, group_type_indexes: list[int]) -> list:
        if not list(group_type_indexes):
            return []

        array_join_tuples = ", ".join(f"(toUInt8({index}), e.$group_{index})" for index in group_type_indexes)
        query = f"""
                SELECT DISTINCT group_type_index, group_key
                FROM groups
                WHERE team_id = %(team_id)s
                  AND group_type_index IN {list(group_type_indexes)}
                  AND (group_type_index, group_key) IN (
                      SELECT tuples.1 AS group_type_index, tuples.2 AS group_key
                      FROM events e
                      ARRAY JOIN arrayFilter(x -> x.2 != '', [{array_join_tuples}]) AS tuples
                      WHERE team_id = %(team_id)s
                        AND e.timestamp > %(after)s
                        AND e.timestamp < %(before)s
                        AND {f"e.$group_{self.group_type_index} = %(id)s" if self.is_aggregating_by_groups else f"e.person_id = %(id)s"}
                  )
                ORDER BY group_type_index, group_key
                """
        # nosemgrep: clickhouse-injection-taint - group_type_indexes are ints from DB, values parameterized
        results = sync_execute(query, self._params)
        if not results:
            return []

        serialized_results: list[SerializedGroup] = []
        for index in group_type_indexes:
            group_keys = [result[1] for result in results if result[0] == index]
            _, serialized_groups = get_groups(self.team.pk, index, group_keys)
            serialized_results.extend(serialized_groups)

        return serialized_results

    def _take_first(self, rows: list) -> list:
        return [row[0] for row in rows]

    @property
    def _filter_clause(self):
        if self.is_aggregating_by_groups:
            return f"$group_{self.group_type_index} = %(id)s"
        else:
            return f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id = %(id)s"

    @property
    def _distinct_ids_join(self):
        return f"JOIN ({get_team_distinct_ids_query(self.team.pk)}) {self.DISTINCT_ID_TABLE_ALIAS} on e.distinct_id = {self.DISTINCT_ID_TABLE_ALIAS}.distinct_id"

    @cached_property
    def _params(self):
        return {
            "team_id": self.team.pk,
            "id": self.id,
            "after": (now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "before": now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        }
