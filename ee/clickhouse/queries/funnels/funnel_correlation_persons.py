from typing import Any, Dict, List, Optional, Tuple, Union

from django.db.models.query import QuerySet
from rest_framework.exceptions import ValidationError

from ee.clickhouse.models.property import prop_filter_json_extract
from ee.clickhouse.queries.actor_base_query import ActorBaseQuery, SerializedGroup, SerializedPerson
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.funnels.funnel_event_query import FunnelEventQuery
from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from posthog.constants import FUNNEL_CORRELATION_PERSON_LIMIT, FunnelCorrelationType
from posthog.models import Person
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.team import Team
from posthog.queries.person_query import PersonQuery


class FunnelCorrelationActors(ActorBaseQuery):
    _filter: Filter

    def __init__(self, filter: Filter, team: Team, base_uri: str = "/", **kwargs) -> None:
        self._base_uri = base_uri
        self._filter = filter
        self._team = team

        if not self._filter.correlation_person_limit:
            self._filter = self._filter.with_data({FUNNEL_CORRELATION_PERSON_LIMIT: 100})

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(self, limit_actors: Optional[bool] = True):
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return _FunnelPropertyCorrelationActors(self._filter, self._team, self._base_uri).actor_query(
                limit_actors=limit_actors
            )
        else:
            return _FunnelEventsCorrelationActors(self._filter, self._team, self._base_uri).actor_query(
                limit_actors=limit_actors
            )

    def get_actors(
        self,
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return _FunnelPropertyCorrelationActors(self._filter, self._team, self._base_uri).get_actors()
        else:
            return _FunnelEventsCorrelationActors(self._filter, self._team, self._base_uri).get_actors()


class _FunnelEventsCorrelationActors(ActorBaseQuery):
    _filter: Filter

    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._funnel_correlation = FunnelCorrelation(filter, team, base_uri=base_uri)
        super().__init__(team, filter)

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(self, limit_actors: Optional[bool] = True):

        if not self._filter.correlation_person_entity:
            raise ValidationError("No entity for persons specified")

        assert isinstance(self._filter.correlation_person_entity, Entity)

        funnel_persons_query, funnel_persons_params = self._funnel_correlation.get_funnel_actors_cte()

        prop_filters = self._filter.correlation_person_entity.property_groups

        # TRICKY: We use "events" as an alias here while the eventquery uses "e" by default
        event_query = FunnelEventQuery(self._filter, self._team)
        event_query.EVENT_TABLE_ALIAS = "events"

        prop_query, prop_params = event_query._get_prop_groups(prop_filters)

        conversion_filter = (
            f'AND actors.steps {"=" if self._filter.correlation_persons_converted else "<>"} target_step'
            if self._filter.correlation_persons_converted is not None
            else ""
        )

        event_join_query = self._funnel_correlation._get_events_join_query()

        recording_event_select_statement = (
            ", any(actors.matching_events) AS matching_events" if self._filter.include_recordings else ""
        )

        query = f"""
            WITH
                funnel_actors as ({funnel_persons_query}),
                toDateTime(%(date_to)s) AS date_to,
                toDateTime(%(date_from)s) AS date_from,
                %(target_step)s AS target_step,
                %(funnel_step_names)s as funnel_step_names
            SELECT
                actors.actor_id AS actor_id
                {recording_event_select_statement}
            FROM events AS event
                {event_join_query}
                AND event.event = %(target_event)s
                {conversion_filter}
                {prop_query}
            GROUP BY actor_id
            ORDER BY actor_id
            {"LIMIT %(limit)s" if limit_actors else ""}
            {"OFFSET %(offset)s" if limit_actors else ""}
        """

        params = {
            **funnel_persons_params,
            **prop_params,
            "target_event": self._filter.correlation_person_entity.id,
            "funnel_step_names": [entity.id for entity in self._filter.events],
            "target_step": len(self._filter.entities),
            "limit": self._filter.correlation_person_limit,
            "offset": self._filter.correlation_person_offset,
        }

        return query, params


class _FunnelPropertyCorrelationActors(ActorBaseQuery):
    _filter: Filter

    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._funnel_correlation = FunnelCorrelation(filter, team, base_uri=base_uri)
        super().__init__(team, filter)

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(self, limit_actors: Optional[bool] = True, extra_fields: Optional[List[str]] = None):
        if not self._filter.correlation_property_values:
            raise ValidationError("Property Correlation expects atleast one Property to get persons for")

        funnel_persons_query, funnel_persons_params = self._funnel_correlation.get_funnel_actors_cte()

        conversion_filter = (
            f'funnel_actors.steps {"=" if self._filter.correlation_persons_converted else "<>"} target_step'
            if self._filter.correlation_persons_converted is not None
            else ""
        )

        actor_join_subquery, actor_join_subquery_params = self._get_actor_subquery()
        group_filters, group_filters_params = self._get_group_filters()

        recording_event_select_statement = (
            ", any(funnel_actors.matching_events) AS matching_events" if self._filter.include_recordings else ""
        )

        query = f"""
            WITH
                funnel_actors AS ({funnel_persons_query}),
                %(target_step)s AS target_step
            SELECT
                funnel_actors.actor_id AS actor_id
                {recording_event_select_statement}
            FROM funnel_actors
            {actor_join_subquery}
            WHERE {conversion_filter}
            {group_filters}
            GROUP BY funnel_actors.actor_id
            ORDER BY actor_id
            {"LIMIT %(limit)s" if limit_actors else ""}
            {"OFFSET %(offset)s" if limit_actors else ""}
        """
        params = {
            **funnel_persons_params,
            **actor_join_subquery_params,
            **group_filters_params,
            "target_step": len(self._filter.entities),
            "limit": self._filter.correlation_person_limit,
            "offset": self._filter.correlation_person_offset,
        }

        return query, params

    def _get_actor_subquery(self) -> Tuple[str, Dict[str, Any]]:
        if self.is_aggregating_by_groups:
            actor_join_subquery, actor_join_subquery_params = GroupsJoinQuery(
                self._filter, self._team.pk, join_key="funnel_actors.actor_id"
            ).get_join_query()
        else:
            person_query, actor_join_subquery_params = PersonQuery(
                self._filter,
                self._team.pk,
                entity=Entity(
                    {"id": "person", "type": "events", "properties": self._filter.correlation_property_values}
                ),
            ).get_query()

            actor_join_subquery = f"""
                JOIN ({person_query}) person
                ON person.id = funnel_actors.actor_id
            """

        return actor_join_subquery, actor_join_subquery_params

    def _get_group_filters(self):
        if self.is_aggregating_by_groups:
            conditions, params = [""], {}

            properties = self._filter.correlation_property_values

            if properties:
                for index, property in enumerate(properties):
                    if property.type != "group":
                        continue

                    expr, prop_params = prop_filter_json_extract(
                        property,
                        index,
                        prepend=f"group_type_{property.group_type_index}",
                        prop_var=f"group_properties_{property.group_type_index}",
                        allow_denormalized_props=True,
                    )

                    conditions.append(expr)
                    params.update(prop_params)

            return " ".join(conditions), params
        else:
            return "", {}
