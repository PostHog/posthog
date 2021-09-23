from abc import ABCMeta, abstractmethod
from typing import Any, Dict, List, Tuple, Union

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.models.cohort import format_person_query, get_precalculated_query, is_precalculated_query
from ee.clickhouse.models.property import filter_element, prop_filter_json_extract
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.models import Cohort, Filter, Property, Team
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter


class ClickhouseEventQuery(metaclass=ABCMeta):
    DISTINCT_ID_TABLE_ALIAS = "pdi"
    PERSON_TABLE_ALIAS = "person"
    EVENT_TABLE_ALIAS = "e"

    _filter: Union[Filter, PathFilter, RetentionFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
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
        self.params: Dict[str, Any] = {
            "team_id": self._team_id,
        }

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
    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        pass

    @abstractmethod
    def _determine_should_join_distinct_ids(self) -> None:
        pass

    def _get_disintct_id_query(self) -> str:
        if self._should_join_distinct_ids:
            return f"""
            INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS {self.DISTINCT_ID_TABLE_ALIAS}
            ON events.distinct_id = {self.DISTINCT_ID_TABLE_ALIAS}.distinct_id
            """
        else:
            return ""

    def _determine_should_join_persons(self) -> None:
        if self._column_optimizer.is_using_person_properties:
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

        if self._filter.filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=self._team_id).test_account_filters
            test_filter_props = [Property(**prop) for prop in test_account_filters]
            if any(self._should_property_join_persons(prop) for prop in test_filter_props):
                self._should_join_distinct_ids = True
                self._should_join_persons = True
                return

    def _should_property_join_persons(self, prop: Property) -> bool:
        if prop.type == "person":
            return True

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

    def _get_person_query(self) -> str:
        if self._should_join_persons:
            return f"""
            INNER JOIN (
                {ClickhousePersonQuery(self._filter, self._team_id, self._column_optimizer, self._extra_person_fields).get_query()}
            ) {self.PERSON_TABLE_ALIAS}
            ON {self.PERSON_TABLE_ALIAS}.id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id
            """
        else:
            return ""

    def _get_date_filter(self) -> Tuple[str, Dict]:

        parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team_id=self._team_id)

        query = f"""
        {parsed_date_from}
        {parsed_date_to}
        """

        return query, date_params

    def _get_props(self, filters: List[Property]) -> Tuple[str, Dict]:

        filter_test_accounts = self._filter.filter_test_accounts
        team_id = self._team_id
        prepend = "global"

        final = []
        params: Dict[str, Any] = {}

        if filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=team_id).test_account_filters
            filters += [Property(**prop) for prop in test_account_filters]

        for idx, prop in enumerate(filters):
            if prop.type == "cohort":
                person_id_query, cohort_filter_params = self._get_cohort_subquery(prop)
                params = {**params, **cohort_filter_params}
                final.append(f"AND {person_id_query}")

            elif prop.type == "person":
                filter_query, filter_params = prop_filter_json_extract(
                    prop,
                    idx,
                    "{}person".format(prepend),
                    allow_denormalized_props=True,
                    prop_var=ClickhousePersonQuery.PERSON_PROPERTIES_ALIAS,
                )
                final.append(filter_query)
                params.update(filter_params)
            elif prop.type == "element":
                query, filter_params = filter_element(
                    {prop.key: prop.value}, operator=prop.operator, prepend="{}_".format(idx)
                )
                if query:
                    final.append(f" AND {query}")
                    params.update(filter_params)
            else:
                filter_query, filter_params = prop_filter_json_extract(
                    prop, idx, prepend, prop_var="properties", allow_denormalized_props=True
                )

                final.append(filter_query)
                params.update(filter_params)
        return " ".join(final), params

    def _get_cohort_subquery(self, prop) -> Tuple[str, Dict[str, Any]]:
        try:
            cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
        except Cohort.DoesNotExist:
            return "0 = 11", {}  # If cohort doesn't exist, nothing can match

        is_precalculated = is_precalculated_query(cohort)

        person_id_query, cohort_filter_params = (
            get_precalculated_query(cohort, 0, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
            if is_precalculated
            else format_person_query(cohort, 0, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
        )

        return person_id_query, cohort_filter_params
