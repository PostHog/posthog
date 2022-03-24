from typing import Dict, Optional, Tuple, Union

from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer
from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter


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
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or EnterpriseColumnOptimizer(self._filter, self._team_id)
        self._join_key = join_key

    def get_join_query(self) -> Tuple[str, Dict]:
        join_queries, params = [], {}

        for group_type_index in self._column_optimizer.group_types_to_query:
            var = f"group_index_{group_type_index}"
            group_join_key = self._join_key or f'"$group_{group_type_index}"'
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
