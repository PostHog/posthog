from abc import ABCMeta, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.models import Cohort, Filter, Property
from posthog.models.cohort.util import is_precalculated_query
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.property import PropertyGroup, PropertyName
from posthog.models.property.util import parse_prop_grouped_clauses
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_query import PersonQuery
from posthog.queries.util import parse_timestamps


class EventQuery(metaclass=ABCMeta):
    DISTINCT_ID_TABLE_ALIAS = "pdi"
    PERSON_TABLE_ALIAS = "person"
    EVENT_TABLE_ALIAS = "e"

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter, SessionRecordingsFilter]
    _team_id: int
    _column_optimizer: ColumnOptimizer
    _should_join_distinct_ids = False
    _should_join_persons = False
    _should_round_interval = False
    _extra_fields: List[ColumnName]
    _extra_event_properties: List[PropertyName]
    _extra_person_fields: List[ColumnName]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter, SessionRecordingsFilter],
        team: Team,
        round_interval=False,
        should_join_distinct_ids=False,
        should_join_persons=False,
        # Extra events/person table columns to fetch since parent query needs them
        extra_fields: List[ColumnName] = [],
        extra_event_properties: List[PropertyName] = [],
        extra_person_fields: List[ColumnName] = [],
        override_aggregate_users_by_distinct_id: Optional[bool] = None,
        using_person_on_events: bool = False,
        **kwargs,
    ) -> None:
        self._filter = filter
        self._team_id = team.pk
        self._team = team
        self._extra_event_properties = extra_event_properties
        self._column_optimizer = ColumnOptimizer(self._filter, self._team_id)
        self._extra_person_fields = extra_person_fields
        self.params: Dict[str, Any] = {"team_id": self._team_id, "timezone": team.timezone}

        self._should_join_distinct_ids = should_join_distinct_ids
        self._should_join_persons = should_join_persons
        self._extra_fields = extra_fields
        self._using_person_on_events = using_person_on_events

        if override_aggregate_users_by_distinct_id is not None:
            self._aggregate_users_by_distinct_id = override_aggregate_users_by_distinct_id
        else:
            self._aggregate_users_by_distinct_id = team.aggregate_users_by_distinct_id

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

    def _get_distinct_id_query(self) -> str:
        if self._should_join_distinct_ids:
            return f"""
            INNER JOIN ({get_team_distinct_ids_query(self._team_id)}) AS {self.DISTINCT_ID_TABLE_ALIAS}
            ON {self.EVENT_TABLE_ALIAS}.distinct_id = {self.DISTINCT_ID_TABLE_ALIAS}.distinct_id
            """
        else:
            return ""

    def _determine_should_join_persons(self) -> None:
        if self._person_query.is_used:
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

        # :KLUDGE: The following is mostly making sure if cohorts are included as well.
        #   Can be simplified significantly after https://github.com/PostHog/posthog/issues/5854
        if any(self._should_property_join_persons(prop) for prop in self._filter.property_groups.flat):
            self._should_join_distinct_ids = True
            self._should_join_persons = True
            return

        if any(
            self._should_property_join_persons(prop)
            for entity in self._filter.entities
            for prop in entity.property_groups.flat
        ):
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
        for property in cohort.properties.flat:
            if property.type == "person":
                return True
        return False

    @cached_property
    def _person_query(self):
        return PersonQuery(self._filter, self._team_id, self._column_optimizer, extra_fields=self._extra_person_fields)

    def _get_person_query(self) -> Tuple[str, Dict]:
        if self._should_join_persons:
            person_query, params = self._person_query.get_query()
            return (
                f"""
            INNER JOIN ({person_query}) {self.PERSON_TABLE_ALIAS}
            ON {self.PERSON_TABLE_ALIAS}.id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id
            """,
                params,
            )
        else:
            return "", {}

    def _get_groups_query(self) -> Tuple[str, Dict]:
        return "", {}

    def _get_date_filter(self) -> Tuple[str, Dict]:

        parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team=self._team)

        query = f"""
        {parsed_date_from}
        {parsed_date_to}
        """

        return query, date_params

    def _get_prop_groups(
        self,
        prop_group: Optional[PropertyGroup],
        person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
        person_id_joined_alias="person_id",
    ) -> Tuple[str, Dict]:
        if not prop_group:
            return "", {}

        if not person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS:
            props_to_filter = self._column_optimizer.property_optimizer.parse_property_groups(prop_group).outer
        else:
            props_to_filter = prop_group

        return parse_prop_grouped_clauses(
            team_id=self._team_id,
            property_group=props_to_filter,
            prepend="global",
            table_name=self.EVENT_TABLE_ALIAS,
            allow_denormalized_props=True,
            person_properties_mode=person_properties_mode,
            person_id_joined_alias=person_id_joined_alias,
        )
