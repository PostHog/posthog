from typing import Any, Dict, Tuple

from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.property import filter_element, prop_filter_json_extract
from posthog.model import Cohort, Entity, Filter, Property, Team


class ClickhouseEventQuery:
    PDI_TABLE_ALIAS = "pdi"
    PERSON_TABLE_ALIAS = "person"
    EVENT_TABLE_ALIAS = "e"

    _PERSON_PROPERTIES_ALIAS = "person_props"
    _filter: Filter
    _team: Team
    _should_join_pdi = False
    _should_join_persons = False

    def __init__(self, filter: Filter, entity: Entity, team: Team, **kwargs) -> None:
        self._filter = filter
        self._team = team
        self.params = {
            "team_id": self._team.pk,
        }

        self._should_join_pdi = self._determine_should_join_pdi(entity)
        self._should_join_persons = self._determine_should_join_persons(filter, entity)

    def get_query(self, fields) -> Tuple[str, Dict[str, Any]]:
        prop_query, prop_params = self._get_props(filter)
        self.params.update(prop_params)

        query = f"""
            SELECT {fields} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_pdi_query()}
            {self._get_person_query()}
            WHERE team_id = %(team_id)s
            {prop_query}
        """

        return query, self.params

    def _determine_should_join_pdi(self, entity: Entity) -> None:
        if entity.math == "dau":
            self._should_join_pdi = True
            return

    def _get_pdi_query(self) -> str:
        if self._should_join_pdi:
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
            ) AS {self.DI_TABLE_NAME}
            ON events.distinct_id = {self.PDI_TABLE_NAME}.distinct_id
            """
        else:
            return ""

    def _determine_should_join_persons(self, filter: Filter, entity: Entity) -> None:
        for prop in filter.properties:
            if prop.type == "person":
                self._should_join_pdi = True
                self._should_join_persons = True
                return

        for prop in entity.properties:
            if prop.type == "person":
                self._should_join_pdi = True
                self._should_join_persons = True
                return

        if filter.breakdown_type == "person":
            self._should_join_pdi = True
            self._should_join_persons = True

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
            ON {self.PERSON_TABLE_ALIAS}.id = {self.PDI_TABLE_NAME}.person_id
            """

    def _get_props(self, filter: Filter, allow_denormalized_props: bool = False,) -> Tuple[str, Dict]:

        filters = filter.properties
        filter_test_accounts = filter.filter_test_accounts
        team_id = self._team.pk
        table_name = f"{self.EVENT_TABLE_ALIAS}."
        prepend = "global"

        final = []
        params: Dict[str, Any] = {}

        if filter_test_accounts:
            test_account_filters = Team.objects.only("test_account_filters").get(id=team_id).test_account_filters
            filters.extend([Property(**prop) for prop in test_account_filters])

        for idx, prop in enumerate(filters):
            if prop.type == "cohort":
                cohort = Cohort.objects.get(pk=prop.value, team_id=team_id)
                person_id_query, cohort_filter_params = format_filter_query(cohort)
                params = {**params, **cohort_filter_params}
                final.append(f"AND {table_name}distinct_id IN ({person_id_query})")
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
