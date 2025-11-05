from typing import Any, Optional, Union
from uuid import UUID

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.constants import PropertyOperatorType
from posthog.models import Filter
from posthog.models.cohort import Cohort
from posthog.models.cohort.sql import GET_COHORTPEOPLE_BY_COHORT_ID, GET_STATIC_COHORTPEOPLE_BY_COHORT_ID
from posthog.models.cohort.util import format_precalculated_cohort_query, format_static_cohort_query
from posthog.models.entity import Entity
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import Property, PropertyGroup
from posthog.models.property.util import (
    extract_tables_and_properties,
    parse_prop_grouped_clauses,
    prop_filter_json_extract,
)
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.trends.util import COUNT_PER_ACTOR_MATH_FUNCTIONS
from posthog.queries.util import PersonPropertiesMode


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
    _extra_fields: set[ColumnName]
    _inner_person_properties: Optional[PropertyGroup]
    _cohort: Optional[Cohort]
    _include_distinct_ids: Optional[bool] = False

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter],
        team_id: int,
        column_optimizer: Optional[ColumnOptimizer] = None,
        cohort: Optional[Cohort] = None,
        *,
        entity: Optional[Entity] = None,
        extra_fields: Optional[list[ColumnName]] = None,
        # A sub-optimal version of the `cohort` parameter above, the difference being that
        # this supports multiple cohort filters, but is not as performant as the above.
        cohort_filters: Optional[list[Property]] = None,
        include_distinct_ids: Optional[bool] = False,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._entity = entity
        self._cohort = cohort
        self._column_optimizer = column_optimizer or ColumnOptimizer(self._filter, self._team_id)
        self._extra_fields = set(extra_fields) if extra_fields else set()
        self._cohort_filters = cohort_filters
        self._include_distinct_ids = include_distinct_ids

        if self.PERSON_PROPERTIES_ALIAS in self._extra_fields:
            self._extra_fields = self._extra_fields - {self.PERSON_PROPERTIES_ALIAS} | {"properties"}

        properties = self._filter.property_groups.combine_property_group(
            PropertyOperatorType.AND,
            self._entity.property_groups if self._entity else None,
        )

        self._inner_person_properties = self._column_optimizer.property_optimizer.parse_property_groups(
            properties
        ).inner

    def get_query(
        self,
        prepend: Optional[Union[str, int]] = None,
        paginate: bool = False,
        filter_future_persons: bool = False,
    ) -> tuple[str, dict]:
        prepend = str(prepend) if prepend is not None else ""

        fields = "id" + " ".join(
            f", argMax({column_name}, version) as {alias}" for column_name, alias in self._get_fields()
        )

        (
            person_filters_prefiltering_condition,
            person_filters_finalization_condition,
            person_filters_params,
        ) = self._get_person_filter_clauses(prepend=prepend)
        (
            multiple_cohorts_condition,
            multiple_cohorts_params,
        ) = self._get_multiple_cohorts_clause(prepend=prepend)
        single_cohort_join, single_cohort_params = self._get_fast_single_cohort_clause()
        if paginate:
            order = "ORDER BY argMax(person.created_at, version) DESC, id DESC" if paginate else ""
            limit_offset, limit_params = self._get_limit_offset_clause()
        else:
            order = ""
            limit_offset, limit_params = "", {}
        (
            search_prefiltering_condition,
            search_finalization_condition,
            search_params,
        ) = self._get_search_clauses(prepend=prepend)
        distinct_id_condition, distinct_id_params = self._get_distinct_id_clause()
        email_condition, email_params = self._get_email_clause()
        filter_future_persons_condition = (
            "AND argMax(person.created_at, version) < now() + INTERVAL 1 DAY" if filter_future_persons else ""
        )
        updated_after_condition, updated_after_params = self._get_updated_after_clause()

        # If there are person filters or search, we do a prefiltering lookup so that the dataset is as small
        # as possible BEFORE the `HAVING` clause (but without eliminating any rows that should be matched).
        # This greatly reduces memory usage because in this lookup we don't aggregate by person version.
        # Additionally, if we're doing prefiltering, it's more efficient to filter by the single cohort inner join here.
        prefiltering_lookup = (
            f"""AND id IN (
            SELECT id FROM person
            {single_cohort_join}
            WHERE team_id = %(team_id)s
            {person_filters_prefiltering_condition}
            {search_prefiltering_condition}
        )
        """
            if person_filters_prefiltering_condition or search_prefiltering_condition
            else ""
        )
        # If we're not prefiltering, the single cohort inner join needs to be at the top level.
        top_level_single_cohort_join = single_cohort_join if not prefiltering_lookup else ""

        return self._add_distinct_id_join_if_needed(
            f"""
            SELECT {fields}
            FROM person
            {top_level_single_cohort_join}
            WHERE team_id = %(team_id)s
            {prefiltering_lookup}
            {multiple_cohorts_condition}
            {email_condition}
            GROUP BY id
            HAVING max(is_deleted) = 0
            {filter_future_persons_condition} {updated_after_condition}
            {person_filters_finalization_condition} {search_finalization_condition}
            {distinct_id_condition}
            {order}
            {limit_offset}
            SETTINGS optimize_aggregation_in_order = 1
            """,
            {
                **updated_after_params,
                **person_filters_params,
                **single_cohort_params,
                **limit_params,
                **search_params,
                **distinct_id_params,
                **email_params,
                **multiple_cohorts_params,
                "team_id": self._team_id,
            },
        )

    def get_uniq_count(self) -> tuple[str, dict]:
        """
        Returns a simplified query that counts unique person IDs using uniq(id).
        This is more efficient than the full get_query() for counting purposes.
        Ignores prefiltering optimizations and is_deleted checks for simplicity.
        """
        (
            person_filters_prefiltering_condition,
            _,
            person_filters_params,
        ) = self._get_person_filter_clauses()
        (
            multiple_cohorts_condition,
            multiple_cohorts_params,
        ) = self._get_multiple_cohorts_clause()
        single_cohort_join, single_cohort_params = self._get_fast_single_cohort_clause()
        (
            search_prefiltering_condition,
            _,
            search_params,
        ) = self._get_search_clauses()
        distinct_id_condition, distinct_id_params = self._get_distinct_id_clause()
        email_condition, email_params = self._get_email_clause()

        return (
            f"""
            SELECT uniq(id)
            FROM person
            {single_cohort_join}
            WHERE team_id = %(team_id)s
            {multiple_cohorts_condition}
            {email_condition}
            {person_filters_prefiltering_condition} {search_prefiltering_condition}
            {distinct_id_condition}
            """,
            {
                **person_filters_params,
                **single_cohort_params,
                **search_params,
                **distinct_id_params,
                **email_params,
                **multiple_cohorts_params,
                "team_id": self._team_id,
            },
        )

    @property
    def fields(self) -> list[ColumnName]:
        "Returns person table fields this query exposes"
        return [alias for column_name, alias in self._get_fields()]

    @property
    def is_used(self):
        "Returns whether properties or any other columns are actually being queried"
        if any(self._uses_person_id(prop) for prop in self._filter.property_groups.flat):
            return True
        for entity in self._filter.entities:
            is_count_per_user = entity.math in COUNT_PER_ACTOR_MATH_FUNCTIONS and entity.math_group_type_index is None
            if is_count_per_user or any(self._uses_person_id(prop) for prop in entity.property_groups.flat):
                return True

        return len(self._column_optimizer.person_columns_to_query) > 0

    def _uses_person_id(self, prop: Property) -> bool:
        return prop.type in ("person", "static-cohort", "precalculated-cohort")

    def _get_fields(self) -> list[tuple[str, str]]:
        # :TRICKY: Figure out what fields we want to expose - minimizing this set is good for performance.
        #   We use the result from column_optimizer to figure out counts of all properties to be filtered and queried.
        #   Here, we remove the ones only to be used for filtering.
        # The same property might be present for both querying and filtering, and hence the Counter.
        properties_to_query = self._column_optimizer.used_properties_with_type("person")
        if self._inner_person_properties:
            properties_to_query -= extract_tables_and_properties(self._inner_person_properties.flat)

        columns = self._column_optimizer.columns_to_query("person", set(properties_to_query)) | set(self._extra_fields)

        return [(column_name, self.ALIASES.get(column_name, column_name)) for column_name in sorted(columns)]

    def _get_person_filter_clauses(self, prepend: str = "") -> tuple[str, str, dict]:
        finalization_conditions, params = parse_prop_grouped_clauses(
            self._team_id,
            self._inner_person_properties,
            has_person_id_joined=False,
            group_properties_joined=False,
            person_properties_mode=PersonPropertiesMode.DIRECT,
            prepend=f"person_filter_fin_{prepend}",
            hogql_context=self._filter.hogql_context,
        )
        prefiltering_conditions, prefiltering_params = parse_prop_grouped_clauses(
            self._team_id,
            self._inner_person_properties,
            has_person_id_joined=False,
            group_properties_joined=False,
            # The above kwargs are the same as for finalization EXCEPT this one - we use the property
            # from the person BEFORE aggregation by version here, to eliminate persons early on
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_PERSONS,
            prepend=f"person_filter_pre_{prepend}",
            hogql_context=self._filter.hogql_context,
        )
        params.update(prefiltering_params)
        return prefiltering_conditions, finalization_conditions, params

    def _get_fast_single_cohort_clause(self) -> tuple[str, dict]:
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
                {
                    "team_id": self._team_id,
                    "cohort_id": self._cohort.pk,
                    "version": self._cohort.version,
                },
            )
        else:
            return "", {}

    def _get_multiple_cohorts_clause(self, prepend: str = "") -> tuple[str, dict]:
        if self._cohort_filters:
            query = []
            params: dict[str, Any] = {}

            # TODO: doesn't support non-caclculated cohorts
            for index, property in enumerate(self._cohort_filters):
                try:
                    cohort = Cohort.objects.get(pk=property.value)
                    if property.type == "static-cohort":
                        subquery, subquery_params = format_static_cohort_query(cohort, index, prepend)
                    else:
                        subquery, subquery_params = format_precalculated_cohort_query(cohort, index, prepend)
                    query.append(f"AND id in ({subquery})")
                    params.update(**subquery_params)
                except Cohort.DoesNotExist:
                    continue

            return " ".join(query), params
        else:
            return "", {}

    def _get_limit_offset_clause(self) -> tuple[str, dict]:
        if not isinstance(self._filter, Filter):
            return "", {}

        if not (self._filter.limit or self._filter.offset):
            return "", {}

        clause = ""

        params = {}

        if self._filter.limit:
            clause += " LIMIT %(limit)s"
            params.update({"limit": self._filter.limit})

        if self._filter.offset:
            clause += " OFFSET %(offset)s"
            params.update({"offset": self._filter.offset})

        return clause, params

    def _get_search_clauses(self, prepend: str = "") -> tuple[str, str, dict]:
        """
        Return - respectively - the prefiltering search clause (not aggregated by is_deleted or version, which is great
        for memory usage), the final search clause (aggregated for true results, more expensive), and new params.
        """
        if not isinstance(self._filter, Filter):
            return "", "", {}

        if self._filter.search:
            id_conditions_param = f"id_conditions_{prepend}"
            id_conditions_sql = f"""
            id IN (
                SELECT person_id FROM ({get_team_distinct_ids_query(self._team_id)})
                WHERE distinct_id = %({id_conditions_param})s
            )
            """
            try:
                UUID(self._filter.search)
            except ValueError:
                pass
            else:
                id_conditions_sql = f"(id = %({id_conditions_param})s OR {id_conditions_sql})"

            prop_group = PropertyGroup(
                type=PropertyOperatorType.AND,
                values=[
                    Property(
                        key="email",
                        operator="icontains",
                        value=self._filter.search,
                        type="person",
                    )
                ],
            )
            finalization_conditions_sql, params = parse_prop_grouped_clauses(
                team_id=self._team_id,
                property_group=prop_group,
                prepend=f"search_fin_{prepend}",
                has_person_id_joined=False,
                group_properties_joined=False,
                person_properties_mode=PersonPropertiesMode.DIRECT,
                _top_level=False,
                hogql_context=self._filter.hogql_context,
            )
            finalization_sql = f"AND ({finalization_conditions_sql} OR {id_conditions_sql})"

            (
                prefiltering_conditions_sql,
                prefiltering_params,
            ) = parse_prop_grouped_clauses(
                team_id=self._team_id,
                property_group=prop_group,
                prepend=f"search_pre_{prepend}",
                has_person_id_joined=False,
                group_properties_joined=False,
                # The above kwargs are the same as for finalization EXCEPT this one - we use the property
                # from the person BEFORE aggregation by version here, to eliminate persons early on
                person_properties_mode=PersonPropertiesMode.DIRECT_ON_PERSONS,
                _top_level=False,
                hogql_context=self._filter.hogql_context,
            )
            params.update(prefiltering_params)
            prefiltering_sql = f"""AND ({prefiltering_conditions_sql} OR {id_conditions_sql})"""

            params.update({id_conditions_param: self._filter.search})

            return prefiltering_sql, finalization_sql, params

        return "", "", {}

    def _get_distinct_id_clause(self) -> tuple[str, dict]:
        if not isinstance(self._filter, Filter):
            return "", {}

        if self._filter.distinct_id:
            distinct_id_clause = f"""
            AND id IN (
                SELECT person_id FROM ({get_team_distinct_ids_query(self._team_id)}) where distinct_id = %(distinct_id_filter)s
            )
            """
            return distinct_id_clause, {"distinct_id_filter": self._filter.distinct_id}
        return "", {}

    def _add_distinct_id_join_if_needed(self, query: str, params: dict[Any, Any]) -> tuple[str, dict[Any, Any]]:
        if not self._include_distinct_ids:
            return query, params
        return (
            """
        SELECT person.*, groupArray(pdi.distinct_id) as distinct_ids
        FROM ({person_query}) person
        LEFT JOIN ({distinct_id_query}) as pdi ON person.id=pdi.person_id
        GROUP BY person.*
        ORDER BY created_at desc, id desc
        """.format(
                person_query=query,
                distinct_id_query=get_team_distinct_ids_query(self._team_id),
            ),
            params,
        )

    def _get_email_clause(self) -> tuple[str, dict]:
        if not isinstance(self._filter, Filter):
            return "", {}

        if self._filter.email:
            return prop_filter_json_extract(
                Property(key="email", value=self._filter.email, type="person"),
                0,
                prepend="_email",
            )
        return "", {}

    def _get_updated_after_clause(self) -> tuple[str, dict]:
        if not isinstance(self._filter, Filter):
            return "", {}

        if self._filter.updated_after:
            return "and max(_timestamp) > parseDateTimeBestEffort(%(updated_after)s)", {
                "updated_after": self._filter.updated_after
            }
        return "", {}
