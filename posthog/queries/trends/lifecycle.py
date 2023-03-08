import urllib
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple

from django.db.models.query import Prefetch

from posthog.models.entity import Entity
from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.person.util import get_persons_by_uuids
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery
from posthog.queries.insight import insight_sync_execute
from posthog.queries.person_query import PersonQuery
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.trends.sql import LIFECYCLE_EVENTS_QUERY, LIFECYCLE_PEOPLE_SQL, LIFECYCLE_SQL
from posthog.queries.trends.util import parse_response
from posthog.utils import encode_get_request_params

# Lifecycle takes an event/action, time range, interval and for every period, splits the users who did the action into 4:
#
# 1. NEW - Users who did the action during interval and were also created during that period
# 2. RESURRECTING - Users who did the action during this interval, but not one prior
# 3. RETURNING - Users who did the action during this interval and prior one
# 4. DORMANT - Users who did not do the action during this period but did an action the previous period
#
# To do this, we need for every period (+1 prior to the first period), list of person_ids who did the event/action
# during that period and their creation dates.


class Lifecycle:
    def _format_lifecycle_query(self, entity: Entity, filter: Filter, team: Team) -> Tuple[str, Dict, Callable]:
        event_query, event_params = LifecycleEventQuery(
            team=team, filter=filter, using_person_on_events=team.person_on_events_querying_enabled
        ).get_query()

        return (
            LIFECYCLE_SQL.format(events_query=event_query, interval_expr=filter.interval),
            event_params,
            self._parse_result(filter, entity, team),
        )

    def _parse_result(self, filter: Filter, entity: Entity, team: Team) -> Callable:
        def _parse(result: List) -> List:
            res = []
            for val in result:
                label = "{} - {}".format(entity.name, val[2])
                additional_values = {"label": label, "status": val[2]}
                parsed_result = parse_response(val, filter, additional_values=additional_values, entity=entity)
                parsed_result.update(
                    {"persons_urls": self._get_persons_urls(filter, entity, parsed_result["days"], val[2])}
                )
                res.append(parsed_result)

            return res

        return _parse

    def get_people(self, filter: Filter, team: Team, target_date: datetime, lifecycle_type: str):
        event_query, event_params = LifecycleEventQuery(
            team=team, filter=filter, using_person_on_events=team.person_on_events_querying_enabled
        ).get_query()

        result = insight_sync_execute(
            LIFECYCLE_PEOPLE_SQL.format(events_query=event_query, interval_expr=filter.interval),
            {
                **event_params,
                **filter.hogql_context.values,
                "status": lifecycle_type,
                "target_date": target_date,
                "offset": filter.offset,
                "limit": filter.limit or 100,
            },
            query_type="lifecycle_people",
            filter=filter,
        )
        people = get_persons_by_uuids(team=team, uuids=[p[0] for p in result])
        people = people.prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))

        from posthog.api.person import PersonSerializer

        return PersonSerializer(people, many=True).data

    def _get_persons_urls(self, filter: Filter, entity: Entity, times: List[str], status) -> List[Dict[str, Any]]:
        persons_url = []
        for target_date in times:
            filter_params = filter.to_params()
            extra_params = {
                "entity_id": entity.id,
                "entity_type": entity.type,
                "entity_math": entity.math,
                "target_date": target_date,
                "entity_order": entity.order,
                "lifecycle_type": status,
            }

            parsed_params: Dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/person/lifecycle/?{urllib.parse.urlencode(parsed_params)}",
                }
            )
        return persons_url


class LifecycleEventQuery(EventQuery):
    _filter: Filter

    def get_query(self):
        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
        )

        self.params.update(prop_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        entity_params, entity_format_params = get_entity_filtering_params(
            allowed_entities=[self._filter.entities[0]],
            team_id=self._team_id,
            table_name=self.EVENT_TABLE_ALIAS,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            hogql_context=self._filter.hogql_context,
        )
        self.params.update(entity_params)

        entity_prop_query, entity_prop_params = self._get_prop_groups(
            self._filter.entities[0].property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
            prepend="entity_props",
        )

        self.params.update(entity_prop_params)

        created_at_clause = "person.created_at" if not self._using_person_on_events else "person_created_at"

        null_person_filter = f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)" if self._using_person_on_events else ""

        sample_clause = f"SAMPLE {self._filter.sampling_factor}" if self._filter.sampling_factor else ""

        return (
            LIFECYCLE_EVENTS_QUERY.format(
                event_table_alias=self.EVENT_TABLE_ALIAS,
                person_column=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
                created_at_clause=created_at_clause,
                distinct_id_query=self._get_distinct_id_query(),
                person_query=person_query,
                groups_query=groups_query,
                prop_query=prop_query,
                entity_filter=entity_format_params["entity_query"],
                date_query=date_query,
                null_person_filter=null_person_filter,
                entity_prop_query=entity_prop_query,
                interval=self._filter.interval,
                sample_clause=sample_clause,
            ),
            self.params,
        )

    @cached_property
    def _person_query(self):
        return PersonQuery(
            self._filter,
            self._team_id,
            self._column_optimizer,
            extra_fields=["created_at"],
            entity=self._filter.entities[0],
        )

    def _get_date_filter(self):
        date_params: Dict[str, Any] = {}
        query_date_range = QueryDateRange(self._filter, self._team, should_round=False)
        _, date_from_params = query_date_range.date_from
        _, date_to_params = query_date_range.date_to
        date_params.update(date_from_params)
        date_params.update(date_to_params)

        params = {**date_params, "interval": self._filter.interval}
        # :TRICKY: We fetch all data even for the period before the graph starts up until the end of the last period
        return (
            f"""
            AND timestamp >= toDateTime(dateTrunc(%(interval)s, toDateTime(%(date_from)s, %(timezone)s))) - INTERVAL 1 {self._filter.interval}
            AND timestamp < toDateTime(dateTrunc(%(interval)s, toDateTime(%(date_to)s, %(timezone)s))) + INTERVAL 1 {self._filter.interval}
        """,
            params,
        )

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True if not self._using_person_on_events else False

    def _determine_should_join_persons(self) -> None:
        self._should_join_persons = True if not self._using_person_on_events else False
