from typing import Dict, List, Optional, Set, Tuple, Union

from posthog.clickhouse.materialized_columns.columns import ColumnName
from posthog.constants import PropertyOperatorType
from posthog.models import Filter
from posthog.models.cohort import Cohort
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID, GET_STATIC_COHORTPEOPLE_BY_COHORT_ID
from posthog.models.entity import Entity
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import Property, PropertyGroup
from posthog.models.property.util import extract_tables_and_properties, parse_prop_grouped_clauses
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.column_optimizer import ColumnOptimizer
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query


class PersonQuery:
    """
    Query class responsible for joining with `person` clickhouse table

    For sake of performance, this class:
    - Tries to do as much person property filtering as possible here
    - Minimizes the amount of columns read
    """

    PERSON_PROPERTIES_ALIAS = "person_props"
    COHORT_TABLE_ALIAS = "cohort_persons"
    ALIASES = {"properties": "person_props"}

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _extra_fields: Set[ColumnName]
    _inner_person_properties: Optional[PropertyGroup]
    _cohort: Optional[Cohort]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
        cohort: Optional[Cohort] = None,
        *,
        entity: Optional[Entity] = None,
        extra_fields: List[ColumnName] = [],
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._entity = entity
        self._cohort = cohort
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

    def get_query(self, prepend: str = "") -> Tuple[str, Dict]:
        fields = "id" + " ".join(
            f", argMax({column_name}, _timestamp) as {alias}" for column_name, alias in self._get_fields()
        )

        person_filters, params = self._get_person_filters(prepend=prepend)
        cohort_query, cohort_params = self._get_cohort_query()
        limit_offset, limit_params = self._get_limit_offset()
        search_clause, search_params = self._get_search_clause(prepend=prepend)

        return (
            f"""
            SELECT {fields}
            FROM person
            {cohort_query}
            WHERE team_id = %(team_id)s
            GROUP BY id
            HAVING max(is_deleted) = 0 {person_filters} {search_clause}
            {limit_offset}
        """,
            {**params, **cohort_params, **limit_params, **search_params, "team_id": self._team_id},
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

    def _get_person_filters(self, prepend: str = "") -> Tuple[str, Dict]:
        return parse_prop_grouped_clauses(
            self._team_id,
            self._inner_person_properties,
            has_person_id_joined=False,
            group_properties_joined=False,
            person_properties_mode=PersonPropertiesMode.DIRECT,
            prepend=prepend,
        )

    def _get_cohort_query(self) -> Tuple[str, Dict]:

        if self._cohort:
            cohort_table = (
                GET_STATIC_COHORTPEOPLE_BY_COHORT_ID if self._cohort.is_static else GET_COHORTPEOPLE_BY_COHORT_ID
            )
            return (
                f"""
            INNER JOIN (
                {cohort_table}
            ) {self.COHORT_TABLE_ALIAS}
            ON {self.COHORT_TABLE_ALIAS}.person_id = person.id
            """,
                {"team_id": self._team_id, "cohort_id": self._cohort.pk},
            )
        else:
            return "", {}

    def _get_limit_offset(self) -> Tuple[str, Dict]:

        if not isinstance(self._filter, Filter):
            return "", {}

        if not self._cohort or not (self._filter.limit or self._filter.offset):
            return "", {}

        clause = """
        ORDER BY id
        """

        params = {}

        if self._filter.limit:
            clause += " LIMIT %(limit)s"
            params.update({"limit": self._filter.limit})

        if self._filter.offset:
            clause += " OFFSET %(offset)s"
            params.update({"offset": self._filter.offset})

        return clause, params

    def _get_search_clause(self, prepend: str = "") -> Tuple[str, Dict]:

        if not isinstance(self._filter, Filter):
            return "", {}

        if self._filter.search:
            prop_group = PropertyGroup(
                type=PropertyOperatorType.AND,
                values=[Property(key="email", operator="icontains", value=self._filter.search, type="person")],
            )
            search_clause, params = parse_prop_grouped_clauses(
                self._team_id,
                prop_group,
                prepend=f"search_{prepend}",
                has_person_id_joined=False,
                group_properties_joined=False,
                person_properties_mode=PersonPropertiesMode.DIRECT,
                _top_level=False,
            )

            distinct_id_param = f"distinct_id_{prepend}"
            distinct_id_clause = f"""
            id IN (
                SELECT person_id FROM ({get_team_distinct_ids_query(self._team_id)}) where distinct_id = %({distinct_id_param})s
            )
            """

            params.update({distinct_id_param: self._filter.search})

            return f"AND (({search_clause}) OR ({distinct_id_clause}))", params

        return "", {}
