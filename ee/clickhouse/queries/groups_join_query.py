from typing import Optional, Union

from posthog.schema import PersonsOnEventsMode

from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.queries.util import PersonPropertiesMode, alias_poe_mode_for_legacy

from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer


class GroupsJoinQuery:
    """
    Query class responsible for joining with `groups` clickhouse table based on filters
    """

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
    _team_id: int
    _column_optimizer: EnterpriseColumnOptimizer

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter],
        team_id: int,
        column_optimizer: Optional[EnterpriseColumnOptimizer] = None,
        join_key: Optional[str] = None,
        person_on_events_mode: PersonsOnEventsMode = PersonsOnEventsMode.DISABLED,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or EnterpriseColumnOptimizer(self._filter, self._team_id)
        self._join_key = join_key
        self._person_on_events_mode = alias_poe_mode_for_legacy(person_on_events_mode)

    def get_join_query(self) -> tuple[str, dict]:
        join_queries, params = [], {}

        for group_type_index in self._column_optimizer.group_types_to_query:
            var = f"group_index_{group_type_index}"
            group_join_key = self._join_key or f'"$group_{group_type_index}"'
            join_queries.append(
                f"""
                LEFT JOIN (
                    SELECT
                        group_key,
                        argMax(group_properties, _timestamp) AS group_properties_{group_type_index}
                    FROM groups
                    WHERE team_id = %(team_id)s AND group_type_index = %({var})s
                    GROUP BY group_key
                ) groups_{group_type_index}
                ON {group_join_key} == groups_{group_type_index}.group_key
                """
            )

            params["team_id"] = self._team_id
            params[var] = group_type_index

        return "\n".join(join_queries), params

    def get_filter_query(self, group_type_index: GroupTypeIndex) -> tuple[str, dict]:
        var = f"group_index_{group_type_index}"
        params = {
            "team_id": self._team_id,
            var: group_type_index,
        }

        aggregated_group_filters, filter_params = parse_prop_grouped_clauses(
            self._team_id,
            self._filter.property_groups,
            prepend=f"group_properties_{group_type_index}",
            has_person_id_joined=False,
            group_properties_joined=True,
            person_properties_mode=PersonPropertiesMode.DIRECT,
            _top_level=True,
            hogql_context=self._filter.hogql_context,
        )

        params.update(filter_params)

        query = f"""
            SELECT
                group_key,
                argMax(group_properties, _timestamp) AS group_properties_{group_type_index}
            FROM groups
            WHERE team_id = %(team_id)s AND group_type_index = %({var})s
            GROUP BY group_key
            HAVING 1=1
            {aggregated_group_filters}
        """
        return query, params
