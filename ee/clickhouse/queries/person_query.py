from typing import List, Optional, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter


class ClickhousePersonQuery:
    PERSON_PROPERTIES_ALIAS = "person_props"
    ALIASES = {"properties": "person_props"}

    _filter: Union[Filter, PathFilter, RetentionFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _extra_fields: List[ColumnName]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
        extra_fields: List[ColumnName] = [],
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)
        self._extra_fields = extra_fields

    def get_query(self) -> str:
        fields = (
            "id"
            + (
                f", argMax(properties, _timestamp) AS {self.PERSON_PROPERTIES_ALIAS}"
                if self._column_optimizer.should_query_person_properties_column
                or self.PERSON_PROPERTIES_ALIAS in self._extra_fields
                else ""
            )
            + " ".join(
                f", argMax({column_name}, _timestamp) as {column_name}"
                for column_name in self._column_optimizer.materialized_person_columns_to_query
            )
            + " ".join(
                f", argMax({column_name}, _timestamp) as {self.ALIASES.get(column_name, column_name)}"
                for column_name in set(self._extra_fields) - {self.PERSON_PROPERTIES_ALIAS}
            )
        )

        return f"""
            SELECT {fields}
            FROM person
            WHERE team_id = %(team_id)s
            GROUP BY id
            HAVING max(is_deleted) = 0
        """

    @property
    def is_used(self):
        "Returns whether properties or any other columns are actually being queried"
        return (
            self._column_optimizer.should_query_person_properties_column
            or len(self._column_optimizer.materialized_person_columns_to_query) > 0
        )
