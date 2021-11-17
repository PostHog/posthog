from typing import Dict, List, Optional, Set, Tuple, Union

from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.property import GroupTypeIndex


class GroupsJoinQuery:
    """
    Query class responsible for joining with `groups` clickhouse table based on filters
    """

    _filter: Union[Filter, PathFilter, RetentionFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _additional_group_types: Set[GroupTypeIndex]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
        join_key: Optional[str] = None,
        additional_group_types: Set[GroupTypeIndex] = set(),
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)
        self._join_key = join_key
        self._additional_group_types = additional_group_types

    def get_join_query(self) -> Tuple[str, Dict]:
        join_queries, params = [], {}

        all_group_types = self._column_optimizer.group_types_to_query | self._additional_group_types

        for group_type_index in all_group_types:
            var = f"group_index_{group_type_index}"
            group_join_key = self._join_key or f"$group_{group_type_index}"
            join_queries.append(
                f"""
                INNER JOIN (
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
