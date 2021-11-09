from typing import Dict, List, Optional, Set, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.property import extract_tables_and_properties, prop_filter_json_extract
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from posthog.models import Filter
from posthog.models.entity import Entity
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.property import Property


class ClickhousePersonQuery:
    """
    Query class responsible for joining with `person` clickhouse table

    For sake of performance, this class:
    - Tries to do as much person property filtering as possible here
    - Minimizes the amount of columns read
    """

    PERSON_PROPERTIES_ALIAS = "person_props"
    ALIASES = {"properties": "person_props"}

    _filter: Union[Filter, PathFilter, RetentionFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _extra_fields: Set[ColumnName]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
        *,
        entity: Optional[Entity] = None,
        extra_fields: List[ColumnName] = [],
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._entity = entity
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)
        self._extra_fields = set(extra_fields)

        if self.PERSON_PROPERTIES_ALIAS in self._extra_fields:
            self._extra_fields = self._extra_fields - {self.PERSON_PROPERTIES_ALIAS} | {"properties"}

    def get_query(self) -> Tuple[str, Dict]:
        fields = "id" + " ".join(
            f", argMax({column_name}, _timestamp) as {alias}" for column_name, alias in self._get_fields()
        )

        person_filters, params = self._get_person_filters()

        return (
            f"""
            SELECT {fields}
            FROM person
            WHERE team_id = %(team_id)s
            GROUP BY id
            HAVING max(is_deleted) = 0 {person_filters}
        """,
            params,
        )

    @property
    def fields(self) -> List[ColumnName]:
        "Returns person table fields this query exposes"
        return [alias for column_name, alias in self._get_fields()]

    @property
    def is_used(self):
        "Returns whether properties or any other columns are actually being queried"
        if any(self._uses_person_id(prop) for prop in self._filter.properties):
            return True
        if any(self._uses_person_id(prop) for entity in self._filter.entities for prop in entity.properties):
            return True

        return len(self._column_optimizer.person_columns_to_query) > 0

    def _uses_person_id(self, prop: Property) -> bool:
        return prop.type in ("person", "static-cohort", "precalculated-cohort")

    def _get_fields(self) -> List[Tuple[str, str]]:
        # :TRICKY: Figure out what fields we want to expose - minimizing this set is good for performance.
        #   We use the result from column_optimizer to figure out counts of all properties to be filtered and queried.
        #   Here, we remove the ones only to be used for filtering.
        # The same property might be present for both querying and filtering, and hence the Counter.
        properties_to_query = self._column_optimizer._used_properties_with_type("person")
        properties_to_query -= extract_tables_and_properties(self._filter.properties)

        if self._entity is not None:
            properties_to_query -= extract_tables_and_properties(self._entity.properties)

        columns = self._column_optimizer.columns_to_query("person", set(properties_to_query)) | set(self._extra_fields)

        return [(column_name, self.ALIASES.get(column_name, column_name)) for column_name in sorted(columns)]

    def _get_person_filters(self) -> Tuple[str, Dict]:
        conditions, params = [""], {}

        properties = self._filter.properties + (self._entity.properties if self._entity else [])

        for index, property in enumerate(properties):
            if property.type != "person":
                continue

            expr, prop_params = prop_filter_json_extract(
                property,
                index,
                prepend="personquery",
                allow_denormalized_props=True,
                transform_expression=lambda column_name: f"argMax(person.{column_name}, _timestamp)",
            )

            conditions.append(expr)
            params.update(prop_params)

        return " ".join(conditions), params
