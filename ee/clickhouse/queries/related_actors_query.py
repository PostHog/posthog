from datetime import timedelta
from functools import cached_property
from typing import Optional, Union

from django.utils.timezone import now

from posthog.schema import ProductKey

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, tag_queries
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

    def run(self) -> list[SerializedActor]:
        tag_queries(product=ProductKey.PRODUCT_ANALYTICS, feature=Feature.QUERY)
        results: list[SerializedActor] = []
        results.extend(self._query_related_people())

        group_type_indexes = list(
            GroupTypeMapping.objects.filter(project_id=self.team.project_id)
            .exclude(group_type_index=self.group_type_index)
            .order_by("group_type_index")
            .values_list("group_type_index", flat=True)
        )

        results.extend(self._query_related_groups(group_type_indexes=group_type_indexes))
        return results

    def _query_related_people(self) -> list[SerializedPerson]:
        if not self.is_aggregating_by_groups:
            return []
        tag_queries(name="related-people")
        person_ids = self._query_related_people_ids()
        return get_serialized_people(self.team, person_ids)

    def _query_related_people_ids(self) -> list:
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

    def _query_related_groups(self, group_type_indexes: list[int]) -> list:
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

    @cached_property
    def _params(self):
        return {
            "team_id": self.team.pk,
            "id": self.id,
            "after": (now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "before": now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        }
