from abc import ABCMeta, abstractmethod
from typing import Any, Dict, List, Tuple

from ee.clickhouse.models.cohort import format_person_query, get_precalculated_query, is_precalculated_query
from ee.clickhouse.models.property import filter_element, prop_filter_json_extract
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.models import Cohort, Filter, Property, Team


class ClickhouseEventQuery(metaclass=ABCMeta):
    DISTINCT_ID_TABLE_ALIAS = "pdi"
    PERSON_TABLE_ALIAS = "person"
    EVENT_TABLE_ALIAS = "e"

    _PERSON_PROPERTIES_ALIAS = "person_props"
    _filter: Filter
    _team_id: int
    _should_join_distinct_ids = False
    _should_join_persons = False
    _should_round_interval = False

    def __init__(
        self,
        filter: Filter,
        team_id: int,
        round_interval=False,
        should_join_distinct_ids=False,
        should_join_persons=False,
        **kwargs,
    ) -> None:
        self._filter = filter
        self._team_id = team_id
        self.params = {
            "team_id": self._team_id,
        }

        self._should_join_distinct_ids = should_join_distinct_ids
        self._should_join_persons = should_join_persons

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
        for prop in self._filter.properties:
            if prop.type == "person":
                self._should_join_distinct_ids = True
                self._should_join_persons = True
                return
            if prop.type == "cohort" and self._does_cohort_need_persons(prop):
                self._should_join_distinct_ids = True
                self._should_join_persons = True
                return

        if self._filter.breakdown_type == "person":
            self._should_join_distinct_ids = True
            self._should_join_persons = True

        if self._filter.filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=self._team_id).test_account_filters
            test_filter_props = [Property(**prop) for prop in test_account_filters]
            for prop in test_filter_props:
                if prop.type == "person":
                    self._should_join_distinct_ids = True
                    self._should_join_persons = True
                    return

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
                SELECT id, properties as person_props
                FROM (
                    SELECT id,
                        argMax(properties, person._timestamp) as properties,
                        max(is_deleted) as is_deleted
                    FROM person
                    WHERE team_id = %(team_id)s
                    GROUP BY id
                    HAVING is_deleted = 0
                )
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

    def _get_props(self, filters: List[Property], allow_denormalized_props: bool = False) -> Tuple[str, Dict]:

        filter_test_accounts = self._filter.filter_test_accounts
        team_id = self._team_id
        table_name = f"{self.EVENT_TABLE_ALIAS}."
        prepend = "global"

        final = []
        params: Dict[str, Any] = {}

        if filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=team_id).test_account_filters
            filters.extend([Property(**prop) for prop in test_account_filters])

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
                    allow_denormalized_props=allow_denormalized_props,
                    prop_var=self._PERSON_PROPERTIES_ALIAS,
                )
                final.append(filter_query)
                params.update(filter_params)
            elif prop.type == "element":
                query, filter_params = filter_element({prop.key: prop.value}, prepend="{}_".format(idx))
                final.append("AND {}".format(query[0]))
                params.update(filter_params)
            else:
                filter_query, filter_params = prop_filter_json_extract(
                    prop, idx, prepend, prop_var="properties", allow_denormalized_props=allow_denormalized_props,
                )

                final.append(filter_query)
                params.update(filter_params)
        return " ".join(final), params

    def _get_cohort_subquery(self, prop) -> Tuple[str, Dict[str, Any]]:
        try:
            cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
        except Cohort.DoesNotExist:
            return "0 = 1", {}  # If cohort doesn't exist, nothing can match

        is_precalculated = is_precalculated_query(cohort)

        person_id_query, cohort_filter_params = (
            get_precalculated_query(cohort, 0, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
            if is_precalculated
            else format_person_query(cohort, 0, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
        )

        return person_id_query, cohort_filter_params
