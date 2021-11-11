from typing import Dict, List, Optional, Set, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.property import extract_tables_and_properties, prop_filter_json_extract
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from posthog.models import Filter
from posthog.models.entity import Entity
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.property import Property


class GroupsJoinQuery:
    """
    Query class responsible for joining with `groups` clickhouse table based on filters
    """

    _filter: Union[Filter, PathFilter, RetentionFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)

    def get_join_query(self, group_join_keys: Optional[List[str]] = None) -> Tuple[str, Dict]:
        join_queries, params = [], {}

        if group_join_keys:
            assert len(group_join_keys) == len(self._column_optimizer.group_types_to_query)
        else:
            group_join_keys = [f"$group_{index}" for index in self._column_optimizer.group_types_to_query]

        for group_type_index, group_type_join_key in zip(self._column_optimizer.group_types_to_query, group_join_keys):
            var = f"group_index_{group_type_index}"
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
                ON {group_type_join_key} == groups_{group_type_index}.group_key
                """
            )

            params["team_id"] = self._team_id
            params[var] = group_type_index

        return "\n".join(join_queries), params
