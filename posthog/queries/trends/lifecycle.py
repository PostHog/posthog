import urllib
from collections.abc import Callable
from typing import Any

from posthog.schema import PersonsOnEventsMode

from posthog.models.entity import Entity
from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters import Filter
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team import Team
from posthog.queries.event_query import EventQuery
from posthog.queries.person_query import PersonQuery
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.trends.sql import LIFECYCLE_EVENTS_QUERY, LIFECYCLE_SQL
from posthog.queries.trends.util import parse_response
from posthog.queries.util import get_person_properties_mode
from posthog.utils import encode_get_request_params, generate_short_id

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
    def _format_lifecycle_query(self, entity: Entity, filter: Filter, team: Team) -> tuple[str, dict, Callable]:
        event_query, event_params = LifecycleEventQuery(
            team=team, filter=filter, person_on_events_mode=team.person_on_events_mode
        ).get_query()

        return (
            LIFECYCLE_SQL.format(events_query=event_query, interval_expr=filter.interval),
            event_params,
            self._parse_result(filter, entity, team),
        )

    def _parse_result(self, filter: Filter, entity: Entity, team: Team) -> Callable:
        def _parse(result: list) -> list:
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

    def get_people(self, filter: LifecycleFilter, team: Team):
        from posthog.queries.trends.lifecycle_actors import LifecycleActors

        _, serialized_actors, _ = LifecycleActors(filter=filter, team=team, limit_actors=True).get_actors()
        return serialized_actors

    def _get_persons_urls(self, filter: Filter, entity: Entity, times: list[str], status) -> list[dict[str, Any]]:
        persons_url = []
        cache_invalidation_key = generate_short_id()
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

            parsed_params: dict[str, str] = encode_get_request_params({**filter_params, **extra_params})
            persons_url.append(
                {
                    "filter": extra_params,
                    "url": f"api/person/lifecycle/?{urllib.parse.urlencode(parsed_params)}&cache_invalidation_key={cache_invalidation_key}",
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
            person_properties_mode=get_person_properties_mode(self._team),
            person_id_joined_alias=self._person_id_alias,
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
            person_properties_mode=get_person_properties_mode(self._team),
            hogql_context=self._filter.hogql_context,
        )
        self.params.update(entity_params)

        entity_prop_query, entity_prop_params = self._get_prop_groups(
            self._filter.entities[0].property_groups,
            person_properties_mode=get_person_properties_mode(self._team),
            person_id_joined_alias=self._person_id_alias,
            prepend="entity_props",
        )

        self.params.update(entity_prop_params)

        created_at_clause = (
            "person.created_at" if self._person_on_events_mode == PersonsOnEventsMode.DISABLED else "person_created_at"
        )

        null_person_filter = (
            ""
            if self._person_on_events_mode == PersonsOnEventsMode.DISABLED
            else f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)"
        )

        sample_clause = "SAMPLE %(sampling_factor)s" if self._filter.sampling_factor else ""
        self.params.update({"sampling_factor": self._filter.sampling_factor})

        return (
            LIFECYCLE_EVENTS_QUERY.format(
                event_table_alias=self.EVENT_TABLE_ALIAS,
                person_column=self._person_id_alias,
                created_at_clause=created_at_clause,
                distinct_id_query=self._get_person_ids_query(),
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
        date_params: dict[str, Any] = {}
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
        self._should_join_distinct_ids = (
            self._person_on_events_mode != PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
        )

    def _determine_should_join_persons(self) -> None:
        self._should_join_persons = self._person_on_events_mode == PersonsOnEventsMode.DISABLED
