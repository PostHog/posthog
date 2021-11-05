from abc import ABCMeta, abstractmethod
from typing import Any, Dict, List, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.cohort import format_person_query, format_precalculated_cohort_query, is_precalculated_query
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.models.util import PersonPropertiesMode
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.query_builder import SQL, SQLFragment
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.models import Cohort, Filter, Property
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter


class ClickhouseEventQuery(metaclass=ABCMeta):
    DISTINCT_ID_TABLE_ALIAS = "pdi"
    PERSON_TABLE_ALIAS = "person"
    EVENT_TABLE_ALIAS = "e"

    _filter: Union[Filter, PathFilter, RetentionFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _person_query: ClickhousePersonQuery
    _should_join_distinct_ids = False
    _should_join_persons = False
    _should_round_interval = False
    _extra_fields: List[ColumnName]
    _extra_person_fields: List[ColumnName]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter],
        team_id: int,
        round_interval=False,
        should_join_distinct_ids=False,
        should_join_persons=False,
        # Extra events/person table columns to fetch since parent query needs them
        extra_fields: List[ColumnName] = [],
        extra_person_fields: List[ColumnName] = [],
        **kwargs,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self._column_optimizer = ColumnOptimizer(self._filter, self._team_id)
        self._person_query = ClickhousePersonQuery(
            self._filter, self._team_id, self._column_optimizer, extra_fields=extra_person_fields
        )

        self._should_join_distinct_ids = should_join_distinct_ids
        self._should_join_persons = should_join_persons
        self._extra_fields = extra_fields
        self._extra_person_fields = extra_person_fields

        if not self._should_join_distinct_ids:
            self._determine_should_join_distinct_ids()

        if not self._should_join_persons:
            self._determine_should_join_persons()

        self._should_round_interval = round_interval

    @abstractmethod
    def get_query(self) -> SQLFragment:
        pass

    @abstractmethod
    def _determine_should_join_distinct_ids(self) -> None:
        pass

    def _get_disintct_id_query(self) -> SQLFragment:
        if self._should_join_distinct_ids:
            return SQL(
                f"""
            INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS {self.DISTINCT_ID_TABLE_ALIAS}
            ON events.distinct_id = {self.DISTINCT_ID_TABLE_ALIAS}.distinct_id
            """
            )
        else:
            return SQL("")

    def _determine_should_join_persons(self) -> None:
        if self._person_query.is_used:
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

        # :KLUDGE: The following is mostly making sure if cohorts are included as well.
        #   Can be simplified significantly after https://github.com/PostHog/posthog/issues/5854
        if any(self._should_property_join_persons(prop) for prop in self._filter.properties):
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

        if any(
            self._should_property_join_persons(prop) for entity in self._filter.entities for prop in entity.properties
        ):
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

        if self._filter.breakdown_type == "person":
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

    def _should_property_join_persons(self, prop: Property) -> bool:
        return prop.type == "cohort" and self._does_cohort_need_persons(prop)

    def _does_cohort_need_persons(self, prop: Property) -> bool:
        try:
            cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
        except Cohort.DoesNotExist:
            return False
        if is_precalculated_query(cohort):
            return True
        if cohort.is_static:
            return True
        for group in cohort.groups:
            if group.get("properties"):
                return True
        return False

    def _get_person_query(self) -> SQLFragment:
        if self._should_join_persons:
            person_query, params = self._person_query.get_query()
            return SQL(
                f"""
            INNER JOIN ({person_query}) {self.PERSON_TABLE_ALIAS}
            ON {self.PERSON_TABLE_ALIAS}.id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id
            """,
                params,
            )
        else:
            return SQL("")

    def _get_groups_query(self) -> SQLFragment:
        return GroupsJoinQuery(self._filter, self._team_id, self._column_optimizer).get_join_query()

    def _get_date_filter(self) -> SQLFragment:
        parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team_id=self._team_id)

        return SQL(
            f"""
        {parsed_date_from}
        {parsed_date_to}
        """,
            date_params,
        )

    def _get_props(self, filters: List[Property]) -> SQLFragment:
        prop_query = SQL("")

        for idx, prop in enumerate(filters):
            if prop.type == "cohort":
                prop_query += SQL(" AND {self._get_cohort_subquery(prop)}")
            else:
                filter_query, filter_params = parse_prop_clauses(
                    [prop],
                    self._team_id,
                    prepend=f"global_{idx}",
                    allow_denormalized_props=True,
                    person_properties_mode=PersonPropertiesMode.EXCLUDE,
                )
                prop_query += SQL(" " + filter_query, filter_params)
        return prop_query

    def _get_cohort_subquery(self, prop) -> SQLFragment:
        try:
            cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
        except Cohort.DoesNotExist:
            return SQL("0 = 11")  # If cohort doesn't exist, nothing can match

        is_precalculated = is_precalculated_query(cohort)

        person_id_query, cohort_filter_params = (
            format_precalculated_cohort_query(
                cohort.pk, 0, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id"
            )
            if is_precalculated
            else format_person_query(cohort, 0, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
        )

        return SQL(person_id_query, cohort_filter_params)
