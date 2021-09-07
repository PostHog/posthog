from typing import Optional, Union

from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter


class ClickhousePersonQuery:
    PERSON_PROPERTIES_ALIAS = "person_props"

    _filter: Union[Filter, PathFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer

    def __init__(
        self, filter: Union[Filter, PathFilter], team_id: int, column_optimizer: Optional[ColumnOptimizer] = None
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)

    def get_query(self) -> str:
        fields = (
            "id"
            + (
                f", argMax(properties, _timestamp) AS {self.PERSON_PROPERTIES_ALIAS}"
                if self._column_optimizer.should_query_person_properties_column
                else ""
            )
            + " ".join(
                f", argMax({column_name}, _timestamp) as {column_name}"
                for column_name in self._column_optimizer.materialized_person_columns_to_query
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
