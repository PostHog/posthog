from typing import Dict, List, Optional, Set, Tuple, Union, cast

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.property import (
    extract_tables_and_properties,
    parse_prop_grouped_clauses,
    prop_filter_json_extract,
)
from ee.clickhouse.models.util import PersonPropertiesMode
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.property_optimizer import PropertyOptimizer
from posthog.constants import PropertyOperatorType
from posthog.models import Filter
from posthog.models.entity import Entity
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import Property, PropertyGroup


class ClickhousePersonQuery:
    """
    Query class responsible for joining with `person` clickhouse table

    For sake of performance, this class:
    - Tries to do as much person property filtering as possible here
    - Minimizes the amount of columns read
    """

    PERSON_PROPERTIES_ALIAS = "person_props"
    ALIASES = {"properties": "person_props"}

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _extra_fields: Set[ColumnName]
    _inner_person_properties: Optional[PropertyGroup]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter],
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

        properties = self._filter.property_groups.combine_property_group(
            PropertyOperatorType.AND, self._entity.property_groups if self._entity else None
        )

        self._inner_person_properties = self._column_optimizer.property_optimizer.parse_property_groups(
            properties
        ).inner

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
        if any(self._uses_person_id(prop) for prop in self._filter.property_groups.flat):
            return True
        if any(self._uses_person_id(prop) for entity in self._filter.entities for prop in entity.property_groups.flat):
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
        if self._inner_person_properties:
            properties_to_query -= extract_tables_and_properties(self._inner_person_properties.flat)

        columns = self._column_optimizer.columns_to_query("person", set(properties_to_query)) | set(self._extra_fields)

        return [(column_name, self.ALIASES.get(column_name, column_name)) for column_name in sorted(columns)]

    def _get_person_filters(self) -> Tuple[str, Dict]:
        return parse_prop_grouped_clauses(
            self._team_id,
            self._inner_person_properties,
            has_person_id_joined=False,
            group_properties_joined=False,
            person_properties_mode=PersonPropertiesMode.DIRECT,
        )
