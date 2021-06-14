from typing import Any, Dict, Tuple

from ee.clickhouse.models.cohort import format_person_query, get_precalculated_query, is_precalculated_query
from ee.clickhouse.models.property import filter_element, prop_filter_json_extract
from ee.clickhouse.queries.trends.util import populate_entity_params
from ee.clickhouse.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps
from posthog.models import Cohort, Entity, Filter, Property, Team


class ClickhouseEventQuery:
    DISTINCT_ID_TABLE_ALIAS = "pdi"
    PERSON_TABLE_ALIAS = "person"
    EVENT_TABLE_ALIAS = "e"

    _PERSON_PROPERTIES_ALIAS = "person_props"
    _filter: Filter
    _entity: Entity
    _team_id: int
    _should_join_distinct_ids = False
    _should_join_persons = False
    _should_round_interval = False
    _date_filter = None

    def __init__(
        self,
        filter: Filter,
        entity: Entity,
        team_id: int,
        round_interval=False,
        should_join_distinct_ids=False,
        should_join_persons=False,
        date_filter=None,
        **kwargs,
    ) -> None:
        self._filter = filter
        self._entity = entity
        self._team_id = team_id
        self.params = {
            "team_id": self._team_id,
        }
        self._date_filter = date_filter

        self._should_join_distinct_ids = should_join_distinct_ids
        self._should_join_persons = should_join_persons

        if not self._should_join_distinct_ids:
            self._determine_should_join_distinct_ids()

        if not self._should_join_persons:
            self._determine_should_join_persons()

        self._should_round_interval = round_interval

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp, {self.EVENT_TABLE_ALIAS}.properties as properties"
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
            + (f", {self.PERSON_TABLE_ALIAS}.person_props as person_props" if self._should_join_persons else "")
        )

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_props()
        self.params.update(prop_params)

        entity_query, entity_params = self._get_entity_query()
        self.params.update(entity_params)

        query = f"""
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_disintct_id_query()}
            {self._get_person_query()}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        if self._entity.math == "dau":
            self._should_join_distinct_ids = True
            return

    def _get_disintct_id_query(self) -> str:
        if self._should_join_distinct_ids:
            return f"""
            INNER JOIN (
                SELECT person_id,
                    distinct_id
                FROM (
                        SELECT *
                        FROM person_distinct_id
                        JOIN (
                                SELECT distinct_id,
                                    max(_offset) as _offset
                                FROM person_distinct_id
                                WHERE team_id = %(team_id)s
                                GROUP BY distinct_id
                            ) as person_max
                            ON person_distinct_id.distinct_id = person_max.distinct_id
                        AND person_distinct_id._offset = person_max._offset
                        WHERE team_id = %(team_id)s
                    )
                WHERE team_id = %(team_id)s
            ) AS {self.DISTINCT_ID_TABLE_ALIAS}
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

        for prop in self._entity.properties:
            if prop.type == "person":
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
        cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
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

    def _get_entity_query(self) -> Tuple[str, Dict]:
        entity_params, entity_format_params = populate_entity_params(self._entity)

        return entity_format_params["entity_query"], entity_params

    def _get_date_filter(self) -> Tuple[str, Dict]:
        if self._date_filter:
            return self._date_filter, {}

        parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team_id=self._team_id)

        query = f"""
        {parsed_date_from}
        {parsed_date_to}
        """

        return query, date_params

    def _get_props(self, allow_denormalized_props: bool = False) -> Tuple[str, Dict]:

        filters = [*self._filter.properties, *self._entity.properties]
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
        cohort = Cohort.objects.get(pk=prop.value, team_id=self._team_id)
        is_precalculated = is_precalculated_query(cohort)

        person_id_query, cohort_filter_params = (
            get_precalculated_query(cohort, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
            if is_precalculated
            else format_person_query(cohort, custom_match_field=f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id")
        )

        return person_id_query, cohort_filter_params
